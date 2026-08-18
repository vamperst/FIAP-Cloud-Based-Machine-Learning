# Evidência — o que cada camada realmente prova

"Aplicou sem erro" não é evidência de que existe um sistema de Machine Learning. Este lab
produz cinco camadas de artefato, e cada uma responde a uma pergunta diferente. A regra é
simples: **toda afirmação da evidência vem de uma chamada de API à AWS ou de um cálculo
sobre bytes em disco** — nada é inferido de "o Terraform não reclamou".

## As camadas

| Camada | Arquivo | Pergunta que responde | Como obtém a resposta |
|---|---|---|---|
| Armazenamento | seção `aws.input_channels` do `evidence.json` | os canais de treino existem em S3 com os bytes certos? | `HeadObject` por canal + comparação de tamanho com o arquivo local |
| Treino | `artifacts/evidence/training_job.json` | o job terminou e produziu artefato? | `DescribeTrainingJob` + `HeadObject` |
| Serving | `artifacts/evidence/smoke_prediction.json` | o endpoint responde e o contrato de payload vale? | `DescribeEndpoint` + `InvokeEndpoint` |
| Qualidade | `artifacts/evidence/evaluation.json` / `.md` | o modelo é melhor que um baseline honesto? | 600 linhas de teste pelo endpoint + métricas |
| Sistema | `artifacts/evidence/evidence.json` / `.md` | a cadeia inteira está fechada e rastreável? | consolida as quatro acima + outputs + git |

## Camada 1 — armazenamento (`aws.input_channels`)

Prova que os canais que o SageMaker vai ler **existem em S3 com os bytes certos**, e não
que um `aws_s3_object` foi declarado. Para cada canal: `HeadObject`, tamanho em bytes,
ETag e comparação com o tamanho do arquivo local que o gerador escreveu. Se o upload
falhar pela metade ou o dataset for regenerado sem re-subir, `size_matches_local` fica
falso e a cadeia quebra antes de alguém culpar o modelo.

## Camada 2 — treino (`training_job.json`)

Prova que houve **computação finita com saída durável**, não que um recurso foi declarado.

Contém: nome e ARN do job, `TrainingJobStatus` terminal, `SecondaryStatus`,
`TrainingStartTime`/`TrainingEndTime`, duração faturada, imagem, hiperparâmetros, canais de
entrada, a URI do artefato **lida de `ModelArtifacts.S3ModelArtifacts`**, e o resultado do
`HeadObject` (tamanho em bytes e ETag).

Dois pontos deliberados:

1. a URI **não é montada** por convenção de caminho — vem da API que criou o artefato
   (ver [ADR 0001](adr/0001-artifact-uri-resolution.md));
2. `HeadObject` com tamanho > 0 é a prova de existência. Sem isso, `Completed` é apenas um
   status: o deploy seguinte falharia com um erro obscuro de download em vez de um erro
   claro no gate.

Se o status terminal for `Failed`, `wait_training.py` imprime o `FailureReason` da AWS e o
caminho do log group no CloudWatch, e sai diferente de zero. O erro é da AWS, não uma
paráfrase.

## Camada 3 — serving (`smoke_prediction.json`)

Prova que a **fronteira artefato → serviço** foi atravessada com o contrato correto.

Envia dois registros fixos, escolhidos para serem inequívocos:

| Registro | Perfil | Expectativa |
|---|---|---|
| `high_risk` | 2 meses, R$ 220/mês, 6 chamados, 30 dias de atraso, uso 15, sem contrato anual, sem plano premium | probabilidade alta |
| `low_risk` | 66 meses, R$ 45/mês, 0 chamado, 0 atraso, uso 92, contrato anual, plano premium | probabilidade baixa |

Quatro asserções, todas booleanas no JSON:

- `all_finite` — nenhuma resposta `NaN`/`inf`;
- `all_in_unit_interval` — toda probabilidade em `[0, 1]`;
- `one_probability_per_row` — cardinalidade da resposta igual à do payload;
- `high_risk_scored_above_low_risk` — sanidade direcional.

A última é a que pega **ordem de features trocada**. Um payload com colunas embaralhadas
passa nas três primeiras e falha nesta. É a razão de ela existir.

## Camada 4 — qualidade (`evaluation.json` + `evaluation.md`)

Prova que o modelo tem **valor de decisão**, não só disponibilidade.

As 600 linhas de teste vão ao endpoint em lotes de 250 (limite de payload do
`InvokeEndpoint`), sem rótulo. Os rótulos ficam locais, em `test_labels.csv`, e só se juntam
às predições na hora de calcular métrica.

Reportado sempre: baseline da classe majoritária, matriz de confusão, acurácia, precision,
recall, F1, ROC-AUC, PR-AUC, Brier score e calibração em faixas de probabilidade.

Por que este conjunto:

- **baseline da classe majoritária** — com prevalência 0.34, prever "ninguém cancela" dá
  ~66% de acurácia. Sem esse número, 74% de acurácia parece bom;
- **matriz de confusão** — separa os dois erros. Em churn, falso negativo (cliente que
  cancela e você não agiu) e falso positivo (desconto dado a quem ia ficar) têm custos
  diferentes;
- **ROC-AUC e PR-AUC** — qualidade do *ranking*, independente de limiar. PR-AUC é a mais
  informativa sob desbalanceamento;
- **Brier e calibração** — a probabilidade é confiável como número, ou só como ordenação?
  Se você vai usar o score em regra de negócio ("acima de 0.7, ligar"), calibração importa
  mais que acurácia.

O limiar 0.5 é **fixo e pedagógico**, registrado em `decision_threshold`. Não é o limiar
ótimo — escolher limiar por custo de erro é assunto de aula posterior. Fixá-lo mantém a
avaliação reproduzível.

**Verificação cruzada:** todas as métricas são implementadas de forma transparente em
`src/lab1/metrics.py` (para poderem ser lidas em aula) e conferidas em tempo de execução
contra o scikit-learn. O JSON traz `sklearn_crosscheck.agrees` e a maior diferença
absoluta; tolerância 1e-6. Métrica escrita à mão sem conferência é uma fonte silenciosa de
erro.

Portões de aceitação, de `config/lab.yaml`: `roc_auc >= 0.75`, `f1 >= 0.50` e acurácia
estritamente acima do baseline majoritário. Falhar em qualquer um sai diferente de zero.

## Camada 5 — sistema (`evidence.json` + `evidence.md`)

Prova que a **cadeia inteira** existe e é rastreável a uma execução específica. Sete seções:
ambiente, dados, treino, artefato de modelo, serving, avaliação e veredito.

O veredito é um dicionário `chain` de sete booleanos — um por elo:

| Elo | Verdadeiro quando |
|---|---|
| `storage: dataset generated and fingerprinted` | o manifesto existe, com SHA-256 por arquivo |
| `storage: training channels proven in S3` | `HeadObject` achou cada canal e o tamanho bate com o arquivo local |
| `training: job reached Completed` | `DescribeTrainingJob` retornou status terminal `Completed` |
| `artifact: model.tar.gz proven in S3` | `HeadObject` achou o objeto com tamanho > 0 |
| `serving: endpoint InService` | `DescribeEndpoint` retornou `InService` |
| `serving: deterministic smoke inference passed` | as quatro asserções do smoke passaram |
| `evidence: test-set metrics meet acceptance` | os portões de ROC-AUC, F1 e baseline fecharam |

Qualquer `false` → código de saída diferente de zero. Não existe evidência "parcialmente
verde": ou a cadeia está fechada, ou o lab não está entregue.

Registra também `git_commit`/`git_dirty` e as versões de Terraform, provider, Python,
boto3, numpy e scikit-learn — sem isso a evidência descreve um resultado que ninguém sabe
reproduzir.

## Higiene: o que a evidência nunca contém

- credenciais, chaves de acesso, secret keys, session tokens — nada disso é impresso em
  qualquer script do lab;
- o ARN do caller aparece com o número da conta **mascarado** nos logs (`mask_arn`);
- `artifacts/` é ignorado pelo git na íntegra: dataset, predições e evidência são
  descartáveis e regeneráveis.

## Limpeza também é evidência (`verify_clean.json`)

Depois de `terraform destroy`, `verify_clean.py` não confia no destroy: varre a conta pelo
prefixo do projeto (`ListEndpoints`, `ListEndpointConfigs`, `ListModels` com `NameContains`)
e checa o bucket com `HeadBucket`.

Duas distinções que importam:

- **`ResourceNotFound` é sucesso** (já está limpo); **erro de permissão nunca é
  engolido** — um `AccessDenied` significa "não sei se está limpo", e isso é reportado, não
  mascarado como PASS;
- **histórico de training job não é recurso faturável.** Jobs terminados aparecem para
  sempre no `ListTrainingJobs` e não custam nada. O relatório diz isso explicitamente, para
  o aluno não sair achando que precisa "limpar" o histórico — ou pior, que o lab deixou algo
  ligado.

O que **custa** é o endpoint em tempo real, e é ele que o relatório precisa provar ausente.

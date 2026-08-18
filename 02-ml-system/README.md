# 02 — Do modelo ao sistema de Machine Learning

Implementação técnica do Lab 1: provisiona, com um comando, a cadeia completa
**armazenamento → treino → artefato → serving → avaliação → evidência** na AWS, e prova cada
elo com chamada de API real.

Este README é a **referência técnica** do lab (pré-requisitos, superfície de comandos,
custos, troubleshooting). O roteiro pedagógico do aluno é material separado.

> [!WARNING]
> **Pré-requisitos — confira antes de começar:**
>
> - [ ] Setup do [01 — Codespaces](../01-create-codespaces/README.md) concluído.
> - [ ] Sessão do AWS Academy Learner Lab **iniciada** e credenciais copiadas para o ambiente (elas expiram a cada 4 horas).
> - [ ] Região `us-east-1` (o lab recusa qualquer outra, por restrição do Academy).
> - [ ] `make doctor` passando — é o portão que confirma toolchain, credenciais, região e `LabRole`.
>
> **Custo:** o endpoint em tempo real (`ml.m5.large`) fatura enquanto estiver de pé. O ciclo
> completo custa alguns centavos de dólar; **esquecer o endpoint ligado é o único jeito de
> gastar de verdade.** `make e2e` destrói tudo ao final, inclusive se algo falhar no meio.

## Principais pontos de aprendizagem

- O que precisa existir entre "treinamos um modelo" e "temos uma capacidade de ML
  reproduzível" — as quatro fronteiras de contrato, não os nomes de produto.
- Por que **computação de treino é finita** e **computação de serving é persistente**, e por
  que só a segunda aparece na fatura depois da aula.
- Por que a URI do artefato é **lida da API** que a produziu, e não montada por convenção de
  caminho.
- Por que um contrato de dados só vale se for **executável** — e o que acontece quando o
  rótulo vaza para o payload de inferência.
- Por que acurácia sozinha não é evidência de valor: baseline majoritário, matriz de
  confusão, ROC-AUC, PR-AUC, Brier e calibração.

## O que você terá ao final

Um endpoint SageMaker em tempo real servindo um XGBoost treinado na própria conta, avaliado
contra 600 linhas de teste que nunca entraram no treino, com pacote de evidência em
`artifacts/evidence/` — e a conta limpa, comprovada por varredura de API.

## Superfície de comandos

```bash
make doctor        # versões de ferramenta + identidade/região/LabRole na AWS
make data          # gera o dataset determinístico (semente 20260817)
make validate      # terraform init + fmt -check + validate
make plan          # plano do estágio atual
make apply         # provisiona tudo (dois estágios, um comando - ver ADR 0001)
make predict       # inferência de fumaça determinística (2 registros)
make evaluate      # 600 linhas de teste pelo endpoint + métricas
make evidence      # consolida o pacote de evidência
make destroy       # destrói todos os recursos gerenciados
make verify-clean  # varre a conta e prova que nada faturável sobrou
make e2e           # ciclo completo com limpeza garantida por trap
make clean         # apaga artefatos locais (nunca toca na AWS)
```

Ciclo completo, do zero ao limpo:

```bash
make e2e
```

Se algo falhar no meio, o `trap` roda `destroy` + `verify-clean` de qualquer forma e o
código de saída original é preservado. Para inspecionar o endpoint depois do ciclo:

```bash
make e2e KEEP_RESOURCES=1   # o endpoint FICA DE PÉ e continua faturando
make destroy                # rode isto assim que terminar
```

Nenhum comando crítico está escondido: cada alvo do `Makefile` é uma linha de
`terraform` ou de `python scripts/...` que você pode ler e executar à mão.

## Convenção de saída dos scripts

**stdout carrega o resultado** (JSON, para pipe/redirect); **stderr carrega progresso e
diagnóstico**. Por isso os alvos do `Makefile` redirecionam stdout para `/dev/null` — a
narração que você vê é stderr, e o dado fica disponível quando você quiser capturá-lo:

```bash
PYTHONPATH=src python3 scripts/validate_data.py > relatorio.json
```

## Arquitetura em uma tela

```text
S3 (canais train/validation)
   |
   v
SageMaker Training Job          1 x ml.m5.large, File mode, XGBoost 1.7-1
   |
   v
S3 model.tar.gz                 URI lida de DescribeTrainingJob + provada com HeadObject
   |
   v
SageMaker Model -> Endpoint Configuration -> Endpoint em tempo real
   |
   v
Boto3 InvokeEndpoint            600 linhas de teste, sem rótulo, em lotes de 250
   |
   v
artifacts/evidence/             evaluation.{json,md} + evidence.{json,md}
```

## Estrutura

```text
02-ml-system/
├── config/          lab.yaml (fonte única de parâmetros) + schema.json (tipos e payload)
├── src/lab1/        dataset, contrato de dados, métricas, helpers AWS
├── scripts/         8 scripts de controle e evidência (stdout = resultado)
├── terraform/       topologia AWS: s3, training, model, endpoint, outputs
└── artifacts/       gerado, gitignored: dados e evidência (descartáveis)
```

Divisão de responsabilidade: **Terraform** é dono da topologia AWS; **Python** é dono de
dados, contratos, espera de job, invocação e métricas; **Make** é dono da ordem.

## Determinismo e versões

Tudo pinado com `=` — sem faixa de versão, sem "latest":

| Componente | Versão |
|---|---|
| Terraform | 1.15.8 |
| provider `hashicorp/aws` | 6.60.0 |
| provider `hashicorp/random` | 3.9.0 |
| Python | 3.12 |
| imagem de treino/serving | `sagemaker-xgboost:1.7-1` (`683313688378.dkr.ecr.us-east-1.amazonaws.com`) |

O `.terraform.lock.hcl` está versionado com checksums para linux/darwin em amd64 e arm64,
então o Codespaces e a máquina do professor resolvem exatamente os mesmos binários. O
dataset é determinístico por semente: mesma semente, mesmos bytes.

O toolchain vem de `.devcontainer/`: `postCreate.sh` instala o Terraform 1.15.8 conferindo
o SHA-256 oficial (que está versionado no script — troca silenciosa do artefato remoto
quebra o build em vez de passar) e cria o `.venv` com as versões de `requirements.txt`.
No Codespaces, escolha a configuração **Cloud-Based ML — Lab 1 (02-ml-system)** na criação
do codespace: o Codespaces só lista configurações que estão em `.devcontainer/` na raiz do
repositório, então existe uma lá que aponta o workspace para esta pasta. Localmente, use
*Reopen in Container* sobre `02-ml-system/`. Em qualquer caminho, `make doctor` é quem
confirma se o toolchain está correto.

Os targets chamam `.venv/bin/python` diretamente quando ele existe, em vez de confiar no
`PATH`: shell de login re-executa `/etc/profile` e descarta o `.venv/bin` que o container
prepende, o que faria o lab rodar com um interpretador sem `boto3`.

## O que este lab nunca faz

- Não cria IAM (usa a `LabRole` pré-existente do Academy).
- Não pede clique em console, nem notebook, nem SageMaker Studio.
- Não imprime credencial, access key, secret key ou session token — em nenhum script. O ARN
  do caller aparece com o número da conta mascarado.
- Não versiona estado do Terraform, dataset gerado, predições ou evidência.
- Não adivinha caminho de artefato em S3.

## Troubleshooting

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `ExpiredToken` / `InvalidClientTokenId` | credenciais do Academy venceram (ciclo de 4h) | reinicie a sessão do Learner Lab e recopie as credenciais |
| `session region is X but this lab requires 'us-east-1'` | perfil sem região ou com outra | `export AWS_DEFAULT_REGION=us-east-1` |
| `NoSuchEntity: role LabRole` | sessão não é do Academy, ou conta sem `LabRole` | confirme que está na conta do Learner Lab |
| gate falha com `Failed` no training job | erro dentro do job | o gate imprime o `FailureReason` da AWS e o log group do CloudWatch |
| `make apply` sem `artifact.auto.tfvars.json` | o estágio 1 não completou | rode `make apply` novamente: os estágios são idempotentes |
| `ResourceLimitExceeded` | cota de `ml.m5.large` da conta | rode `make destroy` e tente de novo; endpoint órfão de run anterior costuma ser a causa |
| `verify-clean` reporta job em `ListTrainingJobs` | histórico de job terminado | **não é recurso faturável**; o relatório diz isso explicitamente |

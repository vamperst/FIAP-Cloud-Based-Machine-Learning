# Contrato de dados

O contrato de dados deste lab é **executável**: nada aqui é convenção documentada e
esquecida. `scripts/validate_data.py` roda 48 verificações e falha com código de saída
diferente de zero se qualquer uma quebrar.

Fonte única de verdade: `config/lab.yaml` (parâmetros) + `config/schema.json` (tipos e
contratos de payload). `tests/test_config_drift.py` falha se `lab.yaml` e
`terraform/variables.tf` divergirem.

## Features, rótulo e identificador

Ordem canônica das features (`schema.json:feature_order`) — a ordem **é** parte do contrato:

| # | Coluna | Tipo | Unidade | Faixa documentada |
|---|---|---|---|---|
| 1 | `tenure_months` | `int64` | meses | 1–72 |
| 2 | `monthly_charges` | `float64` | BRL/mês (2 casas) | 20–250 |
| 3 | `support_calls_90d` | `int64` | chamados | 0–12 |
| 4 | `payment_delay_days` | `float64` | dias (2 casas) | 0–45 |
| 5 | `usage_score` | `float64` | índice 0–100 (2 casas) | 0–100 |
| 6 | `annual_contract` | `int64` | binário | 0 ou 1 |
| 7 | `premium_plan` | `int64` | binário | 0 ou 1 |

- **Rótulo:** `churn` ∈ {0, 1}; `1` = o cliente cancelou. Prevalência exigida em `[0.20, 0.50]`.
- **Identificador:** `observation_id`, inteiro único. **Nunca** entra no modelo — é
  ferramenta de auditoria (prova de disjunção entre splits e conferência de rótulos).

## Contratos de arquivo

| Arquivo | Header | Colunas | Rótulo | Consumidor |
|---|---|---|---|---|
| `source.csv` | sim | 9 (`observation_id` + 7 features + `churn`) | sim | auditoria humana e testes |
| `model_train_headerless.csv` | **não** | 8 | **primeira coluna** | canal `train` do SageMaker |
| `model_validation_headerless.csv` | **não** | 8 | **primeira coluna** | canal `validation` |
| `model_test_features_headerless.csv` | **não** | 7 | **ausente** | payload de `InvokeEndpoint` |
| `test_labels.csv` | sim | 2 (`observation_id`, `churn`) | sim | avaliação externa ao endpoint |
| `dataset_manifest.json` | — | — | — | fingerprints e proveniência |

### A assimetria que quebra labs em silêncio

O XGBoost built-in do SageMaker espera CSV **sem header** e com o **rótulo na primeira
coluna** no treino. Na inferência espera **só as features**, na mesma ordem, sem rótulo.

Se o rótulo vazar para o payload de inferência, o endpoint não retorna erro: ele lê
`churn` como se fosse `tenure_months`, desloca todas as features e devolve probabilidades
plausíveis e erradas. É exatamente por isso que `src/lab1/data_contract.py` rejeita:

- feature faltando ou coluna desconhecida;
- presença de `churn` (vazamento de rótulo) ou de `observation_id` (vazamento de ID);
- valor não finito (`NaN`, `inf`);
- valor fracionário em coluna `int64` (ex.: `annual_contract = 0.5`);
- ordem diferente de `feature_order`.

O serializador em `data_contract.py` é o **único** caminho para gerar payload. O teste
`payload.roundtrip_matches_file` re-serializa as 600 linhas de teste e exige igualdade
byte a byte com o arquivo que vai para o endpoint — se o serializador e o gerador de dados
divergirem, o contrato acusa.

## Splits: independência provada, não afirmada

4000 linhas, split estratificado 70/15/15 com semente `20260817`:

| Split | Linhas | Prevalência |
|---|---|---|
| `train` | 2800 | 0.337500 |
| `validation` | 600 | 0.338333 |
| `test` | 600 | 0.336667 |
| fonte | 4000 | 0.337500 |

Provas mecânicas (`tests/test_split_integrity.py` e `validate_data.py`):

1. **partição exata** — 2800 + 600 + 600 = 4000, sem sobra e sem duplicata;
2. **disjunção por `observation_id`** — interseção vazia par a par;
3. **estratificação** — prevalência de cada split próxima da fonte;
4. **rótulos de teste consistentes** — todo `observation_id` de `test_labels.csv` existe em
   `source.csv` com o mesmo `churn`; 0 divergências;
5. **contagens conferem com o manifesto** — manifesto e bytes em disco concordam.

O conjunto de teste **nunca** vai para o SageMaker como canal. Ele existe fora do treino,
é enviado ao endpoint sem rótulo e avaliado localmente. Essa é a razão de ele existir.

## Determinismo e fingerprint

Mesma semente → mesmos bytes. Verificado gerando o dataset duas vezes em diretórios
diferentes e comparando os seis arquivos com `cmp`.

`dataset_manifest.json` é **livre de timestamp** por decisão de projeto: se carregasse hora
de geração, dois runs idênticos produziriam manifestos diferentes e o determinismo deixaria
de ser verificável. O manifesto registra `schema_version`, `seed`, `feature_order`,
contagens, prevalências e SHA-256 de cada arquivo — `manifest.fingerprints_match_files`
recalcula os hashes e compara.

## Processo gerador (DGP)

Regressão logística sintética com coeficientes fixos em `dataset.py`: `tenure_months`,
`annual_contract`, `premium_plan` e `usage_score` empurram o risco para baixo;
`support_calls_90d`, `payment_delay_days` e `monthly_charges` empurram para cima. O rótulo
sai de uma amostra Bernoulli da probabilidade, então o problema tem **ruído irredutível** —
não existe acurácia 100%, e é isso que se quer: um lab onde o modelo acerta tudo ensina a
lição errada sobre avaliação.

Sinal calibrado para que um XGBoost razoável fique bem acima do baseline sem chegar perto
do perfeito. Ver [ADR 0002](adr/0002-synthetic-dataset.md).

## Como quebrar o contrato de propósito

`tests/test_failure_paths.py` corrompe uma coisa por vez e exige que a verificação
correspondente fique vermelha: header no arquivo headerless, rótulo no payload de
inferência, contagem de linhas errada, `NaN`, valor fora da faixa, ID duplicado, rótulo
divergente do `source.csv`, fingerprint desatualizado. Um contrato que nunca falhou não é
um contrato — é um comentário.

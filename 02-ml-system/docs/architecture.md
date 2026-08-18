# Arquitetura — capacidade primeiro, AWS depois

Este documento descreve **o que precisa existir** entre "treinamos um modelo" e "temos uma
capacidade de Machine Learning reproduzível e consumível" — e só depois qual serviço AWS
realiza cada peça. A ordem é deliberada: os nomes de produto mudam, as fronteiras não.

## Cadeia de capacidades (visão portátil)

```text
ambiente de desenvolvimento
        |
        v
contrato de dados executável
        |
        v
dados de treino duráveis ----> computação de treino finita
                                        |
                                        v
                            artefato de modelo durável
                                        |
                                        v
                            runtime de serving compatível
                                        |
                                        v
                              serviço de predição
                                        |
                                        v
                          avaliação + evidência
```

Nenhuma dessas caixas é um produto. Cada uma é um **contrato** que alguém tem que honrar.

## As quatro fronteiras e o que cada uma exige

### Fronteira 1 — dados → treino

| Pergunta do contrato | Onde este lab responde |
|---|---|
| Qual o schema e a ordem das features? | `config/schema.json` (`feature_order`) |
| Qual a semântica do rótulo? | `config/lab.yaml` (`label: churn`, 1 = churn) |
| Treino/validação/teste são independentes? | `test_split_integrity.py` prova disjunção por `observation_id` |
| Existe vazamento (leakage)? | `data_contract.py` rejeita rótulo e ID no payload de inferência |
| A versão dos dados é identificável? | SHA-256 por arquivo em `dataset_manifest.json` |

### Fronteira 2 — treino → artefato

| Pergunta do contrato | Onde este lab responde |
|---|---|
| Qual runtime gerou o artefato? | output `training_image` (XGBoost 1.7-1, tag fixa) |
| Quais dados e configuração o geraram? | outputs `training_channels` + `hyperparameters` |
| Qual o formato? | `model.tar.gz` (convenção SageMaker) |
| Onde está persistido? | `s3://<bucket>/models/<job>/output/model.tar.gz` |
| É rastreável? | `DescribeTrainingJob` é a fonte da URI; `HeadObject` prova a existência |

O ponto pedagógico: a URI do artefato **não é adivinhada** a partir de uma convenção de
caminho. Ela é lida da API que a produziu. Ver [ADR 0001](adr/0001-artifact-uri-resolution.md).

### Fronteira 3 — artefato → serving

| Pergunta do contrato | Onde este lab responde |
|---|---|
| O runtime de serving é compatível? | mesma imagem ECR do treino, reusada no `aws_sagemaker_model` |
| A semântica e a ordem das features são idênticas? | `feature_order` é a única fonte, usada por treino e inferência |
| Qual o payload esperado? | `text/csv`, sem header, 7 colunas, **sem** rótulo |
| Qual o formato da resposta? | CSV de probabilidades em `[0, 1]`, uma por linha |
| O deploy está pronto? | `aws_sagemaker_endpoint` só retorna em `InService` |

Assimetria que vale mostrar em aula: o CSV de **treino** tem 8 colunas com o rótulo na
primeira posição; o de **inferência** tem 7 e nenhum rótulo. Trocar isso não gera erro —
gera predição silenciosamente errada. Por isso o contrato é executável, não prosa.

### Fronteira 4 — serving → decisão/evidência

| Pergunta do contrato | Onde este lab responde |
|---|---|
| O endpoint está operacional? | `predict.py` exige `EndpointStatus == InService` |
| A resposta é válida? | finitude, faixa `[0,1]`, uma probabilidade por linha |
| O modelo bate um baseline honesto? | acurácia da classe majoritária no teste |
| As métricas dizem mais que acurácia? | matriz de confusão, precision, recall, F1, ROC-AUC, PR-AUC, Brier, calibração |
| A evidência amarra o resultado a uma execução? | `evidence.json` liga conta, região, job, artefato, endpoint, dados e git |

## Realização AWS

```text
GitHub Codespaces (Terraform + Python)
        |
        +---------------------------+
        |                           |
        v                           v
   S3 (input)              control plane AWS
        |                           |
        v                           |
SageMaker Training Job <------------+
  1 x ml.m5.large, File mode
        |
        v
S3 model.tar.gz
        |
        v
SageMaker Model
        |
        v
Endpoint Configuration
        |
        v
Endpoint em tempo real
  1 x ml.m5.large
        |
        v
Boto3 InvokeEndpoint + avaliação no conjunto de teste
        |
        v
evidence.json / evidence.md
```

### Quem é dono de quê

| Camada | Responsabilidade | Não faz |
|---|---|---|
| Terraform | topologia de recursos AWS | não gera dados, não avalia modelo |
| Python | dados, contratos, espera de job, invocação, métricas, evidência | não cria recurso de infraestrutura |
| Make | ordem e conveniência | não esconde comando crítico (todos são inspecionáveis) |

## Trade-offs deliberadamente visíveis

Estas escolhas são adequadas **a este lab**, não recomendações universais de produção.

| Decisão | Benefício aqui | Custo/limitação |
|---|---|---|
| Dados sintéticos numéricos | determinismo, zero download | menos realismo de domínio |
| XGBoost built-in | runtime gerenciado estável | não ensina empacotamento de container |
| Uma `ml.m5.large` | compatível com Academy, fácil de raciocinar | não é dimensionamento de produção |
| Training job gerenciado | deixa a computação finita explícita | a plataforma abstrai o host |
| Endpoint em tempo real | fronteira de serving e contrato de API nítidos | custa enquanto estiver de pé |
| Terraform | topologia explícita e repetível | semântica de *job* é desconfortável em IaC declarativa (ver ADR 0001) |
| `LabRole` | atende à restrição do Academy | não é desenho de menor privilégio |
| Sem VPC própria | reduz complexidade do primeiro lab | não é arquitetura de rede/segurança de referência |

### Por que não SageMaker Studio?

Escolha pedagógica, não julgamento técnico: no Codespaces a arquitetura permanece
explícita e programável. Studio misturaria UX de plataforma com as fronteiras que a aula
quer tornar visíveis.

### Por que tempo real já no Lab 1?

Porque é o modo que torna óbvia a separação entre **computação de treino finita** e
**computação de serving persistente**. Não é o melhor modo de serving em geral — a Aula 2
compara síncrono provisionado, serverless, assíncrono e batch com trade-offs de latência,
throughput e custo.

## O que troca se o provedor mudar

| Peça | AWS aqui | Equivalente em outro lugar |
|---|---|---|
| Armazenamento durável | S3 | GCS, Azure Blob, MinIO |
| Treino finito | SageMaker Training Job | Kubernetes Job, Vertex AI Training, Batch |
| Artefato | `model.tar.gz` em S3 | qualquer blob versionado |
| Serving | SageMaker Endpoint | KServe, Vertex Endpoint, container atrás de um LB |
| Evidência | JSON/Markdown do lab | idêntico — é código, não serviço |

A cadeia de capacidades sobrevive à troca. É esse o conteúdo da aula.

# ADR 0001 — como a URI do artefato de treino chega ao Model

- **Status:** aceito
- **Data:** 2026-08-17
- **Contexto de versão:** Terraform 1.15.8, provider `hashicorp/aws` 6.60.0
- **Verificado em:** conta AWS Academy Learner Lab real, `us-east-1`

## Contexto

A cadeia de capacidades do lab exige atravessar a fronteira **artefato → serving**: o
`aws_sagemaker_model` precisa da URI do `model.tar.gz` que o training job produziu. Numa
IaC declarativa, o caminho natural seria referenciar um atributo computado do recurso de
treino e deixar o grafo de dependências resolver a ordem.

Antes de escrever qualquer coisa, o schema do provider foi inspecionado (não adivinhado),
como manda a spec.

## Achados no provider 6.60.0

**Achado 1 — o recurso de training NÃO espera a conclusão.** O `Create` de
`aws_sagemaker_training_job` retorna assim que o job atinge `InProgress`. Confirmado no run
real: `Creation complete after 1s`. Um `apply` verde **não** significa modelo treinado.

**Achado 2 — não existe atributo de artefato.** O recurso exporta apenas `arn` e
`tags_all`. Não há `model_artifacts`, não há `s3_model_artifacts`. Não existe atributo a
referenciar.

**Achado 3 (colateral) — `s3_data_distribution_type` tem default silencioso e errado.**
Omitindo o campo, o provider envia `ShardedByS3Key` à API — confirmado por
`DescribeTrainingJob` — enquanto o default documentado da AWS é `FullyReplicated`. O apply
então falha com `Provider produced inconsistent result after apply` (o provider devolve um
valor diferente do que o plano previa). Com uma instância o efeito prático é nulo, mas com
`instance_count > 1` isso **dividiria os dados de treino entre as instâncias sem avisar**.
O campo passou a ser explícito nos dois canais.

Consequência dos achados 1 e 2 juntos: um único grafo Terraform não consegue ligar treino a
model. Se o `aws_sagemaker_model` fosse criado no mesmo apply, ele correria contra um job
ainda em `Downloading` e falharia ao baixar um artefato que ainda não existe.

## Alternativas consideradas

**A. Montar a URI por convenção de caminho.**
`s3://<bucket>/models/<job_name>/output/model.tar.gz` é a convenção do SageMaker e daria um
único apply. Rejeitada: adivinhar o caminho de saída de outro sistema é frágil (a convenção
pode mudar, e o `apply` não erraria — só entregaria um endpoint quebrado) e ensina o hábito
errado. Vale para ler o caminho, não para confiar nele.

**B. `null_resource` com `local-exec` esperando o job.**
Funcionaria, mas esconde controle de fluxo imperativo dentro do grafo, não tem estado
inspecionável e falha de formas difíceis de depurar em sala.

**C. Provisionar o serving fora do Terraform, via Boto3.**
Resolveria a espera, mas jogaria fora a topologia declarativa — justamente o que a aula quer
tornar visível — e deixaria recursos faturáveis sem `terraform destroy`.

**D. Dois applies atrás de um único `make apply`, com gate em Python.** Escolhida.

## Decisão

Dois estágios, **um comando**. `make apply` executa:

```text
stage 1/2   terraform apply -var deploy_serving=false
            -> bucket, canais em S3, training job criado
gate        scripts/wait_training.py
            -> espera status terminal via DescribeTrainingJob
            -> lê ModelArtifacts.S3ModelArtifacts (URI autoritativa)
            -> prova com HeadObject que o objeto existe e não está vazio
            -> grava terraform/artifact.auto.tfvars.json
stage 2/2   terraform apply
            -> model, endpoint configuration, endpoint (espera InService)
```

Detalhes que fazem isso funcionar:

- os recursos dependentes de artefato usam `count = var.deploy_serving ? 1 : 0`, e o
  `aws_sagemaker_model` tem um `lifecycle { precondition }` exigindo URI não vazia — errar o
  estágio dá erro de plano, não recurso quebrado;
- o handoff é persistido em `artifact.auto.tfvars.json` (carregado automaticamente) e **não**
  passado como `-var`. Assim um `terraform plan` ou `destroy` posterior vê o mesmo estágio
  que o estado representa; com `-var`, o próximo `plan` proporia destruir o serving;
- o arquivo de handoff é gitignored: é estado de execução, não código;
- `aws_sagemaker_endpoint` **espera** `InService` no create (ao contrário do training job),
  então não é preciso waiter extra no estágio 2;
- o aluno nunca copia e cola ID nenhum. A spec (§9.5) autoriza explicitamente o padrão de
  dois estágios desde que automatizado atrás de `make apply`.

## Consequências

**Positivas.** A URI vem da API que a produziu, e sua existência é provada antes do deploy.
A falha de treino aparece no gate com o `FailureReason` da AWS e o ponteiro do CloudWatch,
em vez de virar um erro obscuro de download no endpoint. O `terraform destroy` continua
sendo o único caminho de limpeza.

**Negativas.** Existem dois applies onde o aluno vê um comando — assimetria que precisa ser
explicada, não escondida. E o estado do Terraform carrega uma variável (`deploy_serving`)
que representa progresso de execução, não desejo de topologia; é dívida conceitual assumida
consciente.

**A lição que fica:** *job* é uma abstração temporal e IaC declarativa descreve estado
desejado. Onde as duas se encontram, a ferramenta range — e reconhecer isso é conteúdo de
arquitetura, não desculpa de implementação.

## Como reverificar em outra versão do provider

```bash
terraform providers schema -json \
  | python3 -c "import json,sys; s=json.load(sys.stdin); \
      r=s['provider_schemas']['registry.terraform.io/hashicorp/aws']['resource_schemas']['aws_sagemaker_training_job']; \
      print(sorted(k for k,v in r['block']['attributes'].items() if v.get('computed')))"
```

Se em alguma versão futura aparecer um atributo com a URI do artefato **e** o create passar
a esperar o status terminal, o estágio 2 pode ser fundido no primeiro apply e este ADR deve
ser substituído — não editado no lugar.

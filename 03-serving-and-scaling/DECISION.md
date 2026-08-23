# Architecture Decision — Serving do churn da Bora Fibra

## Stakeholder

Helena Marques, Diretora de Receita.

## Pergunta

Qual padrão de inferência atende cada workload sem pagar complexidade ou capacidade que não precisamos?

## Evidências da nossa execução

| Workload | Padrão | Evidência observada | Custo/ociosidade | Limitação |
|---|---|---|---|---|
| Atendimento humano | Real-Time | _preencher com `artifacts/evidence/compare.json` (latência p50/p95)_ | | |
| App após fechamento da fatura | Serverless | _preencher com `artifacts/evidence/compare.json` (first vs warm)_ | | |
| Importação de arquivo pesado | Asynchronous | _preencher com `artifacts/evidence/async.json`_ | | |
| Campanha noturna | Batch Transform | _preencher com `artifacts/evidence/batch.json`_ | | |

## Recomendação

### Atendimento

...

### App com rajadas

...

### Arquivo assíncrono

...

### Campanha noturna

...

## Custo do erro

O que acontece se escolhermos o padrão errado para cada workload? (pense em latência quebrada, fatura inflada, ou fila que nunca esvazia)

## Condições que fariam a decisão mudar

...

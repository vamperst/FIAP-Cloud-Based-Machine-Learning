# ADR 0002 — dataset sintético determinístico

- **Status:** aceito
- **Data:** 2026-08-17

## Contexto

O Lab 1 ensina as fronteiras de um sistema de Machine Learning: contrato de dados, treino
finito, artefato, serving, avaliação. Precisa de um dataset tabular de classificação
binária que sirva a esse objetivo dentro de um AWS Academy Learner Lab, com orçamento e
sessão limitados, em `us-east-1`, sem cliques em console.

## Alternativas consideradas

**A. Dataset público baixado em tempo de execução** (Telco Churn, UCI e afins).
Rejeitada: adiciona dependência de rede e de disponibilidade de terceiro no caminho crítico
de uma aula com sessão cronometrada; URLs de dataset didático apodrecem; licença e
redistribuição viram assunto onde deveria haver arquitetura. Pior: um lab que falha na
primeira célula porque um host caiu perde a aula inteira.

**B. Dataset público versionado no repositório.**
Melhor que A, mas engorda o repo, ainda carrega questão de licença e não elimina o problema
real — dados de mundo real trazem limpeza, encoding de categóricos e imputação, que são
conteúdo de **outra** aula. Aqui isso é ruído: o aluno gastaria o tempo com `pandas` em vez
de com as fronteiras do sistema.

**C. Dados aleatórios sem estrutura.**
Rejeitada: sem sinal, o modelo não bate o baseline, e o portão "melhor que a classe
majoritária" nunca fecharia. Um lab que ensina "treinar não serve para nada" é pior que
nenhum lab.

**D. Dados sintéticos determinísticos com sinal calibrado.** Escolhida.

## Decisão

Gerar 4000 linhas localmente a partir de um processo gerador logístico explícito, com
semente fixa `20260817`, e tratar o gerador como parte do material didático — não como
detalhe de implementação.

Sete features numéricas com significado de negócio legível (tempo de casa, mensalidade,
chamados ao suporte, atraso de pagamento, índice de uso, contrato anual, plano premium),
coeficientes fixos em `src/lab1/dataset.py`, rótulo amostrado de uma Bernoulli sobre a
probabilidade resultante.

Três propriedades são exigidas por construção e verificadas por teste:

1. **determinismo byte a byte** — a mesma semente produz os mesmos seis arquivos; conferido
   gerando em dois diretórios e comparando com `cmp`. O manifesto é livre de timestamp
   justamente para não quebrar essa verificação;
2. **ruído irredutível** — como o rótulo é amostrado, e não uma função degrau da
   probabilidade, não existe acurácia 100%. Um lab onde o modelo acerta tudo ensina a lição
   errada sobre avaliação;
3. **sinal suficiente, não excessivo** — calibrado para um XGBoost razoável ficar
   confortavelmente acima do baseline majoritário sem chegar perto do perfeito.

Medido com um modelo local de referência sobre o split de teste, antes de qualquer chamada
à AWS: prevalência 0.3375, baseline majoritário 0.6633 de acurácia, e o modelo em
ROC-AUC 0.8109 / F1@0.5 0.5831 / acurácia 0.745. Todos os portões de `config/lab.yaml`
(`roc_auc >= 0.75`, `f1 >= 0.50`, acurácia acima do baseline) fecham com margem — o DGP não
precisou de ajuste depois de escrito.

Sem valores faltantes e sem categóricos de alta cardinalidade: **não** porque dados reais
sejam assim, mas porque imputação e encoding são o assunto de outra aula e aqui competiriam
pelo tempo com as fronteiras do sistema.

## Consequências

**Positivas.** Zero dependência de rede para obter dados. Reprodutível em qualquer máquina
e em qualquer semestre. A prevalência é conhecida, o que torna o baseline majoritário um
número honesto e explicável. Cada verificação de contrato pode ser quebrada de propósito em
`tests/test_failure_paths.py`, porque o gerador está sob nosso controle.

**Negativas.** Menos realismo de domínio: o aluno não enfrenta dado sujo, e o modelo não
tem a "cara" de um problema real. É trade-off explícito, registrado também na tabela de
trade-offs de `docs/architecture.md` — e deve ser dito em voz alta em aula, não escondido.

**Mitigação.** As features têm semântica de negócio plausível e os coeficientes têm sinal
defensável (mais chamados ao suporte e mais atraso de pagamento aumentam o risco; contrato
anual e uso alto reduzem), de modo que a discussão sobre *o que o modelo aprendeu* continua
possível. E o gerador é código legível: dá para mostrar em aula exatamente qual é a verdade
que o modelo está tentando recuperar — algo que nenhum dataset real permite.

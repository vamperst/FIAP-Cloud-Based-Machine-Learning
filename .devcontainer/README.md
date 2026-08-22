# .devcontainer — o ambiente único da disciplina

Esta pasta define o ambiente de desenvolvimento usado em **todos os laboratórios e no trabalho final** da disciplina **Cloud-Based Machine Learning**. O aluno cria esse ambiente **uma única vez**, na primeira aula, e reusa em todas as outras.

> [!TIP]
> Se você é aluno e só quer começar, vá para o [01 - Setup e configuração de ambiente](../01-create-codespaces/README.md). Este README é para quem quer entender **como** o ambiente é construído.

---

## A regra da disciplina: um Codespaces, uma conta AWS

| Item | Quantidade | Quando é criado |
|------|-----------|-----------------|
| Codespaces | **1**, reusado em todas as aulas | Aula 1, junto com a conta AWS |
| Conta AWS (Academy Learner Lab) | **1**, reusada em todas as aulas | Aula 1 |
| Instalação específica de cada lab | 1 script por lab | Dentro do mesmo Codespaces, no início do lab |

O motivo é tempo de aula. Criar e destruir um Codespaces por laboratório custa de 10 a 15 minutos por aula, multiplicados por toda a turma. Reusar o mesmo ambiente derruba isso para segundos — reabrir um Codespaces existente é quase instantâneo.

Consequência prática para quem escreve laboratório novo: **nenhum lab tem seu próprio `.devcontainer/`**. O que é geral vive aqui; o que é específico vira um script Ubuntu executado dentro do Codespaces já existente, no padrão `NN-nome-do-lab/scripts/setup.sh`.

---

## Arquivos desta pasta

| Arquivo | Função |
|---------|--------|
| [`devcontainer.json`](devcontainer.json) | Manifesto. Imagem base, ferramentas (features), extensões do VS Code, região AWS padrão e o comando pós-criação. |
| [`script.sh`](script.sh) | Executado uma vez, ao criar o container. Instala `make`, `unzip` e `jq`, prepara `~/.aws/config` e valida que tudo ficou no PATH. |
| [`config`](config) | Config padrão da AWS CLI (`us-east-1`, output `json`). Copiado para `~/.aws/config` pelo `script.sh`. |

---

## O que vem instalado

| Ferramenta | Versão | Por que está no básico |
|-----------|--------|------------------------|
| Ubuntu | 24.04 LTS | Base recente e estável, igual para toda a turma. |
| Python | 3.12 | Linguagem de todos os scripts de dados, treino e avaliação. |
| AWS CLI | mais recente | Interação com S3, SageMaker, STS e IAM nos labs. |
| Terraform | **1.15.8 exata** | Os labs fixam `required_version`; versão diferente falha no `init`. |
| Node LTS | LTS | Ferramentas de CLI de labs futuros. |
| Git | mais recente | Sincronizar o fork no início de cada aula. |
| Docker-in-Docker | 2 | Empacotar container de inferência em labs de serving. |
| `make`, `unzip`, `jq` | apt | `make` é a interface do aluno nos labs; `jq` inspeciona saída JSON da AWS. |

<details>
<summary><b>💡 Por que o Terraform é fixado em versão exata e as outras ferramentas não</b></summary>
<blockquote>

O Terraform grava a versão que criou o state e recusa abrir um state escrito por versão mais nova. Além disso, os labs declaram `required_version = "= 1.15.8"`. Se cada aluno resolvesse uma versão diferente, o `terraform init` falharia de formas distintas em cada máquina, e a aula viraria uma sessão de depuração de Terraform.

AWS CLI, Node e Git não têm esse acoplamento: eles leem e escrevem formatos estáveis, então a versão mais recente é a escolha melhor (correções de segurança de graça).

</blockquote>
</details>

---

## Anatomia do `devcontainer.json`

### Imagem base

```json
"name": "FIAP Cloud-Based ML",
"image": "mcr.microsoft.com/devcontainers/base:ubuntu-24.04"
```

O `name` é o rótulo que aparece no campo `Dev container configuration` da tela de criação do Codespaces — o aluno seleciona `FIAP Cloud-Based ML`. A imagem é a oficial da Microsoft para Dev Containers, com Ubuntu 24.04 enxuto.

### Features — ferramentas injetadas na imagem

```json
"features": {
  "ghcr.io/devcontainers/features/python:1": { "version": "3.12" },
  "ghcr.io/devcontainers/features/git:1": {},
  "ghcr.io/devcontainers/features/aws-cli:1": {},
  "ghcr.io/devcontainers/features/terraform:1": { "version": "1.15.8", "tflint": "none", "terragrunt": "none" },
  "ghcr.io/devcontainers/features/node:1": { "version": "lts" },
  "ghcr.io/devcontainers/features/docker-in-docker:2": {}
}
```

**Features** são pacotes reutilizáveis do registry `ghcr.io/devcontainers`: cada um instala uma ferramenta já configurada, sem precisar escrever Dockerfile. O sufixo `:1` é versionamento por major da feature — você recebe correções sem quebra de compatibilidade.

### Região AWS por padrão

```json
"remoteEnv": {
  "AWS_DEFAULT_REGION": "us-east-1",
  "AWS_REGION": "us-east-1"
}
```

O AWS Academy Learner Lab só permite recursos em `us-east-1`. Definir a região no ambiente evita a classe de erro mais comum da disciplina: criar recurso em uma região e procurá-lo em outra.

### Comando pós-criação

```json
"postCreateCommand": "bash ${containerWorkspaceFolder}/.devcontainer/script.sh"
```

`${containerWorkspaceFolder}` é resolvido pelo Codespaces para a pasta do repositório dentro do container. Usar a variável em vez do caminho literal mantém o setup funcionando em qualquer fork, inclusive se o aluno renomear o repositório.

---

## Como um laboratório usa este ambiente

```
Aula 1 ─── cria o Codespaces (uma vez) ─── cria a conta AWS Academy (uma vez)
                     │
                     ▼
Aula N ─── abre o MESMO Codespaces ─── cola as credenciais de 4 h
                     │
                     ▼
            cd NN-nome-do-lab
            bash scripts/setup.sh      ← instalação específica do lab
            make doctor                ← confere ambiente e credenciais
                     │
                     ▼
            passos do laboratório
```

Cada `scripts/setup.sh` de lab é idempotente: instala só o que falta e pode ser rodado de novo sem efeito colateral. É também a rede de segurança de quem criou o Codespaces em uma aula anterior — se o ambiente base estiver desatualizado, o script do lab completa o que falta.

---

## Como atualizar o ambiente

1. Edite o [`devcontainer.json`](devcontainer.json) (nova feature ou extensão) ou o [`script.sh`](script.sh) (nova lógica de inicialização).
2. Commit e push.
3. Avise a turma.

> [!WARNING]
> Mudanças aqui **não** chegam a Codespaces já criados. O aluno precisa de `Cmd/Ctrl+Shift+P` → `Codespaces: Rebuild Container`, ou criar um ambiente novo. Por isso o que muda com frequência deve viver no `scripts/setup.sh` do laboratório, não aqui — o script roda a cada aula, o devcontainer só no build.

---

## Rodando localmente (opcional)

Quem preferir Docker local em vez do Codespaces:

1. Instale [Docker Desktop](https://www.docker.com/products/docker-desktop/) e a extensão [Dev Containers](https://marketplace.visualstudio.com/items?itemName=ms-vscode-remote.remote-containers) do VS Code.
2. Clone o fork.
3. `F1` → `Dev Containers: Reopen in Container`.

O mesmo `devcontainer.json` é consumido, então o ambiente é idêntico ao da nuvem.

---

## Referências

- [Dev Containers Specification](https://containers.dev/)
- [Catálogo de Features](https://containers.dev/features)
- [devcontainer.json reference](https://containers.dev/implementors/json_reference/)
- [GitHub Codespaces Docs](https://docs.github.com/en/codespaces)
- [Setup da aula 1](../01-create-codespaces/README.md)

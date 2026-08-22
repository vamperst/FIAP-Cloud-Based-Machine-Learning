#!/usr/bin/env bash
# ----------------------------------------------------------------------
# Setup do Codespaces da disciplina FIAP — Cloud-Based Machine Learning.
#
# Roda como postCreateCommand do devcontainer.json. É o ambiente base de
# TODOS os laboratórios e do trabalho final: o aluno cria o Codespaces uma
# vez, na aula 1, e reusa em todas as aulas.
#
# Tudo aqui precisa ser idempotente — o aluno pode rebuildar o Codespaces a
# qualquer momento, e o script roda de novo do zero.
#
# Instalação específica de um laboratório NÃO entra aqui: cada lab tem seu
# próprio `scripts/setup.sh`, executado dentro deste mesmo Codespaces.
# ----------------------------------------------------------------------
set -euo pipefail

log() { echo "==> $*" >&2; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log "atualizando índice de pacotes"
sudo apt-get update -y

# make: os labs expõem a interface do aluno via Makefile.
# unzip: descompacta binários fixados por versão (ex.: Terraform em labs antigos).
# jq: inspeção de JSON de saída da AWS CLI nos passos de evidência.
log "instalando make, unzip e jq"
sudo apt-get install -y --no-install-recommends make unzip jq

# Região e formato padrão da AWS CLI. Credenciais NÃO entram aqui: são
# individuais, temporárias (4 h) e o aluno cola a cada aula.
log "preparando ~/.aws/config"
mkdir -p ~/.aws
cp "${REPO_ROOT}/.devcontainer/config" ~/.aws/config

# Validação explícita: se uma ferramenta faltar, o build para AQUI, com o erro
# visível no log de criação, em vez de dar "command not found" no meio da aula.
for tool in python3 pip3 aws terraform git make jq unzip node docker; do
  command -v "${tool}" > /dev/null 2>&1 || {
    echo "ERRO: ${tool} não ficou disponível no PATH." >&2
    echo "      Rebuilde o Codespaces (Cmd/Ctrl+Shift+P -> Codespaces: Rebuild Container)." >&2
    exit 1
  }
done

log "python    : $(python3 --version)"
log "aws cli   : $(aws --version 2>&1)"
log "terraform : $(terraform version | head -1)"
log "node      : $(node --version)"
log "ambiente base pronto. Próximo passo: 01-create-codespaces/README.md"

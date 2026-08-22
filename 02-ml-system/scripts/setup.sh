#!/usr/bin/env bash
# ============================================================================
# setup.sh — instalação específica do Lab 02 dentro do Codespaces da disciplina
# ============================================================================
# O ambiente base (Ubuntu, Python 3.12, AWS CLI, Terraform, make) vem do
# Codespaces criado na aula 1 (`.devcontainer/` na raiz do repositório). Este
# script instala apenas o que é exclusivo deste laboratório:
#
#   1. as bibliotecas Python nas versões exatas de requirements.txt, em .venv
#   2. o Terraform 1.15.8, caso o Codespaces do aluno seja anterior à versão
#      fixada no devcontainer (acontece com quem criou o ambiente em aulas
#      passadas e não rebuildou)
#
# Idempotente: rodar duas vezes não quebra nada e não reinstala o que já está
# na versão certa.
#
# Uso, a partir da pasta do laboratório:
#   bash scripts/setup.sh
# ============================================================================
set -euo pipefail

TERRAFORM_VERSION="1.15.8"

# Checksums oficiais de
# https://releases.hashicorp.com/terraform/1.15.8/terraform_1.15.8_SHA256SUMS.
# Ficam versionados aqui (e não baixados no ato) para que uma troca silenciosa
# do artefato remoto quebre a instalação em vez de passar despercebida.
declare -A TERRAFORM_SHA256=(
  [amd64]="d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d"
  [arm64]="8891e9dcedc9e3b8950bc6af9d4d8af1f4cfade3062f53b9dc403a89f6ce8c9c"
)

LAB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

log() { echo "==> $*" >&2; }

install_terraform() {
  local arch zip_name url tmp

  # A saída de `terraform version` é estável entre versões; o JSON vem
  # indentado, então comparar a linha do texto é mais confiável que casar chave.
  if command -v terraform > /dev/null 2>&1 &&
    [ "$(terraform version | head -1)" = "Terraform v${TERRAFORM_VERSION}" ]; then
    log "terraform ${TERRAFORM_VERSION} já disponível"
    return 0
  fi

  case "$(uname -m)" in
    x86_64) arch="amd64" ;;
    aarch64 | arm64) arch="arm64" ;;
    *)
      echo "arquitetura não suportada: $(uname -m)" >&2
      return 1
      ;;
  esac

  zip_name="terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"
  url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${zip_name}"
  tmp="$(mktemp -d)"

  log "instalando terraform ${TERRAFORM_VERSION} (${arch})"
  curl -fsSL "${url}" -o "${tmp}/${zip_name}"
  echo "${TERRAFORM_SHA256[$arch]}  ${tmp}/${zip_name}" | sha256sum --check --status
  log "checksum conferido"

  command -v unzip > /dev/null 2>&1 || sudo apt-get install -y --no-install-recommends unzip
  unzip -q -o "${tmp}/${zip_name}" -d "${tmp}"
  sudo install -m 0755 "${tmp}/terraform" /usr/local/bin/terraform
  rm -rf "${tmp}"
}

install_python_deps() {
  log "criando .venv com as versões de requirements.txt"
  python3 -m venv "${LAB_DIR}/.venv"
  "${LAB_DIR}/.venv/bin/python" -m pip install --quiet --upgrade pip
  "${LAB_DIR}/.venv/bin/python" -m pip install --quiet -r "${LAB_DIR}/requirements.txt"
}

install_terraform
install_python_deps

log "terraform : $(terraform version | head -1)"
log "python    : $("${LAB_DIR}/.venv/bin/python" --version)"
log "aws cli   : $(aws --version 2>&1)"
log "pronto. Próximo passo: make doctor"

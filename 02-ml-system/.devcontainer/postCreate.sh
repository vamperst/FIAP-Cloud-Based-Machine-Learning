#!/usr/bin/env bash
# Provisiona o toolchain do Lab 1 de forma determinística: a mesma versão de
# Terraform e as mesmas versões de biblioteca Python em qualquer Codespace.
set -euo pipefail

TERRAFORM_VERSION="1.15.8"

# Checksums oficiais de https://releases.hashicorp.com/terraform/1.15.8/terraform_1.15.8_SHA256SUMS.
# Ficam versionados aqui (e não baixados no ato) para que uma troca silenciosa do
# artefato remoto quebre o build em vez de passar despercebida.
declare -A TERRAFORM_SHA256=(
  [amd64]="d25ce7b6902013ad905db3d2eab0be4cd905887fe88b81a6171b8d5503c31f3d"
  [arm64]="8891e9dcedc9e3b8950bc6af9d4d8af1f4cfade3062f53b9dc403a89f6ce8c9c"
)

log() { echo "==> $*" >&2; }

install_terraform() {
  local arch zip_name url tmp
  case "$(uname -m)" in
    x86_64) arch="amd64" ;;
    aarch64 | arm64) arch="arm64" ;;
    *)
      echo "arquitetura não suportada: $(uname -m)" >&2
      return 1
      ;;
  esac

  if command -v terraform > /dev/null 2>&1 &&
    terraform version -json | grep -q "\"terraform_version\":\"${TERRAFORM_VERSION}\""; then
    log "terraform ${TERRAFORM_VERSION} já instalado"
    return 0
  fi

  zip_name="terraform_${TERRAFORM_VERSION}_linux_${arch}.zip"
  url="https://releases.hashicorp.com/terraform/${TERRAFORM_VERSION}/${zip_name}"
  tmp="$(mktemp -d)"

  log "baixando ${zip_name}"
  curl -fsSL "${url}" -o "${tmp}/${zip_name}"
  echo "${TERRAFORM_SHA256[$arch]}  ${tmp}/${zip_name}" | sha256sum --check --status
  log "checksum conferido"

  unzip -q -o "${tmp}/${zip_name}" -d "${tmp}"
  sudo install -m 0755 "${tmp}/terraform" /usr/local/bin/terraform
  rm -rf "${tmp}"
}

install_python_deps() {
  log "criando .venv com as versões de requirements.txt"
  python3 -m venv .venv
  .venv/bin/python -m pip install --quiet --upgrade pip
  .venv/bin/python -m pip install --quiet -r requirements.txt
}

install_terraform
install_python_deps

log "terraform : $(terraform version | head -1)"
log "python    : $(.venv/bin/python --version)"
if command -v aws > /dev/null 2>&1; then
  log "aws cli   : $(aws --version 2>&1)"
else
  # Fora de um devcontainer real a feature aws-cli não roda; o lab usa boto3, então
  # isso não bloqueia nada além do fluxo manual de credenciais do Academy.
  log "aws cli   : ausente (instalado pela feature aws-cli no devcontainer)"
fi
log "pronto. próximo passo: make doctor"

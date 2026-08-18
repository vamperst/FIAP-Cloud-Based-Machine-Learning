# Lab 1 - From Model to Machine Learning System
#
# Every target is idempotent and safe to run twice. The lifecycle order is
# doctor -> data -> validate -> apply -> predict -> evaluate -> evidence ->
# destroy -> verify-clean, and `make e2e` runs exactly that with a cleanup trap.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

# The venv is preferred over whatever `python3` PATH happens to resolve to: a
# login shell re-sources /etc/profile and drops the .venv/bin that the
# devcontainer prepends, which would run the lab against an interpreter without
# boto3 or pyyaml installed.
PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
TF ?= terraform
TF_DIR := terraform
SCRIPTS := scripts
ARTIFACTS ?= artifacts

# Scripts import lab1 from src/; exporting it here means `make` works with a
# plain interpreter, no install step.
export PYTHONPATH := src

# Written by scripts/wait_training.py; it carries the proven artifact URI and
# flips the serving stage on.
HANDOFF := $(TF_DIR)/artifact.auto.tfvars.json

.PHONY: help doctor data fmt validate plan apply predict evaluate \
        evidence destroy verify-clean e2e clean

help: ## Show available targets
	@echo "Lab 1 - From Model to Machine Learning System"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Full lifecycle:  make e2e"
	@echo "  Keep resources:  make e2e KEEP_RESOURCES=1   (you must run make destroy later)"

doctor: ## Check tool versions and AWS credentials/region/role
	@echo "== tool versions =="
	@$(TF) version
	@$(PYTHON) --version
	@$(PYTHON) -c "import boto3, botocore, numpy, sklearn; \
		print(f'boto3 {boto3.__version__} botocore {botocore.__version__} numpy {numpy.__version__} scikit-learn {sklearn.__version__}')"
	@echo "== aws preflight =="
	@$(PYTHON) $(SCRIPTS)/check_aws.py > /dev/null

data: ## Generate the deterministic dataset
	@$(PYTHON) $(SCRIPTS)/generate_dataset.py --clean > /dev/null

fmt: ## Format Terraform (check in CI, rewrite locally)
	@$(TF) fmt -recursive $(TF_DIR)

validate: ## terraform init + validate
	@$(TF) -chdir=$(TF_DIR) init -input=false -upgrade=false
	@$(TF) -chdir=$(TF_DIR) fmt -check -recursive
	@$(TF) -chdir=$(TF_DIR) validate

plan: validate ## Plan the current stage
	@$(TF) -chdir=$(TF_DIR) plan -input=false

apply: data validate ## Provision storage + training, then serving (single command, two stages)
	@echo "== stage 1/2: storage and training job =="
	@rm -f $(HANDOFF)
	@$(TF) -chdir=$(TF_DIR) apply -input=false -auto-approve -var deploy_serving=false
	@echo "== gate: wait for the training job and prove the artifact exists =="
	@$(PYTHON) $(SCRIPTS)/wait_training.py > /dev/null
	@echo "== stage 2/2: model, endpoint configuration and endpoint =="
	@$(TF) -chdir=$(TF_DIR) apply -input=false -auto-approve
	@$(TF) -chdir=$(TF_DIR) output

predict: ## Deterministic smoke inference
	@$(PYTHON) $(SCRIPTS)/predict.py > /dev/null

evaluate: ## Score the held-out test set through the endpoint
	@$(PYTHON) $(SCRIPTS)/evaluate_endpoint.py > /dev/null

evidence: ## Build the evidence package
	@$(PYTHON) $(SCRIPTS)/evidence.py > /dev/null

destroy: ## Destroy every managed resource
	@$(TF) -chdir=$(TF_DIR) destroy -input=false -auto-approve
	@rm -f $(HANDOFF)

verify-clean: ## Prove no billable serving resource remains
	@$(PYTHON) $(SCRIPTS)/verify_clean.py > /dev/null

e2e: ## Full lifecycle with failure-safe cleanup (KEEP_RESOURCES=1 to skip destroy)
	@set -euo pipefail; \
	if [ "$${KEEP_RESOURCES:-0}" = "1" ]; then \
		echo "!! KEEP_RESOURCES=1: the endpoint will stay up and keep billing."; \
		echo "!! Run 'make destroy' as soon as you are done, or the lab budget pays for it."; \
	else \
		trap 'code=$$?; echo "== cleanup (always runs) =="; $(MAKE) --no-print-directory destroy || true; \
			$(MAKE) --no-print-directory verify-clean || true; exit $$code' EXIT; \
	fi; \
	$(MAKE) --no-print-directory doctor; \
	$(MAKE) --no-print-directory apply; \
	$(MAKE) --no-print-directory predict; \
	$(MAKE) --no-print-directory evaluate; \
	$(MAKE) --no-print-directory evidence

clean: ## Remove generated local artifacts (never touches AWS)
	@rm -rf $(ARTIFACTS)
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +

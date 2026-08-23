# Lab 03 - Serving and Scaling
#
# One model, four ways to consume it. Lifecycle order: setup -> doctor -> data
# -> validate-data -> apply -> status/compare/async/batch/load/scale-demo ->
# evidence -> destroy -> verify-clean. `make e2e` runs exactly that with a
# cleanup trap.

SHELL := /bin/bash
.SHELLFLAGS := -eu -o pipefail -c
.DEFAULT_GOAL := help

PYTHON ?= $(shell if [ -x .venv/bin/python ]; then echo .venv/bin/python; else echo python3; fi)
TF ?= terraform
TF_DIR := terraform
SCRIPTS := scripts
ARTIFACTS ?= artifacts

export PYTHONPATH := src

HANDOFF := $(TF_DIR)/artifact.auto.tfvars.json

.PHONY: help setup doctor data validate-data fmt validate plan apply status \
        compare async batch load scale-demo evidence destroy verify-clean \
        e2e clean

help: ## Show available targets
	@echo "Lab 03 - Serving and Scaling"
	@echo
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[1m%-14s\033[0m %s\n", $$1, $$2}'
	@echo
	@echo "  Full lifecycle:  make e2e"
	@echo "  Keep resources:  make e2e KEEP_RESOURCES=1   (you must run make destroy later)"

setup: ## Create/update the lab .venv with pinned dependencies
	@bash $(SCRIPTS)/setup.sh

doctor: setup ## Check tool versions and AWS credentials/region/role
	@$(PYTHON) $(SCRIPTS)/lab.py doctor > /dev/null

data: setup ## Generate the deterministic dataset
	@$(PYTHON) $(SCRIPTS)/lab.py data > /dev/null

validate-data: data ## Run the executable data contract and print exact hashes
	@$(PYTHON) $(SCRIPTS)/lab.py validate-data

fmt: ## Format Terraform (check in CI, rewrite locally)
	@$(TF) fmt -recursive $(TF_DIR)

validate: ## terraform init + validate
	@$(TF) -chdir=$(TF_DIR) init -input=false -upgrade=false
	@$(TF) -chdir=$(TF_DIR) fmt -check -recursive
	@$(TF) -chdir=$(TF_DIR) validate

plan: validate-data validate ## Plan the current stage
	@$(TF) -chdir=$(TF_DIR) plan -input=false

apply: validate-data validate ## Provision storage + training bootstrap, gate, then 3 endpoints + autoscaling
	@echo "== stage 1/2: storage and training bootstrap =="
	@rm -f $(HANDOFF)
	@$(TF) -chdir=$(TF_DIR) apply -input=false -auto-approve -var deploy_serving=false
	@echo "== gate: wait for the training job and prove the artifact exists =="
	@$(PYTHON) $(SCRIPTS)/lab.py wait-training > /dev/null
	@echo "== stage 2/2: model, 3 endpoint configs/endpoints, autoscaling =="
	@$(TF) -chdir=$(TF_DIR) apply -input=false -auto-approve
	@$(TF) -chdir=$(TF_DIR) output

status: ## Describe endpoints, configs and scalable targets as JSON
	@$(PYTHON) $(SCRIPTS)/lab.py status

compare: ## Smoke + first/warm latency, real-time vs serverless
	@$(PYTHON) $(SCRIPTS)/lab.py compare

async: ## Upload payload to S3, InvokeEndpointAsync, wait for and validate output
	@$(PYTHON) $(SCRIPTS)/lab.py async

batch: ## CreateTransformJob for the 600-row test set, wait, validate 600 outputs
	@$(PYTHON) $(SCRIPTS)/lab.py batch

load: ## Load test the real-time endpoint at concurrency 1/4/8
	@$(PYTHON) $(SCRIPTS)/lab.py load

scale-demo: ## Prove 1->2->1 instances via Application Auto Scaling, restore config
	@$(PYTHON) $(SCRIPTS)/lab.py scale-demo

evidence: ## Consolidate checkable results into artifacts/evidence/
	@$(PYTHON) $(SCRIPTS)/lab.py evidence > /dev/null

destroy: ## Destroy every managed resource
	@$(TF) -chdir=$(TF_DIR) destroy -input=false -auto-approve
	@rm -f $(HANDOFF)

verify-clean: ## Prove by direct API query that nothing billable of this lab's prefix remains
	@$(PYTHON) $(SCRIPTS)/lab.py verify-clean

e2e: ## Full lifecycle with failure-safe cleanup (KEEP_RESOURCES=1 to skip destroy)
	@set -euo pipefail; \
	if [ "$${KEEP_RESOURCES:-0}" = "1" ]; then \
		echo "!! KEEP_RESOURCES=1: real-time and async endpoints will stay up and keep billing."; \
		echo "!! Run 'make destroy' as soon as you are done, or the lab budget pays for it."; \
	else \
		trap 'code=$$?; echo "== cleanup (always runs) =="; $(MAKE) --no-print-directory destroy || true; \
			$(MAKE) --no-print-directory verify-clean || true; exit $$code' EXIT; \
	fi; \
	$(MAKE) --no-print-directory doctor; \
	$(MAKE) --no-print-directory apply; \
	$(MAKE) --no-print-directory status; \
	$(MAKE) --no-print-directory compare; \
	$(MAKE) --no-print-directory async; \
	$(MAKE) --no-print-directory batch; \
	$(MAKE) --no-print-directory load; \
	$(MAKE) --no-print-directory scale-demo; \
	$(MAKE) --no-print-directory evidence

clean: ## Remove generated local artifacts (never touches AWS)
	@rm -rf $(ARTIFACTS)
	@find . -name __pycache__ -type d -prune -exec rm -rf {} +

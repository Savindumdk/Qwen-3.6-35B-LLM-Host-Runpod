# Convenience shortcuts. Works with GNU make (Linux/macOS/WSL/git-bash).
# On plain Windows PowerShell, run the underlying `docker compose` commands shown.

ENGINE ?= llamacpp        # llamacpp (default) | vllm

.PHONY: help
help:
	@echo "Targets:"
	@echo "  make up            # start gateway + engine (ENGINE=$(ENGINE))"
	@echo "  make up ENGINE=vllm# start with the vLLM engine instead"
	@echo "  make down          # stop the stack"
	@echo "  make logs          # tail all logs"
	@echo "  make ps            # container status"
	@echo "  make build         # rebuild images"
	@echo "  make test          # run gateway unit tests"
	@echo "  make gen-key       # print a fresh API key"
	@echo "  make runpod-build  # build+push the RunPod image (REGISTRY=.. TAG=..)"

.PHONY: up
up:
	docker compose --profile $(ENGINE) up -d --build

.PHONY: down
down:
	docker compose --profile llamacpp --profile vllm down

.PHONY: logs
logs:
	docker compose logs -f --tail=200

.PHONY: ps
ps:
	docker compose ps

.PHONY: build
build:
	docker compose --profile $(ENGINE) build

.PHONY: test
test:
	cd gateway && pytest -q

.PHONY: gen-key
gen-key:
	@printf "sk-"; openssl rand -hex 24

.PHONY: runpod-build
runpod-build:
	./runpod/build-and-push.sh

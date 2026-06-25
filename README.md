# Qwen3.6-35B-A3B — Self-Hosted OpenAI-Compatible LLM Platform

A production-grade, self-hosted serving stack for **Zoo Code** (and any
OpenAI-compatible client), built around a hardened **FastAPI gateway** in front
of a GPU inference **engine** running **Qwen3.6-35B-A3B**.

```
        VS Code
           │
     Zoo Code (agent)                MCP servers (your PC)
           │                     ┌── Playwright · GitHub · Filesystem · PostgreSQL
   OpenAI-compatible HTTPS       │   (connect to Zoo Code, not the gateway)
           │  ◄──────────────────┘
           ▼
 ┌───────────────────────────────────────────────┐
 │  FastAPI Gateway   (this repo, ./gateway)      │
 │  auth · rate limit · usage analytics · logging │
 │  request history · model routing · health      │
 └───────────────────────────────────────────────┘
           │  http://engine:8001/v1   (internal only)
           ▼
 ┌───────────────────────────────────────────────┐
 │  Inference Engine   (./engine)                 │
 │  • llama.cpp  ← DEFAULT, serves your IQ4_NL GGUF│
 │  • vLLM       ← alternative, serves an AWQ quant│
 │  PagedAttention · continuous batching ·         │
 │  prefix/prompt caching · flash attention        │
 └───────────────────────────────────────────────┘
           │
   GPU (RunPod RTX A6000, 48 GB) — model on a persistent volume
```

The gateway never implements model logic; it is a thin, secure, observable
OpenAI front door. The engine does all the heavy lifting and provides the KV
cache / batching optimizations natively — we configure them, we don't reinvent
them.

---

## ⚠️ Important: which engine serves your model, and why

You downloaded `Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf` (~19.5 GB). That is a
**llama.cpp-native i-quant (IQ4_NL)** of a **Mixture-of-Experts** model.

- **vLLM cannot serve this file.** vLLM recognizes the IQ4_NL *quant*, but it
  rejects the **`qwen3moe` GGUF architecture** with *"architecture qwen3moe is
  not supported yet."* GGUF support in vLLM is also officially "experimental and
  under-optimized." (See [issue #18382](https://github.com/vllm-project/vllm/issues/18382),
  [#36456](https://github.com/vllm-project/vllm/issues/36456).)
- **llama.cpp serves it natively** and is OpenAI-compatible, with built-in
  continuous batching, prompt (prefix) caching, flash attention and GPU offload
  — i.e. the same class of optimizations the brief asks vLLM for.

**Therefore this stack defaults to the llama.cpp engine for your exact file**,
and ships the **vLLM engine as a fully-configured alternative** that serves an
*AWQ* quant of the same model (vLLM's native, high-throughput path). Both sit
behind the identical gateway; switching is one word on the command line. You get
the vLLM option you asked for **and** something that actually runs your GGUF —
the honest, production-correct outcome.

| | **llama.cpp** (default) | **vLLM** (alternative) |
|---|---|---|
| Serves your `IQ4_NL` GGUF | ✅ yes | ❌ no (arch unsupported) |
| Model used | your downloaded GGUF | AWQ quant (`QuantTrio/Qwen3.6-35B-A3B-AWQ`) |
| Best for | exact file, max VRAM efficiency, single/low-concurrency | high concurrency / throughput |
| Tooling | `--jinja` (Qwen tool calls) | `--enable-auto-tool-choice` |

---

## Project structure

```
.
├── docker-compose.yml          # multi-container: gateway + engine (profiles)
├── .env.example                # every config knob, documented
├── Makefile                    # build / up / down / logs / test shortcuts
├── gateway/                    # the FastAPI OpenAI gateway
│   ├── app/
│   │   ├── main.py             # app factory, lifespan, exception handlers
│   │   ├── config.py           # typed env settings (pydantic-settings)
│   │   ├── auth.py             # API-key auth (constant-time, key_id hashing)
│   │   ├── rate_limit.py       # per-key RPM / TPM / concurrency token buckets
│   │   ├── proxy.py            # shared httpx client; SSE pass-through; usage sniff
│   │   ├── relay.py            # core pipeline: route → admit → stream → account
│   │   ├── analytics.py        # precise per-request usage recording
│   │   ├── db.py               # async SQLAlchemy models + aggregations (SQLite/PG)
│   │   ├── middleware.py       # request-id, body limits, access logs
│   │   ├── errors.py           # OpenAI-shaped error envelopes
│   │   ├── logging_config.py   # structured JSON logging
│   │   └── routers/            # /v1/chat, /v1/completions, /v1/embeddings,
│   │       └── ...             #   /v1/models, /health, /admin/*
│   ├── tests/                  # pytest suite (mocked engine; 12 tests)
│   ├── requirements.txt
│   └── Dockerfile
├── engine/
│   ├── scripts/download_model.sh   # idempotent runtime model fetch from HF
│   ├── llamacpp/{Dockerfile,entrypoint.sh}   # DEFAULT engine
│   └── vllm/{Dockerfile,entrypoint.sh}       # ALTERNATIVE engine
├── runpod/                     # single-container all-in-one for RunPod Pods
│   ├── Dockerfile              # llama.cpp + gateway under supervisord
│   ├── supervisord.conf
│   └── build-and-push.sh
└── docs/
    ├── RUNPOD.md               # RunPod A6000 deployment, step by step
    ├── ZOO_CODE.md             # Zoo Code "OpenAI Compatible" setup
    └── MCP.md                  # Playwright/GitHub/Filesystem/Postgres via MCP
```

---

## Quick start

### A) Local / any GPU server (Docker Compose)

```bash
cp .env.example .env
# Edit .env: set GATEWAY_API_KEYS (and ADMIN_API_KEY). Keep ENGINE_API_KEY ==
# UPSTREAM_API_KEY.

# Default engine = llama.cpp (serves your IQ4_NL GGUF; downloads it on first run)
docker compose --profile llamacpp up -d --build

# …or the vLLM engine instead (AWQ quant):
docker compose --profile vllm up -d --build

curl http://localhost:8000/readyz          # {"status":"ready"} once the model loads
```

Point Zoo Code at `http://<host>:8000` → see [docs/ZOO_CODE.md](docs/ZOO_CODE.md).

### B) RunPod (RTX A6000)

Single-container image, model on a persistent volume:
see **[docs/RUNPOD.md](docs/RUNPOD.md)**.

### C) Gateway tests (no GPU needed)

```bash
cd gateway
python -m venv .venv && . .venv/Scripts/activate   # or source .venv/bin/activate
pip install -r requirements.txt pytest
pytest -q                                            # 12 passed
```

---

## API surface (OpenAI-compatible)

| Method & path                 | Auth        | Purpose                                  |
|-------------------------------|-------------|------------------------------------------|
| `GET  /health`, `/healthz`    | none        | Gateway liveness                         |
| `GET  /readyz`                | none        | Readiness (checks the engine is up)      |
| `GET  /v1/models`             | API key     | Model catalogue Zoo Code reads           |
| `POST /v1/chat/completions`   | API key     | Chat — **streaming & non-streaming**     |
| `POST /v1/completions`        | API key     | Legacy text completion                   |
| `POST /v1/embeddings`         | API key     | Optional, for codebase indexing/RAG      |
| `GET  /admin/stats`           | admin key   | Headline counters for a time window      |
| `GET  /admin/usage`           | admin key   | Tokens/requests by key & model           |
| `GET  /admin/requests`        | admin key   | Recent request history                   |
| `GET  /admin/config`          | admin key   | Non-secret runtime config + engine health|

Errors use the OpenAI envelope `{"error": {"message","type","code"}}` so OpenAI
SDKs and Zoo Code handle them natively.

---

## Design decisions (the "why")

**Gateway and engine are separate processes behind one network seam.** The
gateway is CPU-only, tiny and restartable in milliseconds; the engine is a
heavyweight GPU process. Decoupling them means you can iterate on auth/analytics
without touching the model, swap engines (llama.cpp ↔ vLLM) without touching the
gateway, and put *only* the authenticated gateway on the public network while the
engine stays private. This is the whole point of "build the platform in FastAPI
without touching vLLM."

**Engine-agnostic proxy.** The gateway forwards request bodies the engine already
understands and **streams SSE byte-for-byte**. New engine features (tool-call
deltas, `reasoning_content`, logprobs) flow through with zero gateway changes.
The only thing the gateway rewrites is the `model` field (routing).

**Auth = static bearer keys, hashed to a `key_id`.** Right altitude for a
self-hosted, single-tenant tool: no user DB, no OAuth, instant revocation by
editing one env var — yet every log line and analytics row is attributed to a
stable non-reversible `key_id`, so the raw secret never hits disk. Keys are
compared in constant time. The gateway **refuses to start** if `REQUIRE_AUTH` is
on but no key is set, so you can't accidentally expose an open model.

**Rate limiting: per-key token buckets (RPM + TPM) plus a concurrency
semaphore.** Token buckets give smooth limits without fixed-window bursts. TPM is
admitted on a cheap char/4 estimate and **reconciled with the engine's real
`usage`** when the response finishes — accurate accounting without loading a
tokenizer into the gateway. In-process state is correct for a single gateway
container (the recommended topology); the interface is drop-in replaceable with
Redis for a horizontal fleet (and `GATEWAY_WORKERS=1` keeps the in-process state
authoritative).

**Analytics owned by the route handlers, not middleware.** With Starlette
`BaseHTTPMiddleware`, code after `call_next` runs *before* a streamed body
finishes — so usage and true latency aren't known there. Handlers record at the
exact completion point (including the final stream `usage` frame), capturing
`prompt/completion/total` tokens, latency, **time-to-first-token**, status and
errors. Writes are fire-and-forget on a background task and **never** block or
break a response. Storage defaults to a zero-ops SQLite file; flip `DATABASE_URL`
to `postgresql+asyncpg://…` for Postgres with no code change. Prompt/response
text is redacted by default (`ANALYTICS_REDACT_CONTENT=true`).

**Streaming usage capture.** OpenAI streams don't include token usage unless the
client opts in. The gateway injects `stream_options.include_usage` (toggle:
`CAPTURE_STREAM_USAGE`) so analytics and TPM reconciliation work for streamed
calls too — the extra terminal frame is standard and ignored by OpenAI clients.

**SSE through edge proxies.** Streaming responses set `Cache-Control: no-cache`
and `X-Accel-Buffering: no` so nginx / the RunPod-Cloudflare edge don't buffer
tokens. The gateway binds `0.0.0.0` and uses `--proxy-headers` for correct client
IPs behind the proxy.

**Model routing via a public→upstream map.** `/v1/models` advertises *gateway*
ids; the relay rewrites `model` to the engine's served id. Adding a model or an
alias is an env edit (`MODEL_ALIASES`), making "extensible with more models /
embeddings" a config change, not a code change.

**Structured JSON logs with a request-id `ContextVar`.** One trace id threads
through every log line for a request and is returned as `x-request-id`. Logs drop
straight into Loki/Elastic/CloudWatch.

**Containerization.** Gateway image is CPU-only and ~150 MB. Engine images build
on the official upstream images (`llama.cpp:server-cuda`, `vllm/vllm-openai`) so
we inherit GPU-correct builds. Compose wires them with both engines sharing the
`engine` network alias behind profiles. RunPod gets a dedicated single-container
image (supervisord) because Pods don't run Compose. **The model is downloaded at
runtime onto a persistent volume**, never baked into an image — small images,
fast pushes, one-time download.

### vLLM / engine best-practices, and how they're applied

The brief calls for PagedAttention, KV cache, continuous batching, prefix
caching, GPU-memory tuning and context length — *relying on the engine's built-in
optimizations*. Both engines provide these natively; we only configure them:

| Optimization        | llama.cpp (default)                          | vLLM (alternative)                                   |
|---------------------|----------------------------------------------|------------------------------------------------------|
| Paged KV cache      | built-in paged KV                            | **PagedAttention** (core)                            |
| Continuous batching | `--cont-batching`, `-np <slots>`             | continuous batching (default)                        |
| Prefix/prompt cache | built-in prompt cache across requests        | `--enable-prefix-caching`                            |
| Chunked prefill     | n/a (handled internally)                     | on by default (recent vLLM)                          |
| Flash attention     | `--flash-attn on`                            | built-in                                             |
| GPU memory          | `-ngl 999` (all layers on GPU)               | `--gpu-memory-utilization 0.90`                      |
| Context length      | `-c CTX_SIZE` (÷ slots = per-request window) | `--max-model-len`                                    |
| KV cache dtype      | `--cache-type-k/v q8_0` (optional)           | `--kv-cache-dtype fp8` (optional)                    |
| Tool calling        | `--jinja`                                     | `--enable-auto-tool-choice --tool-call-parser …`     |
| Reasoning split     | `--reasoning-format auto`                    | `--reasoning-parser qwen3`                           |

No custom KV-cache logic is written anywhere — by design.

---

## Configuration

Everything is environment-driven and documented inline in **[.env.example](.env.example)**.
The essentials:

| Variable            | What it does                                                |
|---------------------|-------------------------------------------------------------|
| `GATEWAY_API_KEYS`  | Comma-separated client keys (what you paste into Zoo Code). |
| `ADMIN_API_KEY`     | Unlocks `/admin/*`.                                          |
| `UPSTREAM_BASE_URL` | Where the engine lives (`http://engine:8001/v1`).           |
| `DEFAULT_MODEL` / `MODEL_ALIASES` | Public model id(s) and routing.               |
| `RATE_LIMIT_RPM/TPM/CONCURRENCY`  | Per-key limits.                               |
| `CTX_SIZE` / `PARALLEL_SLOTS`     | llama.cpp context & concurrency.              |
| `VLLM_MODEL` / `VLLM_QUANTIZATION`| vLLM model & quant.                           |

---

## Security checklist

- Set strong `GATEWAY_API_KEYS` (`openssl rand -hex 24`); rotate by editing env.
- Only the gateway port is published; the engine stays on the internal network.
- The RunPod proxy URL is effectively public — auth is enforced by the gateway.
- Keep `ANALYTICS_REDACT_CONTENT=true` unless you intentionally need full history.
- Put a real TLS terminator (RunPod proxy already does HTTPS; for self-managed
  VMs, front with Caddy/nginx) — never ship raw HTTP over the internet.

---

## Extending

- **More models**: run another engine, add its id to `MODEL_ALIASES`, done.
- **Embeddings**: serve an embedding model and route `/v1/embeddings` to it.
- **Postgres analytics / Grafana**: point `DATABASE_URL` at Postgres; the engines
  also expose Prometheus `/metrics`.
- **Horizontal scale**: run N gateways behind a load balancer and swap the
  in-process limiter for the Redis-backed one (same interface).

See **[docs/RUNPOD.md](docs/RUNPOD.md)**, **[docs/ZOO_CODE.md](docs/ZOO_CODE.md)**,
**[docs/MCP.md](docs/MCP.md)**.

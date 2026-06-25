# Connecting Zoo Code (OpenAI Compatible mode)

[Zoo Code](https://github.com/Zoo-Code-Org/Zoo-Code) is the VS Code autonomous
coding agent (a community continuation of Roo Code). It talks to any
OpenAI-compatible endpoint — which is exactly what this gateway exposes.

## 1. Install Zoo Code

VS Code → Extensions → search **"Zoo Code"** (publisher *ZooCodeOrganization*,
id `ZooCodeOrganization.zoo-code`) → Install. Click the Zoo Code icon in the
Activity Bar.

## 2. Add the provider

Open Zoo Code **Settings** (gear icon) → **Providers** → create/select a profile,
then set:

| Field            | Value                                                            |
|------------------|------------------------------------------------------------------|
| **API Provider** | `OpenAI Compatible`                                              |
| **Base URL**     | your gateway root **without `/v1`** (Zoo Code appends it)        |
| **API Key**      | one of your `GATEWAY_API_KEYS`                                   |
| **Model**        | `qwen3.6-35b-a3b` (your `DEFAULT_MODEL`)                         |

**Base URL examples**

| Deployment                       | Base URL                                          |
|----------------------------------|---------------------------------------------------|
| RunPod proxy                     | `https://<podId>-8000.proxy.runpod.net`           |
| Docker Compose on a remote VM    | `http://<server-ip>:8000`                         |
| Local (same machine)             | `http://localhost:8000`                           |

> ⚠️ Do **not** include `/v1` in the Base URL — Zoo Code adds it automatically,
> and the gateway serves the standard `/v1/chat/completions`, `/v1/models`, …
> If you accidentally add `/v1`, requests go to `/v1/v1/...` and 404.

## 3. Model Configuration (advanced, recommended)

Expand **Model Configuration** for the profile and set:

| Setting           | Value     | Why                                                           |
|-------------------|-----------|---------------------------------------------------------------|
| Context Window    | `131072`  | Match your engine's effective per-request context (`CTX_SIZE ÷ PARALLEL_SLOTS`; 128K with the defaults). Zoo Code uses this to manage/condense context. Also enable **Automatically condense context** for long sessions. |
| Max Output Tokens | `8192`    | A sane cap for agent turns; raise if you want longer answers. |
| Input Price       | `0`       | Self-hosted — silences cost estimates.                        |
| Output Price      | `0`       | Same.                                                         |
| Image Support     | off       | This model is text-only.                                      |

Set **Temperature** (Zoo Code's general setting) to **0.6** for coding/agentic
work (Qwen's recommended thinking-coding preset).

## 4. Verify

1. The model `qwen3.6-35b-a3b` should appear / be accepted. You can confirm the
   catalogue directly:
   ```bash
   curl https://<your-base-url>/v1/models -H "Authorization: Bearer sk-your-key"
   ```
2. Send a message in Zoo Code. You should see a streamed reply.
3. Try an agentic task (read a file, run a tool). This exercises **tool calling**
   — the gateway passes Zoo Code's OpenAI `tools` through and the engine
   (`--jinja`) returns native `tool_calls`.

## 5. Notes for this model

- **Streaming** is on by default in Zoo Code and fully supported end-to-end
  (SSE pass-through through the gateway).
- **Tool calling**: Zoo Code uses *native* OpenAI tool calling exclusively (no
  XML fallback). The engine is configured for it (llama.cpp `--jinja`; vLLM
  `--enable-auto-tool-choice --tool-call-parser qwen3_coder`, the parser the
  official model card specifies). The default in `.env.example` already matches.
- **Thinking model**: Qwen3.6-35B-A3B emits `<think>…</think>` reasoning. The
  engine extracts it into `reasoning_content` (llama.cpp `--reasoning-format`),
  so it won't pollute the visible answer or tool arguments.
- **Per-key analytics**: issue a different key per machine/teammate (comma-
  separate `GATEWAY_API_KEYS`) to see usage broken down per key in `/admin/usage`.

Next: wire up your local tools via [MCP.md](MCP.md).

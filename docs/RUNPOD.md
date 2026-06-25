# Deploying on RunPod (RTX A6000, 48 GB)

This guide deploys the **all-in-one image** (`runpod/Dockerfile`) — llama.cpp
engine + FastAPI gateway in one container — onto a RunPod **Pod**. A Pod runs a
single container, which is why we bundle both processes under supervisord rather
than using Docker Compose (Compose is for the multi-container path; see the main
[README](../README.md)).

```
Zoo Code ──HTTPS──> https://{podId}-8000.proxy.runpod.net  (RunPod edge proxy)
                              │
                     Gateway :8000  (auth, rate limit, analytics)   ← only exposed port
                              │  127.0.0.1
                     llama-server :8001  (Qwen3.6-35B-A3B IQ4_NL GGUF)
                              │
                     /workspace volume  (model + HF cache, persistent)
```

---

## 1. Build and push the image

The model is **not** baked into the image (it is downloaded at first boot), so
the image stays small and within registry limits.

```bash
# From the repo root:
REGISTRY=ghcr.io/<youruser> TAG=v1 ./runpod/build-and-push.sh
# -> ghcr.io/<youruser>/qwen-runpod:v1
```

If your registry is private, create a **Container Registry Auth** in RunPod
(Settings → Container Registry Auth: name + username + token) and attach it to
the template in the next step.

---

## 2. Create a Network Volume (persistent model storage)

RunPod → **Storage → Network Volumes → New**:

| Field        | Value                                              |
|--------------|----------------------------------------------------|
| Name         | `qwen-models`                                      |
| Data center  | one that has **RTX A6000** in stock                |
| Size         | **60 GB** (≈20 GB model + HF cache + headroom)     |

A Network Volume survives pod **termination** and mounts at `/workspace`. (A
plain Volume Disk also works but is deleted when the pod is terminated.)

> The image points `MODEL_DIR`, `HF_HOME`, `HF_HUB_CACHE`, `LLAMA_CACHE` and the
> analytics DB at `/workspace`, so the ~19.5 GB GGUF downloads **once** and is
> reused on every restart.

---

## 3. Create the Pod

RunPod → **Pods → Deploy**:

1. **GPU**: select **RTX A6000** (48 GB VRAM).
2. **Network Volume**: attach `qwen-models` (mounts at `/workspace`).
3. **Container Disk**: `25 GB` (OS + runtime only; the model lives on the volume).
4. **Template / Image**: enter your image, e.g. `ghcr.io/<youruser>/qwen-runpod:v1`
   (attach the registry auth if private). Leave the **Docker Command** blank —
   the image's supervisord entrypoint handles startup.
5. **Expose HTTP Ports**: `8000`  ← critical; RunPod only proxies declared ports.
   (Optionally also expose `22/tcp` for SSH.)
6. **Environment Variables** (see table below).

### Required / recommended environment variables

| Variable             | Example                              | Notes                                              |
|----------------------|--------------------------------------|----------------------------------------------------|
| `GATEWAY_API_KEYS`   | `{{ RUNPOD_SECRET_gw_key }}`         | **Required.** The key(s) Zoo Code will send.       |
| `ADMIN_API_KEY`      | `{{ RUNPOD_SECRET_admin_key }}`     | Unlocks `/admin/*` analytics. Optional.            |
| `CTX_SIZE`           | `131072`                             | Total KV context (128K). Model supports 262K native. |
| `PARALLEL_SLOTS`     | `1`                                  | 1 = full context per request (raise for concurrency). |
| `CACHE_TYPE_K/V`     | `q8_0`                               | Near-lossless KV quant so 128K fits on 48 GB.       |
| `SERVED_MODEL_NAME`  | `qwen3.6-35b-a3b`                    | Must equal `DEFAULT_MODEL` (both default to this). |
| `HF_TOKEN`           | `{{ RUNPOD_SECRET_hf }}`            | Only if the repo is gated.                          |

The engine is on `127.0.0.1` (never exposed), so it needs no API key — only the
gateway is reachable, and it enforces `GATEWAY_API_KEYS`. Use RunPod **Secrets**
(`{{ RUNPOD_SECRET_name }}`) for keys rather than plain text.

> Changing env vars **restarts the pod** and wipes everything outside
> `/workspace` — which is fine here, because the model and DB live on the volume.

### Or deploy via `runpodctl`

```bash
runpodctl gpu list          # confirm the exact A6000 id
runpodctl pod create \
  --name qwen-platform \
  --gpu-id 'NVIDIA RTX A6000' \
  --gpu-count 1 \
  --image ghcr.io/<youruser>/qwen-runpod:v1 \
  --container-disk-in-gb 25 \
  --network-volume-id <your-network-volume-id> \
  --volume-mount-path /workspace \
  --ports '8000/http,22/tcp' \
  --env '{"GATEWAY_API_KEYS":"sk-your-key","CTX_SIZE":"131072","PARALLEL_SLOTS":"1"}'
```

---

## 4. First boot

Watch the pod **Logs**. On first boot you'll see:

```
[download] fetching Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf ...     # ~19.5 GB, one time
...
[engine] starting llama-server ...
llama server listening on http://0.0.0.0:8001
INFO  gateway.main  starting gateway
```

The first boot downloads ~19.5 GB (a few minutes) and then loads the model into
VRAM (another minute or two). Subsequent boots skip the download.

Check readiness (replace the host with your pod's proxy URL):

```bash
curl https://<podId>-8000.proxy.runpod.net/readyz       # {"status":"ready"} when the model is loaded
curl https://<podId>-8000.proxy.runpod.net/health       # gateway liveness (instant)
```

Smoke-test a completion:

```bash
curl https://<podId>-8000.proxy.runpod.net/v1/chat/completions \
  -H "Authorization: Bearer sk-your-key" \
  -H "Content-Type: application/json" \
  -d '{"model":"qwen3.6-35b-a3b","messages":[{"role":"user","content":"say hi"}]}'
```

Your **Base URL for Zoo Code** is then:

```
https://<podId>-8000.proxy.runpod.net
```

(No `/v1` — Zoo Code appends it. See [ZOO_CODE.md](ZOO_CODE.md).)

---

## 5. Notes, limits & gotchas

- **Proxy timeout ~100 s (Cloudflare).** A request that produces *no bytes* for
  ~100 s gets a `524`. With streaming enabled (Zoo Code streams by default) the
  first token arrives quickly, so this is a non-issue for chat. If you ever make
  very long *non-streaming* calls, prefer streaming or expose a **TCP** port and
  connect via `RUNPOD_PUBLIC_IP:<mapped-port>` instead of the proxy.
- **Bind 0.0.0.0.** The gateway already does; never bind `127.0.0.1` for the
  exposed port or the proxy can't reach it.
- **Ports must be declared in the template**, not just listening in the
  container.
- **Cost.** RTX A6000 is ~\$0.33–0.49/hr. Stop the pod when idle; with a Network
  Volume the model persists and the next start is fast (no re-download).
- **Image stays small** by downloading the model at runtime — keep it that way;
  do not `COPY` the GGUF into the image.
- **Scaling concurrency.** Raise `PARALLEL_SLOTS` (and `CTX_SIZE` proportionally)
  for more concurrent users; quantize the KV cache (`CACHE_TYPE_K/V=q8_0`) to fit
  more context in 48 GB.

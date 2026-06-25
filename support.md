                    VS Code
                       │
                 Zoo Code (Agent)
                       │
        OpenAI-Compatible API Request
                       │
               FastAPI (Optional)
            Auth, Logging, Analytics
                       │
                    vLLM
                       │
           Qwen3-Coder / DeepSeek
                       │
               vast.ai GPU Instance
                       │
        MCP Servers (on your PC)
     ┌────────┬────────┬───────────┐
     │        │        │           │
 Playwright GitHub Filesystem PostgreSQL





 FastAPI
 │
vLLM

always use openAI-compatible API

build below in FastAPI
    Rate limiting
    Analytics
    Usage tracking
    Logging
    Request history
without touching vLLM.


I want to build a production-grade self-hosted LLM serving platform for use with Zoo Code and MCP servers. The architecture should consist of Zoo Code → OpenAI-compatible FastAPI Gateway → vLLM → Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf running on RunPod (or Vast.ai). The FastAPI gateway should expose the standard OpenAI API endpoints (/v1/models, /v1/chat/completions, etc.) while providing authentication, request logging, usage analytics, rate limiting, model routing, and health checks before forwarding requests to vLLM. Use Docker and Docker Compose to containerize both the FastAPI gateway and vLLM so the entire stack can be deployed easily on any GPU server. Configure vLLM using best practices (PagedAttention, KV cache, continuous batching, prefix caching where supported, GPU memory utilization, and context length), relying on vLLM's built-in optimizations rather than implementing custom KV cache logic. The final result should expose a secure OpenAI-compatible endpoint that Zoo Code can connect to as an "OpenAI Compatible" provider, while remaining modular, scalable, and easy to extend with additional models, embeddings, and future services. Please provide a complete project structure, Docker Compose configuration, deployment steps for RunPod, environment variables, FastAPI implementation, and explanations for every design decision so the system follows production-grade software engineering practices.

consider below scenarios
OpenAI compatible streaming API
read the Zoo Code well and build for that and also provide me a setup steps in it under OpenAI compatible mode
read the runpod well and and how i can deploy on the pod.
    RTX A6000
    48 GB VRAM
    50 GB RAM
    9
    vCPUs
    $0.49/hr


Also for here i have downloaded the model but when deploying through github a dockerized container, let the server download it from the huggingface model. 
the below link downloads the model automatically.
https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-IQ4_NL_XL.gguf?download=true

    
MoE config	256 experts, 8 active, 40 layers, embed 2048
uses llama.cpp engine to run the system

Client key (GATEWAY_API_KEYS):  sk-0d96a943a4d3172cda11bfa059d61afe509765247ca6ad11
Admin key  (ADMIN_API_KEY):     admin-888894f32db08bf05bf1090ca80aca9b


git init && git add . && git commit -m "Qwen3.6 OpenAI gateway + engine + RunPod image"
git branch -M main
git remote add origin https://github.com/<you>/<repo>.git
git push -u origin main

GATEWAY_API_KEYS =sk-0d96a943a4d3172cda11bfa059d61afe509765247ca6ad11

https://cv1jhh7cdou16e-8000.proxy.runpod.net


PARALLEL_SLOTS	1 
#Supports only 1 user


ENV Setup
Model_ID =qwen3.6-35b-a3b
PARALLEL_SLOTS = 1
CTX_SIZE       = 131072      # 128K per request
CACHE_TYPE_K   = q8_0        # halves KV-cache memory so 128K fits easily
CACHE_TYPE_V   = q8_0

ZOO CODE Configurations
Context Window: 131072
Max Output Tokens: 16384
Input/Output Price: 0
Temperature (general setting): 0.6 (best for coding/agentic)

# RunPod GPU Worker Setup

## Prerequisites
- RunPod account with GPU Pod access
- Network Volume created (20GB recommended)

## Setup Steps

### 1. Create a Network Volume
- Region: US-TX-3 (or closest)
- Size: 20GB
- Mount path: `/root/.ollama` (Ollama model storage)

### 2. Create a GPU Pod
- GPU: NVIDIA A40 (48GB VRAM) — $0.35/hr
- Template: RunPod Ollama
- Network Volume: attach the volume created above
- Expose port: 11434 (HTTP)

### 3. First Run (models download to Network Volume)
```bash
# SSH into the pod or use the web terminal
# Models are pulled automatically by entrypoint.sh
# First run takes ~10min for downloads, subsequent starts take ~60-90s
```

### 4. Use from your Mac
```bash
# Get the proxy URL from RunPod dashboard (e.g., https://xxx-11434.proxy.runpod.net)
python translate.py samples/mdx/Algorithm_Bot_01.mdx --runpod-url https://xxx-11434.proxy.runpod.net
```

### 5. Stop the pod when done
- RunPod dashboard → Stop Pod (Network Volume persists models)
- Cost when stopped: $0.07/GB/month for Network Volume only

## Custom Docker Build (Optional)
If you want to use the custom Dockerfile instead of RunPod's Ollama template:
```bash
docker build -t local-llm-worker .
# Push to Docker Hub or use RunPod's container registry
```

## Models
| Model | Size | Purpose |
|-------|------|---------|
| translategemma:12b | ~8GB | Korean → English translation |
| qwen3:14b | ~9GB | Korean → Japanese translation |
| nomic-embed-text | ~0.3GB | Embeddings for RAG (Phase 2) |

## Cost Estimate
- Per run (~10 min): $0.06
- Network Volume (20GB): $1.40/month
- Monthly (8 runs): ~$1.88

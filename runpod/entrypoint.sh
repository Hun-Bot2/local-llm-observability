#!/bin/bash
set -e

# Start Ollama server in background
ollama serve &
OLLAMA_PID=$!

# Wait for Ollama to be ready
echo "Waiting for Ollama server..."
for i in $(seq 1 30); do
    if curl -s http://localhost:11434/api/tags > /dev/null 2>&1; then
        echo "Ollama is ready."
        break
    fi
    sleep 2
done

# Pull models if not already present (Network Volume persists these)
echo "Checking models..."

if ! ollama list | grep -q "translategemma:12b"; then
    echo "Pulling translategemma:12b..."
    ollama pull translategemma:12b
fi

if ! ollama list | grep -q "qwen3:14b"; then
    echo "Pulling qwen3:14b..."
    ollama pull qwen3:14b
fi

if ! ollama list | grep -q "nomic-embed-text"; then
    echo "Pulling nomic-embed-text..."
    ollama pull nomic-embed-text
fi

echo "All models ready."
echo "Ollama serving on port 11434"

# Start the worker API
echo "Starting worker API on port 8000"
/opt/worker-venv/bin/python /app/worker.py &
WORKER_PID=$!

cleanup() {
    kill "$WORKER_PID" "$OLLAMA_PID" 2>/dev/null || true
}

trap cleanup EXIT INT TERM

# Keep the container running while either process is alive
wait -n "$OLLAMA_PID" "$WORKER_PID"

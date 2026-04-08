FROM ollama/ollama:latest

# Install runtime dependencies for the worker API
RUN apt-get update && apt-get install -y \
    curl \
    python3 \
    python3-pip \
    && rm -rf /var/lib/apt/lists/*

RUN pip3 install --no-cache-dir \
    fastapi \
    uvicorn \
    requests \
    pydantic

# Copy worker assets
COPY worker.py /app/worker.py
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# Ollama serves on 11434, worker API on 8000
EXPOSE 11434 8000

ENTRYPOINT ["/entrypoint.sh"]

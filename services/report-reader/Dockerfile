# Module 5: SGX Report Reader. One image serves two roles:
#   API:     uvicorn app.main:app        (Kubernetes Deployment)
#   Ingest:  python -m ingest.run ...    (Kubernetes Job, run once per batch of new PDFs)
# Build from the repository root:
#   docker build -f services/report-reader/Dockerfile -t spendcheck/report-reader .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    EMBEDDING_CACHE_DIR=/models

WORKDIR /app

# Runtime user and model folder first, so the model is downloaded as that user (a later
# `chown -R` would copy the model files into an extra image layer).
RUN useradd --create-home --uid 10001 appuser && mkdir -p /models && chown appuser /models

COPY libs/common /opt/spendcheck-common
COPY services/report-reader/requirements.txt .
RUN pip install --no-cache-dir "/opt/spendcheck-common[llm]" -r requirements.txt

USER appuser
# Download the embedding model at build time: containers start fast, work offline, and every
# replica uses exactly the same model files (reproducible embeddings).
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('BAAI/bge-small-en-v1.5', cache_dir='/models')"

COPY services/report-reader/app ./app
COPY services/report-reader/ingest ./ingest

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

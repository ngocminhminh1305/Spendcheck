FROM python:3.14-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/models/huggingface

WORKDIR /code

# Keep dependency installation and model downloads cached across code changes.
COPY requirements.txt .
# Install the same pinned torch version from the official CPU wheel index first,
# avoiding CUDA packages that the default Linux wheels can pull in.
RUN python -m pip install --no-cache-dir torch==2.14.1 --index-url https://download.pytorch.org/whl/cpu \
    && python -m pip install --no-cache-dir -r requirements.txt \
    && python -m pip check
RUN python -m spacy download en_core_web_sm \
    && python -c "from gliner import GLiNER; GLiNER.from_pretrained('urchade/gliner_small-v2.1')"

# All model assets must come from the image when the service runs.
ENV HF_HUB_OFFLINE=1

RUN useradd --create-home --uid 10001 extractor \
    && chmod -R a+rX /opt/models
COPY app ./app
USER extractor

EXPOSE 8000
# This checks HTTP availability; run smoke_api separately to check extraction.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD ["python", "-c", "from urllib.request import urlopen; urlopen('http://127.0.0.1:8000/health', timeout=3).read()"]

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]

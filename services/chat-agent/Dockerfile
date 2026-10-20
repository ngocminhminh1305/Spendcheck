# Module 4: Budget Chat Agent.
# Build from the repository root so the shared library is inside the build context:
#   docker build -f services/chat-agent/Dockerfile -t spendcheck/chat-agent .
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY libs/common /opt/spendcheck-common
COPY services/chat-agent/requirements.txt .
RUN pip install --no-cache-dir "/opt/spendcheck-common[llm]" -r requirements.txt

COPY services/chat-agent/app ./app

# Do not run as root inside the container.
RUN useradd --create-home --uid 10001 appuser
USER appuser

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

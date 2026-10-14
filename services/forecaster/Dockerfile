# 1. Start from a small official Python image
FROM python:3.12-slim

# 2. Everything below happens inside /code in the container
WORKDIR /code

# 3. Install dependencies first: Docker caches this layer, so rebuilding after
#    a code change doesn't reinstall everything
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 4. Copy the service code and the trained model (not data, tests or scripts)
COPY app ./app
COPY models ./models

# 5. Document the port and say how to start the server.
#    0.0.0.0 makes it reachable from outside the container.
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

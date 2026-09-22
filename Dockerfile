# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# greentechhub-ui / greentechhub-fastapi / greentechhub-core are all pinned
# git+https dependencies (see requirements.txt), so pip needs git on PATH.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "src.scheduler"]

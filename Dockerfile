# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# greentechhub-ui / greentechhub-fastapi: copied from their named build
# contexts (see docker-compose.yml's additional_contexts — paths configurable
# via GREENTECHHUB_UI_PATH / GREENTECHHUB_FASTAPI_PATH, local checkouts during
# dev). Once each has tagged releases, swap requirements.txt to a pinned git
# dependency and delete the matching COPY + additional_contexts entry —
# nothing else changes.
COPY --from=greentechhub_ui . /greentechhub-ui
COPY --from=greentechhub_fastapi . /greentechhub-fastapi

# greentechhub-fastapi depends on greentechhub-core via a git+https URL
# (see its own requirements), so pip needs git on PATH to resolve it.
RUN apt-get update && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "src.scheduler"]

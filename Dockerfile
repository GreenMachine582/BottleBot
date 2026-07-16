# Dockerfile
FROM python:3.12-slim

WORKDIR /app

# greentechhub-ui: copied from the `greentechhub_ui` named build context
# (see docker-compose.yml's additional_contexts — path configurable via
# GREENTECHHUB_UI_PATH, a local checkout during dev). Once greentechhub-ui
# has tagged releases, swap requirements.txt to a pinned git dependency and
# delete this COPY + the additional_contexts entry — nothing else changes.
COPY --from=greentechhub_ui . /greentechhub-ui

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN playwright install --with-deps chromium

COPY . .

CMD ["python", "-m", "src.scheduler"]

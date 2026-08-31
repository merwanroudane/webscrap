# Deployment

## Local (Windows / macOS / Linux)

```bash
uv venv --python 3.12
uv pip install -r requirements-core.txt
uv run streamlit run app.py
```

Optional browser support:

```bash
uv pip install playwright
uv run playwright install chromium
```

## Docker

```dockerfile
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential libxml2-dev libxslt1-dev curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-core.txt .
RUN pip install --no-cache-dir -r requirements-core.txt

# Optional: browser rendering
# RUN pip install --no-cache-dir playwright && playwright install --with-deps chromium

COPY . .
EXPOSE 8501
HEALTHCHECK CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

## Streamlit Community Cloud

Works for the deterministic core. Browser rendering and the heavier optional
engines are usually unsuitable there (binary size, memory). Keep `runs/`
ephemeral and provide any keys through the platform secret manager, never in the
repository.

## Configuration

All limits are environment variables (see `.env.example`): request rate, page
caps, response size caps, timeouts and the user agent. Set a contactable user
agent when running against public sources at any scale:

```bash
SRWS_USER_AGENT="MyLabResearchBot/1.0 (+https://mylab.example/contact)"
SRWS_REQUESTS_PER_SECOND=1.0
SRWS_MAX_CRAWL_PAGES=50
```

`SRWS_ALLOW_PRIVATE_NETWORKS` must stay unset in any shared deployment: it
disables the private-address protection in the SSRF guard and exists only for
the offline demo and the test suite.

## Long crawls

Extraction runs inside the Streamlit process today, bounded by the page and row
caps. For very long jobs, move `service.extract` behind a worker queue (RQ, ARQ
or Celery) — the service boundary was designed for that and needs no change to
the UI or the engines.

## Data retention

Each run writes `runs/<run_id>/` with the dataset (Parquet), recipe, provenance,
data dictionary and generated script. Delete individual runs from the History
page, or remove the folder. Nothing is sent anywhere unless you explicitly
enable a cloud provider.

# Deployment

## Local (Windows / macOS / Linux)

```bash
uv venv --python 3.12
uv pip install -r requirements.txt
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

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Optional: browser rendering
# RUN pip install --no-cache-dir playwright && playwright install --with-deps chromium

COPY . .
EXPOSE 8501
HEALTHCHECK CMD curl -f http://localhost:8501/_stcore/health || exit 1
CMD ["streamlit", "run", "app.py", "--server.port=8501", "--server.address=0.0.0.0"]
```

## Streamlit Community Cloud

**Live instance: <https://webscrapapp.streamlit.app/>**

The deterministic core runs well there. Browser rendering and the heavier
optional engines are not suitable (binary size and memory), and the app is built
to work without them.

### Deploying

1. Push the repository to GitHub.
2. On <https://share.streamlit.io>, choose **Create app → Deploy a public app
   from GitHub**.
3. Repository `merwanroudane/webscrap`, branch `main`, main file `app.py`.
4. Open **Advanced settings** and set **Python version to 3.12**. This step
   matters — see below.
5. Deploy.

### Python version

Community Cloud defaults to whatever Python the platform currently ships, which
may be newer than the versions this project is tested against. Two symptoms
follow from getting it wrong:

```text
── poetry ──
Current Python version (3.14.7) is not allowed
Error during processing dependencies
```

That message means Community Cloud used **Poetry** against `pyproject.toml`, and
`requires-python` excluded the interpreter it was running. It is fixed here in
two ways:

* `requirements.txt` exists at the repository root. Community Cloud searches
  `uv.lock` → `Pipfile` → `environment.yml` → `requirements.txt` →
  `pyproject.toml` and uses the **first** it finds, so pip is used and Poetry is
  never invoked.
* `requirements.txt` lists only what the application imports, so the install is
  small and unlikely to hit a package without a wheel for the chosen Python.

Even so, **select Python 3.12** in Advanced settings. Some scientific wheels
(`pyreadstat`, `pyreadr`, `pyarrow`) appear late for a brand-new interpreter, and
3.12 is the version this project is developed and tested on.

For an app that is already deployed and failing, the reliable path is to delete
it from the Community Cloud dashboard and deploy again with the Python version
set. Changing the version is not always offered for an existing app.

### One dependency file only

Community Cloud uses the first manifest it finds and ignores the rest. Do not
add `Pipfile`, `environment.yml` or `uv.lock` to this repository unless you also
remove `requirements.txt`, or dependency resolution will silently change.

### What to expect on Community Cloud

| | |
| --- | --- |
| Engines available | direct file, JSON API, HTML table, repeated DOM, structured metadata, feeds, links, article |
| Engines unavailable | browser rendering (Playwright), Crawl4AI, PDF documents — shown honestly as *optional* in Settings |
| Storage | `runs/` is ephemeral; the container is reset on reboot. Ask users to download the research bundle. |
| Secrets | Use the platform secret manager, never a committed `.env`. |
| Private networks | Leave `SRWS_ALLOW_PRIVATE_NETWORKS` unset. The bundled demo does not need it: it allow-lists only its own loopback port. |

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

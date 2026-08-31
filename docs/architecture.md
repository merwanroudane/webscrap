# Architecture

## Layers

```text
Streamlit UI (src/scraper_app/ui)
        │  thin: rendering, session state, translation
        ▼
service.py                     analyze → preflight → extract → clean → persist → bundle
        ▼
routing/                       capability registry · scoring · router (+ rationale)
        ▼
engines/                       BaseEngine implementations, all returning ExtractionResult
        ▼
engines/http_client.py         guarded, rate-limited, size-bounded HTTP
        ▼
security/url_guard.py          SSRF validation on every request and every redirect
```

Supporting layers:

| Package | Responsibility |
| --- | --- |
| `discovery/` | Profiles a source, proposes `CandidateDataset` objects, and finds candidate sources. |
| `ai/` | Provider-independent LLM layer: protocol, providers, prompts, schema-validated structured output. Optional and off by default. |
| `providers/` | Remote browsers, managed fetch, discovery, semantic content, document extractors, and the registry that reports their state. |
| `extraction/` | Natural-language schema, field mapping, dedupe, normalization. |
| `data/` | Cleaning, validation, quality profiling, dictionary, provenance. |
| `export/` | Format builders with per-format capability checks. |
| `visualize/` | Plotly charts and the NetworkX crawl graph. |
| `reproducibility/` | Recipe, generated script, README, research bundle. |
| `storage/` | Parquet run artifacts and the history manifest. |

## Request lifecycle

1. **Guard** — `security.url_guard.guard_url` normalizes the URL, rejects
   non-http(s) schemes, userinfo and blocked ports, resolves DNS and refuses any
   non-public address. Redirect hops are re-validated inside `http_client.fetch`.
2. **Robots** — `security.robots.check` fetches and interprets robots.txt
   (protego when available, `urllib.robotparser` otherwise) and the status is
   carried into the profile and the provenance manifest.
3. **Profile** — `discovery.profiler.profile_source` classifies the response
   (file / JSON / XML+feed / HTML), then for HTML runs the table detector, the
   structured-data extractor, the repeated-pattern detector, the API detector,
   the pagination detector and link/file/feed collection. If the static evidence
   says JavaScript is required, the optional Playwright probe renders the page
   and captures XHR/fetch JSON responses.
4. **Candidates** — every finding becomes a `CandidateDataset` with a score, a
   confidence band, sample rows and a plain-language *why*.
5. **Route** — `routing.router.choose_engine` scores available engines and picks
   the cheapest reliable one, following the documented preference order and
   recording a `RouteDecision`.
6. **Extract** — the engine walks pagination with hard stop conditions
   (max pages, max rows, absent next link, repeated page hash, empty page,
   per-page error) and reports schema drift instead of dropping rows silently.
7. **Assemble** — records become a DataFrame with stable column order and
   optional provenance columns; the requested schema is mapped onto the actual
   columns and unmatched fields are reported, never invented.
8. **Clean** — opt-in, reversible operations run from `raw_df`, never in place.
9. **Package** — quality report, data dictionary, provenance, recipe, generated
   script and the research ZIP.

## The AI layer

Deterministic parsing always runs first. A model may be consulted only when the
researcher enabled AI *and* the deterministic path left a gap:

```text
sample page → propose schema → validate against evidence in the page
            → deterministic extraction for every remaining page
            → AI re-enters only on schema drift or extraction failure
```

Every reply is parsed into a Pydantic model and rejected if it fails. Proposed
values are additionally checked against the page text, so a fabricated value
cannot become a row. Usage and cost are recorded per run.

## Key contracts

* `BaseEngine.availability()` never raises; an optional dependency that is not
  installed produces a reason and an install hint.
* `ExtractionResult` is the single result shape for every engine.
* `ScraperError(code, detail, context)` is the single failure shape; the UI
  renders `message(lang)` plus `actions(lang)`.

## Performance

Response sizes, preview rows, crawl pages, redirects and timeouts are bounded in
`config.Limits`. Quality profiling samples above 200k rows. Datasets are stored
as Parquet artifacts under `runs/<run_id>/` rather than kept as Python lists in
session state. Long crawls run in-process today; the `service.extract` boundary
is the seam where an external worker queue would attach.

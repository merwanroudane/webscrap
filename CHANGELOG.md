# Changelog

Every release records what changed, because a provenance manifest stamps the
version that produced a dataset. If two runs disagree, the version is how you
find out why.

This project follows [Semantic Versioning](https://semver.org/).

---

## 0.2.1 — 2026-09-01

Bug-fix release. No change to the recipe format, the export formats or the
security model, so recipes and datasets from 0.2.0 remain valid. Every defect
below could reach a user; several made a *successful* run look like a failure.

### Fixed — engines

* **Scrapy worked only once per session.** `CrawlerProcess.start()` ran inside
  the Streamlit process, and a Twisted reactor cannot be restarted. The first
  extraction succeeded and every later one raised `ReactorNotRestartable`. The
  crawl now runs in a throwaway subprocess.
* **Crawlee, crawl4ai and the agentic engines crashed inside a running event
  loop.** All four called `asyncio.run()`, which raises when a loop already owns
  the thread. They now share `run_async_safely`, which uses a worker thread when
  it must. A test forbids `asyncio.run` anywhere in `engines/`.
* **Browser Use discarded successful runs.** Whatever an agent returned was
  stringified into an HTML parser — correct for one of the four shapes agents
  actually return. A JSON answer, the normal outcome once a schema is requested,
  produced "no data detected"; a prose answer was silently dropped. Output is
  now classified as records, HTML, prose or empty and handled accordingly, and
  prose raises a typed error instead of masquerading as data.
* **Browser Use now uses structured output** when an extraction schema exists,
  so its answer is validated rather than trusted.
* **Stagehand** tolerates both the synchronous and asynchronous Python SDKs.
* **Skyvern's engine version** was hardcoded; it reads `SKYVERN_ENGINE` now.

### Fixed — providers and models

* **LiteLLM reported "Ready" and then failed to authenticate.** Availability was
  true if *any* backend key existed, but the default model was always
  `gpt-4o-mini`, so a user with only `ANTHROPIC_API_KEY` was misled. The default
  model now matches a key that is present, and availability checks the key that
  model needs.
* **The provider registry disagreed with LiteLLM's own check.** Descriptors can
  delegate to the provider, so the Settings table and the AI page cannot drift.
* **Docling attributed an entire multi-page PDF to page 1**, and `max_pages`
  limited only tables. Text is now placed on the page Docling recorded for it,
  `max_pages` limits real pages, and a whole-document fallback is labelled
  rather than passed off as page 1.
* **Bright Data silently ignored** the run's "render JavaScript" and country
  options. Web Unlocker decides both from the zone, so the behaviour is correct
  — but it is now disclosed instead of dropped without a word.

### Added

* Provenance records `provider_id`, `provider_category`, `ai_provider`,
  `ai_model`, `remote_browser_provider` and `managed_fetch_provider`, so a
  methods section can state which vendor saw the query and which model wrote a
  column. Identifiers only; a test proves no key survives into the manifest.
* Recipes record the non-secret runtime — engine, provider, model, and what the
  run was permitted to do — so a strategy can be replayed faithfully.
* `CITATION.cff`.
* Contract tests for all ten managed-fetch vendors: credential sent, target URL
  carried, empty document refused, 401/403/429/timeout typed correctly, key
  absent from every error message, SSRF guard still applied.
* Security regression tests that a vendor key passed as a query parameter cannot
  reach a log, error message, recipe or provenance manifest.

### Changed

* **`uv.lock` is now the single source of truth for dependencies.**
  `requirements.txt` is generated from it and fully pinned; CI fails if they
  drift. The previous documentation claimed `requirements.txt` was what
  Streamlit Community Cloud installs, which was wrong — `uv.lock` ranks above it
  in the search order. Both now install identical versions either way.
* CI gained a coverage floor, a locked-environment job, and a manifest
  consistency check.

---

## 0.2.0 — 2026-08-31

Second release: the provider-independent AI layer, the capability registry with
honest states, remote-browser and managed-fetch providers, source discovery,
document extraction, and the reproducibility bundle.

## 0.1.0

First release: deterministic extraction core, SSRF guard, robots handling,
provenance, exports and the guided workflow.

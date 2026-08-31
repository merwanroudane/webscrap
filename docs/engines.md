# Engines

Every engine implements `BaseEngine`: `name`, `capabilities`, `availability()`,
`probe()` and `extract()`, returning the same `ExtractionResult`.

## Implemented

### Deterministic core — free, local, always preferred

| Engine | Tier | Requires |
| --- | --- | --- |
| `direct_file` | 0 | — |
| `feed` | 0 | feedparser |
| `json_api` | 1 | — |
| `table` | 1 | — |
| `repeated_dom` | 1 | — |
| `structured` | 1 | extruct |
| `links` | 1 | — |
| `article` | 1 | trafilatura (falls back to lxml) |
| `document` | 1 | `documents` extra |

### Crawlers and browsers

| Engine | Tier | Requires | Notes |
| --- | --- | --- | --- |
| `scrapy` | 2 | `crawler` extra | Bounded crawls with a real scheduler |
| `crawlee` | 2 | `crawler` extra | Same job through a request queue |
| `playwright` | 3 | `browser` extra | Default browser; also drives remote sessions |
| `selenium` | 3 | `browser` extra | Compatibility only |
| `scrapling` | 3 | `modern` extra | Adaptive selector recovery after redesigns |

### Adaptive, managed and agentic

| Engine | Tier | Cost | Requires |
| --- | --- | --- | --- |
| `crawl4ai` | 4 | local compute | `modern` extra (semantic mode needs AI on) |
| `firecrawl` | 4 | metered | `cloud` extra + `FIRECRAWL_API_KEY` |
| `scrapegraph` | 4 | metered | `cloud` extra + `SGAI_API_KEY` |
| `agentql` | 4 | metered | `AGENTQL_API_KEY` (REST; SDK optional) |
| `managed_fetch` | 4 | metered | any managed provider key |
| `semantic_content` | 4 | metered | `DIFFBOT_TOKEN` or `JINA_API_KEY` |
| `stagehand` | 5 | metered | `agents` extra + model key |
| `browser_use` | 5 | metered | `agents` extra + model key |
| `skyvern` | 5 | metered | `SKYVERN_API_KEY` |

## Provider protocols

Four abstractions keep vendor count from multiplying code:

| Protocol | Providers | Contract |
| --- | --- | --- |
| `RemoteBrowserProvider` | Browserbase, Hyperbrowser, Steel, Browserless | create a session, return a CDP endpoint, release it |
| `ManagedFetchProvider` | ZenRows, ScrapingBee, ScraperAPI, ScrapingAnt, Scrapfly, Oxylabs, Bright Data, Scrapeless, Nimble, Thordata | build the vendor call, normalize the response to HTML |
| `SourceDiscoveryProvider` | Tavily, Exa, Jina Search | query → candidate sources, guard-filtered |
| `SemanticContentProvider` | Diffbot, Jina Reader | URL → title/text/metadata |
| `DocumentExtractor` | PyMuPDF, Docling | bytes → pages, text, tables |

Two rules hold for every provider:

* the **target URL still passes the SSRF guard** — using a vendor never bypasses
  our own access policy;
* anti-bot and CAPTCHA-solving switches are never exposed. These adapters fetch
  public pages.

## Not implemented, and why

| Provider | Reason |
| --- | --- |
| Apify | Actor-based: every actor has its own input schema, so a generic adapter would misrepresent what it does. Use Crawlee locally, or call a specific actor directly. |
| Zyte API | Entirely overlapped by the managed fetch providers already implemented; adding it would mean a second, redundant metered path. |
| Firecrawl `extract` | The current published SDK documents this method as unavailable. Scrape, crawl, map and search are wired. |

## Routing order

1. downloadable structured file
2. documented public API
3. observed stable public JSON endpoint
4. embedded JSON / JSON-LD / structured metadata
5. HTML table
6. deterministic repeated DOM selectors
7. static crawl
8. local browser (Playwright)
9. adaptive/semantic local engine
10. hosted provider (only with explicit opt-in)

The scorer weights source fit (0.40), determinism (0.15), reliability (0.15),
speed (0.10), cost (0.10) and user preference (0.10), then applies policy: a
metered provider scores zero unless `allow_cloud` is set, and the browser scores
zero unless `allow_browser` is set. Ties break toward the lower tier. The
selected engine, the alternatives and the fallback chain are visible in
**Diagnostics**.

## Network API discovery

The Playwright probe listens to responses during page load, ignores images,
fonts, stylesheets and media, keeps only JSON responses that look like datasets,
and records the URL, method, content type and a bounded sample of the response
shape — never request headers. When a stable endpoint is found, the router
prefers calling it with HTTPX instead of scraping the rendered DOM, because the
API route is faster, cheaper and reproducible.

## Pagination

`page_number`, `offset_limit`, `cursor`, `next_link`, `next_button`,
`load_more` and `infinite_scroll`. Stop conditions: max pages, max rows, empty
page, missing next link, repeated page hash, per-page error, hard page cap.

## Adding an engine

1. Subclass `BaseEngine` in `engines/`, implementing `availability()` and
   `extract()`.
2. Register it in `routing/capability_registry.engine_instances`.
3. Add a `ProviderInfo` row so Settings reports it honestly.
4. Add it to `routing/router.FALLBACKS` for the dataset kinds it can serve.
5. Add a `code_generator` builder so reproducer scripts match it.
6. Add tests with fixtures/mocks — never a paid live call in CI.

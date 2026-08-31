# Engines

Every engine implements `BaseEngine`: `name`, `capabilities`, `availability()`,
`probe()` and `extract()`, returning the same `ExtractionResult`.

## Implemented

| Engine | Tier | Capabilities | Cost | Requires |
| --- | --- | --- | --- | --- |
| `direct_file` | 0 | files | free | — |
| `feed` | 0 | rss, xml | free | feedparser |
| `json_api` | 1 | json, pagination | free | — |
| `table` | 1 | html_tables, pagination | free | — |
| `repeated_dom` | 1 | static_html, pagination, crawl | free | — |
| `structured` | 1 | structured_output | free | extruct (optional) |
| `links` | 1 | static_html, crawl | free | — |
| `article` | 1 | static_html, crawl | free | trafilatura (falls back to lxml) |
| `document` | 1 | documents | local compute | pymupdf |
| `playwright` | 3 | javascript, network_capture | local compute | playwright + chromium |
| `crawl4ai` | 4 | javascript, semantic | local compute | crawl4ai |
| `firecrawl` | 4 | hosted semantic | metered | firecrawl-py + key + `allow_cloud` |

Other providers in the ecosystem (Scrapling, Scrapy, Crawlee, Selenium,
ScrapeGraphAI, AgentQL, Stagehand, Browser Use, Skyvern, Browserbase, Apify,
Zyte, Docling) are listed in the capability registry as *catalogue* entries:
known, documented, and honestly marked as not implemented in this version.

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

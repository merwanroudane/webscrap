# Example — a JSON API

**Goal:** collect a paginated JSON endpoint as a tidy dataset, without a browser.

## Why this route wins

When a page loads its numbers through a JSON request, calling that endpoint
directly with HTTPX is faster, lighter and reproducible: the same URL returns
the same records tomorrow, while a rendered DOM can change with any redesign.
The router therefore prefers `json_api` over `playwright` whenever an endpoint
is observed.

## Steps

1. Paste either the API URL itself (`https://example.org/api/indicators?page=1`)
   or the page that uses it.
2. Click **Analyze website**. The analysis page shows a
   `JSON data · /api/indicators` candidate with the record count and the field
   names (`country, year, value, unit`), and the **APIs / JSON** tab lists how it
   was found (`direct`, `html` or `network`).
3. Click **Use this dataset**, then **Preview extraction**.
4. Turn on **Follow pagination** and set the page limit. The detector already
   filled in the plan — `page_number`, parameter `page`, template
   `…/api/indicators?page={page}`.
5. **Start extraction.** The engine walks pages until one returns an empty
   record list, a page repeats, or your limit is reached.

## Pagination styles handled

| Style | Detected from | Stop condition |
| --- | --- | --- |
| `?page=2` | the URL query or a Next link | empty page / repeated hash / limit |
| `?offset=0&limit=100` | the URL query | empty page / limit |
| `next_cursor`, `next_page_token` | the response body | cursor absent |

## Recipe

```yaml
name: JSON data · /api/indicators
source_url: https://example.org/api/indicators?page=1
engine: json_api
dataset:
  kind: api
  records_path: data
  api_url: https://example.org/api/indicators?page=1
pagination:
  type: page_number
  param: page
  start: 1
  url_template: https://example.org/api/indicators?page={page}
limits:
  max_pages: 5
```

`records_path` is the path to the array inside the response — the app finds it
automatically, and you can override it in Advanced mode.

## Generated reproducer

The script uses `httpx` with the same template and a `walk()` helper that
follows `records_path`, sleeping `REQUEST_DELAY_SECONDS` between pages. No
credentials are embedded; if the API needs a key, add it from an environment
variable yourself.

## Try it offline

```text
Help → Try the offline demo → JSON API
```

The bundled fixture serves six records across two pages and an empty third
page, so you can watch the stop condition work.

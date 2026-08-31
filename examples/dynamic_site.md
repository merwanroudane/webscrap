# Example — a JavaScript-rendered page

**Goal:** get data from a page whose HTML arrives almost empty and fills in
after scripts run.

## What the app does first

Before reaching for a browser, the profiler looks for the data the scripts are
about to use:

1. **Embedded state** — `__NEXT_DATA__`, `window.__NUXT__`,
   `window.__INITIAL_STATE__`, hydration blobs and
   `<script type="application/json">` blocks. If one contains an array of
   records, that becomes a candidate immediately — no browser needed.
2. **Referenced endpoints** — URLs matching `/api/`, `/v1/`, `.json` found in
   scripts are verified with a single request.
3. **Observed endpoints** — only if steps 1–2 fail and browser mode is on, the
   Playwright probe loads the page, listens to XHR/fetch responses, ignores
   images/fonts/CSS, and keeps JSON responses that look like datasets.

The **Overview** tab explains the decision under *Why JavaScript may be needed*,
listing the concrete evidence (framework markers, little readable text, no
tables or repeated blocks in the static HTML).

## Steps

1. Paste the page URL and click **Analyze website**.
2. If a JSON candidate appears, use it — the preflight will say
   `Direct JSON API` and `Uses browser: no`.
3. If nothing structured is found, open **Access and privacy options** on the
   Home page and make sure *Allow browser rendering when needed* is ticked, then
   analyze again. Browser mode needs the optional install:

   ```bash
   pip install playwright && playwright install chromium
   ```

4. The rendered DOM is passed to the same deterministic table and
   repeated-pattern extractors, so the output shape matches a static page.

## Load more and infinite scroll

In Advanced mode, set the pagination type explicitly:

| Type | What the browser does | Bounded by |
| --- | --- | --- |
| `next_button` | clicks the next control until it disappears or is disabled | max pages |
| `load_more` | clicks the button, waits, repeats | max pages, `SRWS_MAX_SCROLLS` |
| `infinite_scroll` | scrolls, waits, compares page height | two stable heights, `SRWS_MAX_SCROLLS` |

Give the browser a `wait_for` CSS selector when the content needs a moment —
if that element never appears you get `SELECTOR_NOT_FOUND`, not a silent empty
dataset.

## Cost and privacy

Browser rendering is local compute: nothing leaves your machine. The preflight
card marks it `Uses local browser`, and no cloud provider is used unless you
explicitly enable one.

## Try it offline

```text
Help → Try the offline demo → JavaScript page with embedded JSON
```

The fixture has an empty `<div id="root">`, a `__NEXT_DATA__` blob and a
`fetch("/api/indicators?page=1")` call — so you can see the app choose the API
over the browser, which is the behaviour to expect on real dashboards.

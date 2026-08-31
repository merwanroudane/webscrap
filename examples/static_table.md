# Example — a statistical table

**Goal:** turn an HTML table of macro indicators into an analysis-ready dataset.

## Steps

1. Paste the page URL.
2. Optionally type: `Extract country, year, inflation rate, GDP and unemployment`.
3. Click **Analyze website**.
4. The analysis page shows `Table 1 · <caption>` with `8 rows × 5 columns` and a
   *High confidence* badge. Click **Use this dataset**.
5. Review the field table, then **Preview extraction**.
6. The preflight card reports `HTML table`, 1 page, 0 AI calls, no cloud
   provider. Click **Start extraction**.
7. In **Quality → Clean & validate**, tick *Convert numeric text to numbers* and
   *Parse percentages*, then **Apply cleaning**: `9.3%` becomes `0.093` and the
   operations table reports how many cells changed.
8. Download CSV/Stata/Parquet, or the complete research package.

## Try it offline

The bundled demo serves this exact page:

```text
Help → Try the offline demo → Statistical table
```

## What the recipe looks like

```yaml
name: Table 1 · Annual inflation rate (%)
source_url: http://127.0.0.1:PORT/table.html
engine: table
dataset:
  kind: table
  table_index: 0
pagination:
  type: none
limits:
  max_pages: 1
  respect_robots: true
```

The generated reproducer uses `httpx` + `pandas.read_html` with the same table
index — no browser, no AI.

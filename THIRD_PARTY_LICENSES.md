# Third-party licences

Smart Research Web Scraper is released under the [MIT licence](LICENSE). It
depends on the open-source projects below, each under its own licence. Nothing
here is vendored — every package is installed from PyPI at its own version, and
each package's own metadata is the authoritative statement of its licence.

To regenerate this inventory for the versions you actually have installed:

```bash
python -m pip install pip-licenses
pip-licenses --format=markdown --with-urls --order=license
```

---

## Required dependencies

These are installed by `requirements.txt` and are what the hosted app runs on.
All are permissive licences (MIT, BSD or Apache-2.0), compatible with
distributing this project under MIT.

| Package | Licence | Project |
| --- | --- | --- |
| streamlit | Apache-2.0 | https://github.com/streamlit/streamlit |
| pydantic | MIT | https://github.com/pydantic/pydantic |
| python-dotenv | BSD-3-Clause | https://github.com/theskumar/python-dotenv |
| PyYAML | MIT | https://github.com/yaml/pyyaml |
| httpx | BSD-3-Clause | https://github.com/encode/httpx |
| lxml | BSD-3-Clause | https://github.com/lxml/lxml |
| cssselect | BSD-3-Clause | https://github.com/scrapy/cssselect |
| trafilatura | Apache-2.0 | https://github.com/adbar/trafilatura |
| extruct | BSD-3-Clause | https://github.com/scrapinghub/extruct |
| feedparser | BSD-2-Clause | https://github.com/kurtmckee/feedparser |
| Protego | BSD-3-Clause | https://github.com/scrapy/protego |
| pandas | BSD-3-Clause | https://github.com/pandas-dev/pandas |
| numpy | BSD-3-Clause (with 0BSD, MIT, Zlib, CC0-1.0 components) | https://github.com/numpy/numpy |
| pyarrow | Apache-2.0 | https://github.com/apache/arrow |
| duckdb | MIT | https://github.com/duckdb/duckdb |
| pandera | MIT | https://github.com/unionai-oss/pandera |
| openpyxl | MIT | https://foss.heptapod.net/openpyxl/openpyxl |
| XlsxWriter | BSD-2-Clause | https://github.com/jmcnamara/XlsxWriter |
| pyreadstat | Apache-2.0 | https://github.com/Roche/pyreadstat |
| plotly | MIT | https://github.com/plotly/plotly.py |
| networkx | BSD-3-Clause | https://github.com/networkx/networkx |

Transitive dependencies pulled in by the packages above are likewise MIT, BSD,
Apache-2.0, PSF-2.0, MIT-CMU or MPL-2.0. None is copyleft in a way that affects
distribution of this project.

---

## Optional dependencies

None of these is installed by default. Each unlocks one feature and is reported
in **Settings → Engines & keys** with its install command. Installing one is
your decision, and its licence then applies to your installation.

| Package | Licence | Feature it enables |
| --- | --- | --- |
| playwright | Apache-2.0 | Browser rendering and network API discovery |
| selenium | Apache-2.0 | Compatibility browser path |
| scrapy | BSD-3-Clause | Bounded multi-page crawling |
| crawlee | Apache-2.0 | Bounded crawling through a request queue |
| crawl4ai | Apache-2.0 | Local adaptive extraction engine |
| scrapling | BSD-3-Clause | Adaptive selector recovery |
| firecrawl-py | MIT | Hosted extraction provider (also needs an API key) |
| scrapegraph-py | MIT | Hosted AI extraction (also needs an API key) |
| agentql | MIT | Semantic element queries (the REST path needs only a key) |
| stagehand | MIT | Agentic browser workflows |
| browser-use | MIT | Agentic browser workflows |
| skyvern | AGPL-3.0 | Hosted agentic workflows (the REST path needs only a key) |
| anthropic | MIT | Anthropic model provider |
| openai | Apache-2.0 | OpenAI model provider |
| google-genai | Apache-2.0 | Google Gemini model provider |
| litellm | MIT | Multi-backend model routing |
| instructor | MIT | Optional structured-output helper |
| rapidfuzz | MIT | Better fuzzy field matching |
| dateparser | BSD-3-Clause | Multilingual date parsing |
| ftfy | Apache-2.0 | Repairing mojibake in scraped text |
| tldextract | BSD-3-Clause | Registrable-domain comparison |
| docling | MIT | Layout-aware document extraction |
| kaleido | MIT | Exporting charts as PNG/SVG/PDF |
| **pymupdf** | **AGPL-3.0-or-later** (commercial licence available) | PDF/document extraction |
| **pyreadr** | **AGPL-3.0-or-later** | Exporting datasets as R `.rds` |

Licences are as published by each project at the time of writing; each package's
own metadata is authoritative. The `skyvern` **package** is AGPL-3.0, which is
why the adapter here talks to the hosted REST API and does not import it.

### Why pyreadr and pymupdf are not installed by default

Both are licensed under the **GNU Affero GPL**. That is a legitimate choice by
their authors, but it is a strong copyleft licence with a network-use clause,
and shipping it as a *required* dependency of an MIT-licensed application —
particularly one that is publicly hosted — would misrepresent the terms under
which this project can be used.

They are therefore optional. The application detects their absence and says so
plainly rather than failing:

```text
R (.rds)   ⚠ RDS export needs the optional pyreadr package (AGPL-3.0).
```

If you install either one, you are choosing to bring AGPL code into your own
deployment, and the AGPL's obligations apply to that deployment. For R users who
would rather avoid this, exporting **CSV** or **Parquet** and reading it with
`readr::read_csv()` or `arrow::read_parquet()` gives the same data under
permissive terms.

SPSS export uses **pyreadstat** (Apache-2.0) and Stata export uses pandas, so
both remain available in the default installation.

---

## Data collected with this tool

The MIT licence covers **this software only**. It says nothing about the data
you collect with it. Content retrieved from a website remains subject to that
site's terms of use, copyright, database rights, licence and any applicable
privacy law. Check those before redistributing a dataset, and cite the original
publisher.

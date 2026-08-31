# Security

## SSRF prevention (`security/url_guard.py`)

* Only `http` and `https`. Any other scheme — including bare `file:`, `data:`,
  `gopher:`, `javascript:` — is rejected before a request is made.
* `user:pass@host` forms are rejected.
* A small set of administrative ports (22, 23, 25, 445, 3306, 5432, 6379, 9200,
  11211) is refused.
* Host names ending in `.localhost`, `.local`, `.internal`, `.home.arpa` and the
  literal loopback names are refused.
* DNS is resolved and **every** returned address is validated: private,
  loopback, link-local, multicast, reserved, unspecified, IPv6 site-local and
  IPv4-mapped equivalents are refused.
* Cloud metadata endpoints (`169.254.169.254`, `metadata.google.internal`, …)
  are refused by name and by address.
* Every redirect hop is re-validated; the redirect count is bounded.

The single escape hatch is `SRWS_ALLOW_PRIVATE_NETWORKS=true`, used by the test
suite and by the bundled offline demo to reach `127.0.0.1`. It is off by
default, and Settings shows when it is on.

## Access rules

robots.txt is fetched, displayed and respected by default. Disabling it lives in
an Advanced expander with an explicit statement of responsibility. The app does
not solve CAPTCHAs, defeat bot challenges, or work around logins and paywalls;
when a challenge or login wall is detected, the profile says so and the error
guidance points to official APIs.

## Prompt-injection defence (`security/content_safety.py`)

Page content is always data:

* `detect_injection` flags agent-directed phrases, and the finding is surfaced
  as a warning on the analysis page.
* `wrap_untrusted` wraps any excerpt sent to a model in an explicit
  untrusted-content block with instructions never to follow it.
* Only bounded excerpts are ever sent, never whole pages, and never together
  with credentials.
* AI field proposals return a constrained JSON shape validated against Pydantic;
  proposed names are tagged `ai_inferred` in the data dictionary so a reader can
  tell them apart from source-native names.

## Secret hygiene (`security/secrets.py`)

Authorization/cookie/api-key headers and key-like query parameters are redacted
in logs, and stripped from recipes, provenance files and generated code, which
use environment variables instead. Advanced-mode credentials are password
inputs held in memory for the run only.

## What the app deliberately does not do

* No credential storage, no session capture, no anti-bot evasion.
* No silent fabrication: a failed extraction raises a typed error rather than
  returning an empty or synthetic dataset.
* No shell execution from the web UI — the Settings page prints install
  commands for you to run yourself.

## Responsibilities that remain yours

robots.txt is an access signal, not a licence. Check the terms of use, the data
licence, database rights and any personal-data restrictions of a source before
collecting from it at scale or redistributing the result, and cite the original
publisher alongside this tool.

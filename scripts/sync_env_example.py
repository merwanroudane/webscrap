"""Regenerate .env.example from the credential declarations.

Run after adding or changing a provider:

    python scripts/sync_env_example.py

CI checks that the committed file matches, so a provider can never be readable
by the code but undocumented for the user.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from scraper_app.credentials import render_env_example  # noqa: E402


def main() -> int:
    target = ROOT / ".env.example"
    generated = render_env_example()
    check = "--check" in sys.argv

    current = target.read_text(encoding="utf-8") if target.exists() else ""
    if current.replace("\r\n", "\n") == generated:
        print(".env.example is up to date")
        return 0

    if check:
        print("ERROR: .env.example is out of date. Run: python scripts/sync_env_example.py")
        return 1

    target.write_text(generated, encoding="utf-8", newline="\n")
    print(f"wrote {target} ({len(generated.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

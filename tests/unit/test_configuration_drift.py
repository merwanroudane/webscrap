"""Configuration drift tests (audit v0.2 sections 24, 25 and 94).

The failure these prevent: a provider that the code can read a key for, but
that no user could ever configure because the variable is documented nowhere.
Before this suite, twenty provider keys were in exactly that state.

Everything here compares the code against itself and against the files that
document it, so drift fails the build instead of shipping.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from scraper_app import credentials
from scraper_app.config import PROVIDER_ENV_KEYS
from scraper_app.providers import registry as provider_registry
from scraper_app.routing.capability_registry import all_providers

ROOT = Path(__file__).resolve().parents[2]
ENV_EXAMPLE = ROOT / ".env.example"

#: Variables read via os.getenv anywhere in the package.
_ENV_PATTERN = re.compile(r'(?:os\.getenv|os\.environ(?:\.get)?)\(?\[?\s*"([A-Z][A-Z0-9_]*)"')


def _source_env_names() -> set[str]:
    names: set[str] = set()
    for path in (ROOT / "src" / "scraper_app").rglob("*.py"):
        names |= set(_ENV_PATTERN.findall(path.read_text(encoding="utf-8")))
    return names


def _documented_env_names() -> set[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return set(re.findall(r"^#?\s*([A-Z][A-Z0-9_]*)=", text, flags=re.MULTILINE))


# ------------------------------------------------------------ single registry
def test_provider_env_keys_are_derived_not_duplicated():
    """config.PROVIDER_ENV_KEYS must mirror the credential registry exactly."""
    expected = {s.id: list(s.env_vars) for s in credentials.ALL_CREDENTIALS if s.env_vars}
    assert dict(PROVIDER_ENV_KEYS) == expected


def test_every_provider_descriptor_key_is_declared():
    """A descriptor may not require a variable the registry does not know."""
    declared = set(credentials.all_env_names())
    for descriptor in provider_registry.all_descriptors():
        for key in descriptor.env_keys:
            assert key in declared, f"{descriptor.id} requires undeclared {key}"


def test_engine_credentials_resolve():
    """Each engine that names a credential must map to a real spec."""
    for info in all_providers():
        if info.credential:
            assert credentials.by_id(info.credential) is not None, info.name


def test_catalogue_entries_do_not_advertise_keys():
    """An unimplemented adapter must not imply that setting a key enables it."""
    for info in all_providers():
        if not info.implemented:
            assert not info.credential, (
                f"{info.name} is catalogue-only but names credential {info.credential}"
            )


# --------------------------------------------------------- .env.example sync
def test_env_example_is_in_sync_with_the_registry():
    """`.env.example` is generated; a stale copy fails here, not in production."""
    generated = credentials.render_env_example()
    current = ENV_EXAMPLE.read_text(encoding="utf-8").replace("\r\n", "\n")
    assert current == generated, (
        "`.env.example` is out of date. Run: python scripts/sync_env_example.py"
    )


def test_every_readable_variable_is_documented():
    """Anything the code reads must appear in `.env.example`."""
    documented = _documented_env_names()
    undocumented = sorted(name for name in _source_env_names() if name not in documented)
    assert not undocumented, f"read by the code but undocumented: {undocumented}"


def test_every_documented_variable_is_used_or_declared():
    """And nothing is documented that the application does not know about."""
    declared = set(credentials.all_env_names())
    used = _source_env_names()
    stray = sorted(n for n in _documented_env_names() if n not in declared and n not in used)
    assert not stray, f"documented but unknown to the code: {stray}"


# -------------------------------------------------------------- sanity checks
def test_no_real_secret_is_committed():
    """`.env.example` must never carry a value."""
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        name, _, value = stripped.partition("=")
        assert value.strip() == "", f"{name} has a value in .env.example"


@pytest.mark.parametrize(
    "provider_id,expected",
    [
        ("browserbase", ("BROWSERBASE_API_KEY",)),
        ("zenrows", ("ZENROWS_API_KEY",)),
        ("oxylabs", ("OXYLABS_USERNAME", "OXYLABS_PASSWORD")),
        ("tavily", ("TAVILY_API_KEY",)),
        ("diffbot", ("DIFFBOT_TOKEN",)),
        ("skyvern", ("SKYVERN_API_KEY",)),
    ],
)
def test_known_providers_declare_their_keys(provider_id, expected):
    assert credentials.env_keys_for(provider_id) == expected


def test_dangerous_setting_is_documented_as_dangerous():
    """The SSRF escape hatch must be labelled in the file users copy."""
    spec = next(s for s in credentials.SETTINGS_SPECS if s.name == "SRWS_ALLOW_PRIVATE_NETWORKS")
    assert "DANGEROUS" in spec.description
    assert "SRWS_ALLOW_PRIVATE_NETWORKS" in ENV_EXAMPLE.read_text(encoding="utf-8")


# ---------------------------------------------------------------- version drift
# The version is declared in four places and stamped into every provenance
# manifest. When they disagree, a dataset claims to come from a build that never
# existed — which is the one thing a provenance record must never do.
def _pyproject_version() -> str:
    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, flags=re.MULTILINE)
    assert match, "pyproject.toml declares no version"
    return match.group(1)


def test_the_package_and_project_versions_agree():
    from scraper_app.config import APP_VERSION

    assert APP_VERSION == _pyproject_version()


def test_the_citation_file_matches_the_release():
    from scraper_app.config import APP_VERSION

    text = (ROOT / "CITATION.cff").read_text(encoding="utf-8")
    versions = set(re.findall(r"^\s*version:\s*(\S+)", text, flags=re.MULTILINE))
    assert versions == {APP_VERSION}, f"CITATION.cff says {versions}, code says {APP_VERSION}"


def test_the_changelog_documents_this_release():
    """A version bump without an entry tells a user nothing about what changed."""
    from scraper_app.config import APP_VERSION

    changelog = ROOT / "CHANGELOG.md"
    assert changelog.exists(), "CHANGELOG.md is missing"
    assert re.search(
        rf"^##\s+{re.escape(APP_VERSION)}\b", changelog.read_text(encoding="utf-8"), re.MULTILINE
    ), f"CHANGELOG.md has no section for {APP_VERSION}"


def test_the_readme_cites_the_current_version():
    from scraper_app.config import APP_VERSION

    text = (ROOT / "README.md").read_text(encoding="utf-8")
    cited = set(re.findall(r"\(Version ([0-9][^)]*)\)", text))
    assert cited in ({APP_VERSION}, set()), f"README cites {cited}, code says {APP_VERSION}"


def test_the_user_agent_carries_the_version():
    """Site owners identify this tool by its user agent; it must be truthful."""
    from scraper_app.config import APP_VERSION, SETTINGS

    assert APP_VERSION in SETTINGS.user_agent

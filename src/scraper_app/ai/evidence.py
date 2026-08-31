"""Per-value evidence checking (audit v0.2 section 11).

The README promises that a value a model proposes must appear in the page. A
ratio over the whole proposal does not deliver that: it lets a minority of
unsupported values through, which in a research dataset is exactly the failure
that matters.

This module checks **each value on its own** and is type-aware, because the
same number is written many ways:

    9.3%   0.093   9,3 %   9.3 percent

A value that cannot be supported is not silently kept. The caller either drops
the record, blanks the cell, or rejects the whole proposal — but it always
knows which cells were unsupported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_WS = re.compile(r"\s+")
_NUMBER = re.compile(r"[-+]?\d[\d\s.,]*")


@dataclass
class CellEvidence:
    """Whether one proposed value is supported by the page it came from."""

    value: str
    supported: bool
    how: str = ""  # exact | normalized | numeric | none

    @property
    def unsupported(self) -> bool:
        return not self.supported


@dataclass
class EvidenceReport:
    """The verdict for a whole proposal."""

    cells: list[CellEvidence] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.cells)

    @property
    def supported(self) -> int:
        return sum(1 for cell in self.cells if cell.supported)

    @property
    def unsupported_values(self) -> list[str]:
        return [cell.value for cell in self.cells if cell.unsupported]

    @property
    def ratio(self) -> float:
        return self.supported / self.total if self.total else 0.0

    @property
    def fully_supported(self) -> bool:
        """True only when every checked value was found in the page."""
        return self.total > 0 and self.supported == self.total


def normalize_text(value: str) -> str:
    return _WS.sub(" ", str(value or "")).strip().lower()


def numeric_forms(value: str) -> set[str]:
    """Every plausible written form of a number, for comparison.

    ``9.3%`` also matches ``0.093`` and ``9,3``; ``1,234.5`` also matches
    ``1234.5``. This is what makes the check type-aware rather than a plain
    substring test.
    """
    text = normalize_text(value)
    match = _NUMBER.search(text)
    if not match:
        return set()

    raw = match.group(0).replace(" ", "")
    candidates = {raw}

    # Thousands/decimal separator variants.
    plain = raw.replace(",", "")
    candidates.add(plain)
    candidates.add(raw.replace(".", "").replace(",", "."))
    comma_decimal = raw.replace(".", ",")
    candidates.add(comma_decimal)

    try:
        number = float(
            plain if plain.count(".") <= 1 else plain.replace(".", "", plain.count(".") - 1)
        )
    except ValueError:
        return {c for c in candidates if c}

    # Percentage <-> fraction.
    formatted = {
        f"{number:g}",
        f"{number * 100:g}",
        f"{number / 100:g}",
    }
    candidates |= formatted
    candidates |= {c.replace(".", ",") for c in formatted}
    return {c for c in candidates if c}


def check_value(
    value: object, haystack: str, haystack_numbers: set[str] | None = None
) -> CellEvidence:
    """Decide whether one value is supported by the page text."""
    text = str(value).strip() if value is not None else ""
    if not text:
        # An empty value asserts nothing, so it needs no support.
        return CellEvidence(value=text, supported=True, how="empty")

    normalized = normalize_text(text)
    if normalized and normalized in haystack:
        return CellEvidence(value=text, supported=True, how="exact")

    # Drop punctuation/symbols that formatting adds but meaning does not.
    stripped = re.sub(r"[^0-9a-z؀-ۿ ]+", "", normalized).strip()
    if stripped and stripped in haystack:
        return CellEvidence(value=text, supported=True, how="normalized")

    forms = numeric_forms(text)
    if forms:
        numbers = haystack_numbers if haystack_numbers is not None else set()
        if forms & numbers:
            return CellEvidence(value=text, supported=True, how="numeric")
        if any(form and form in haystack for form in forms):
            return CellEvidence(value=text, supported=True, how="numeric")

    return CellEvidence(value=text, supported=False, how="none")


def page_numbers(page_content: str) -> set[str]:
    """Every numeric form present in the page, for fast numeric comparison."""
    text = normalize_text(page_content)
    found: set[str] = set()
    for match in _NUMBER.finditer(text):
        found |= numeric_forms(match.group(0))
    return found


def check_values(values: list[object], page_content: str) -> EvidenceReport:
    """Check a list of proposed values against the page they came from."""
    haystack = normalize_text(page_content)
    numbers = page_numbers(page_content)
    return EvidenceReport(cells=[check_value(value, haystack, numbers) for value in values])


def check_records(
    records: list[dict[str, object]], page_content: str
) -> tuple[EvidenceReport, list[dict[str, object]]]:
    """Check every cell of every record.

    Returns the report plus the records with unsupported cells blanked, so a
    caller can keep a row whose other columns are sound while never presenting
    an unsupported value as data.
    """
    haystack = normalize_text(page_content)
    numbers = page_numbers(page_content)

    cells: list[CellEvidence] = []
    cleaned: list[dict[str, object]] = []
    for record in records:
        row: dict[str, object] = {}
        for key, value in record.items():
            evidence = check_value(value, haystack, numbers)
            cells.append(evidence)
            row[key] = value if evidence.supported else None
        cleaned.append(row)

    return EvidenceReport(cells=cells), cleaned

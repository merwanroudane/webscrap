"""Document extractors (audit section Q).

PyMuPDF stays the light path for ordinary PDFs. Docling is the optional heavy
path for complex layouts. Both are local: a document never leaves the machine.

Docling is not required for simple PDFs, and PyMuPDF is not required at all —
without either, the document route reports the limitation instead of failing.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass, field
from typing import Any

from .base import BaseProvider, ProviderCategory, ProviderDescriptor


@dataclass
class DocumentPage:
    number: int
    text: str = ""
    tables: list[list[list[str]]] = field(default_factory=list)


@dataclass
class DocumentResult:
    """Normalized document content with page-level provenance."""

    url: str
    pages: list[DocumentPage] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    extractor: str = ""

    @property
    def table_count(self) -> int:
        return sum(len(page.tables) for page in self.pages)

    def to_records(self) -> list[dict[str, Any]]:
        """Tables become rows when present; otherwise one row per page."""
        records: list[dict[str, Any]] = []
        for page in self.pages:
            if page.tables:
                for table_index, table in enumerate(page.tables, start=1):
                    if len(table) < 2:
                        continue
                    header = [str(cell or f"column_{i}") for i, cell in enumerate(table[0])]
                    for row in table[1:]:
                        record = {
                            header[i] if i < len(header) else f"column_{i}": (cell or "")
                            for i, cell in enumerate(row)
                        }
                        record["_page"] = page.number
                        record["_table"] = table_index
                        records.append(record)
            elif page.text.strip():
                records.append({"page": page.number, "text": page.text.strip()})
        return records


class DocumentExtractor(BaseProvider):
    """Turn document bytes into pages, text and tables."""

    @abstractmethod
    def extract(
        self, payload: bytes, *, url: str = "", max_pages: int | None = None
    ) -> DocumentResult: ...

    def describe(self) -> dict[str, Any]:
        return self.descriptor.as_row()


class PyMuPDFExtractor(DocumentExtractor):
    """Light, fast, local. The default for PDFs."""

    descriptor = ProviderDescriptor(
        id="pymupdf",
        label="PyMuPDF",
        category=ProviderCategory.DOCUMENT,
        cost_mode="local_compute",
        local=True,
        package="fitz",
        install_hint="pip install pymupdf",
        docs="https://github.com/pymupdf/PyMuPDF",
        privacy_note="The document is parsed on your machine.",
        capabilities=("documents",),
        notes="AGPL-3.0 — optional by design, see THIRD_PARTY_LICENSES.md.",
    )

    def extract(
        self, payload: bytes, *, url: str = "", max_pages: int | None = None
    ) -> DocumentResult:
        self._require_ready()
        import fitz  # type: ignore

        pages: list[DocumentPage] = []
        with fitz.open(stream=payload, filetype="pdf") as document:
            limit = min(max_pages or document.page_count, document.page_count)
            for index in range(limit):
                page = document.load_page(index)
                tables: list[list[list[str]]] = []
                try:
                    finder = page.find_tables()
                    tables = [table.extract() for table in finder.tables]
                except Exception:
                    tables = []
                pages.append(
                    DocumentPage(number=index + 1, text=page.get_text("text") or "", tables=tables)
                )
            metadata = dict(document.metadata or {})
        return DocumentResult(url=url, pages=pages, metadata=metadata, extractor="pymupdf")


class DoclingExtractor(DocumentExtractor):
    """Heavier, layout-aware, local. Optional; better on complex documents."""

    descriptor = ProviderDescriptor(
        id="docling",
        label="Docling",
        category=ProviderCategory.DOCUMENT,
        cost_mode="local_compute",
        local=True,
        package="docling",
        install_hint="pip install docling",
        docs="https://github.com/docling-project/docling",
        privacy_note="The document is parsed on your machine.",
        capabilities=("documents", "structured_output"),
        notes="Large download; only worth installing for complex layouts.",
    )

    def extract(
        self, payload: bytes, *, url: str = "", max_pages: int | None = None
    ) -> DocumentResult:
        self._require_ready()
        import tempfile
        from pathlib import Path

        from docling.document_converter import DocumentConverter  # type: ignore

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "document.pdf"
            path.write_bytes(payload)
            converter = DocumentConverter()
            converted = converter.convert(str(path))

        document = converted.document
        return self._to_pages(document, url=url, max_pages=max_pages)

    @staticmethod
    def _page_of(item: Any) -> int:
        """The page an item sits on, from Docling's own provenance."""
        for prov in getattr(item, "prov", []) or []:
            try:
                return int(getattr(prov, "page_no", 1) or 1)
            except (TypeError, ValueError):
                break
        return 1

    def _to_pages(self, document: Any, *, url: str, max_pages: int | None) -> DocumentResult:
        """Split a converted document into real pages (audit v0.2 sections 40-41).

        The first version put the whole document's Markdown on page 1 and
        attributed every word of a 200-page PDF to that page. For a research
        tool that is worse than no page number at all, so text is now placed on
        the page Docling itself recorded for it, and ``max_pages`` is applied to
        those pages rather than to the serialized output.
        """
        tables_by_page: dict[int, list[list[list[str]]]] = {}
        for table in getattr(document, "tables", []) or []:
            try:
                frame = table.export_to_dataframe()
                grid = [[str(c) for c in frame.columns]] + frame.astype(str).values.tolist()
            except Exception:
                continue
            tables_by_page.setdefault(self._page_of(table), []).append(grid)

        text_by_page: dict[int, list[str]] = {}
        for item in getattr(document, "texts", []) or []:
            content = str(getattr(item, "text", "") or "").strip()
            if content:
                text_by_page.setdefault(self._page_of(item), []).append(content)

        metadata: dict[str, Any] = {"converter": "docling"}

        if not text_by_page:
            # No per-item provenance available. Fall back to the whole-document
            # Markdown, but say so rather than implying it all came from page 1.
            try:
                markdown = document.export_to_markdown()
            except Exception:
                markdown = ""
            if markdown.strip():
                text_by_page[1] = [markdown]
                metadata["page_attribution"] = (
                    "whole document (Docling reported no per-item page provenance)"
                )

        numbers = sorted(set(tables_by_page) | set(text_by_page))
        if max_pages:
            # "First N pages of the document", matching the PyMuPDF path, rather
            # than "first N pages that happen to contain something".
            numbers = [number for number in numbers if number <= max_pages]
            metadata["pages_limited_to"] = max_pages

        pages = [
            DocumentPage(
                number=number,
                text="\n\n".join(text_by_page.get(number, [])),
                tables=tables_by_page.get(number, []),
            )
            for number in numbers
        ]

        return DocumentResult(url=url, pages=pages, metadata=metadata, extractor="docling")


PROVIDERS: dict[str, type[DocumentExtractor]] = {
    "pymupdf": PyMuPDFExtractor,
    "docling": DoclingExtractor,
}


def providers() -> list[DocumentExtractor]:
    return [cls() for cls in PROVIDERS.values()]


def get_provider(name: str) -> DocumentExtractor | None:
    cls = PROVIDERS.get(name)
    return cls() if cls else None


def best_extractor(prefer: str | None = None) -> DocumentExtractor | None:
    """PyMuPDF unless Docling is explicitly preferred; ``None`` if neither exists."""
    if prefer:
        chosen = get_provider(prefer)
        if chosen and chosen.available():
            return chosen
    for name in ("pymupdf", "docling"):
        provider = get_provider(name)
        if provider and provider.available():
            return provider
    return None

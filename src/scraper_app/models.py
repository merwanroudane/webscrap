"""Pydantic models shared across the application (spec section 55).

Large datasets are never carried inside these models: ``ExtractionResult``
holds metadata plus a bounded record list, while the full table lives in a
pandas/Arrow artifact managed by :mod:`scraper_app.storage.run_store`.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["auto", "guided", "advanced"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class Confidence(str, Enum):
    """Human-readable confidence bands (spec section 61: no fake decimals)."""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"

    @classmethod
    def from_score(cls, score: float) -> Confidence:
        if score >= 0.8:
            return cls.HIGH
        if score >= 0.55:
            return cls.MEDIUM
        return cls.LOW

    def label(self, lang: str = "en") -> str:
        en = {
            "high": "High confidence",
            "medium": "Medium confidence",
            "low": "Low confidence — review recommended",
        }
        ar = {
            "high": "ثقة عالية",
            "medium": "ثقة متوسطة",
            "low": "ثقة منخفضة — يُنصح بالمراجعة",
        }
        return (ar if lang == "ar" else en)[self.value]

    def symbol(self) -> str:
        return {"high": "●●●", "medium": "●●○", "low": "●○○"}[self.value]


class NameSource(str, Enum):
    SOURCE_NATIVE = "source_native"
    HEURISTIC = "heuristic"
    USER_DEFINED = "user_defined"
    AI_INFERRED = "ai_inferred"


class FieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    label: str | None = None
    dtype: str | None = None
    required: bool = False
    selector: str | None = None
    attribute: str | None = None
    source_path: str | None = None
    name_source: NameSource = NameSource.SOURCE_NATIVE
    confidence: Confidence = Confidence.MEDIUM
    sample: str | None = None
    notes: str | None = None


class ExtractionSchema(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = "dataset"
    fields: list[FieldSpec] = Field(default_factory=list)

    def field_names(self) -> list[str]:
        return [f.name for f in self.fields]

    def required_names(self) -> list[str]:
        return [f.name for f in self.fields if f.required]


class PaginationType(str, Enum):
    NONE = "none"
    PAGE_NUMBER = "page_number"
    OFFSET_LIMIT = "offset_limit"
    CURSOR = "cursor"
    NEXT_LINK = "next_link"
    NEXT_BUTTON = "next_button"
    LOAD_MORE = "load_more"
    INFINITE_SCROLL = "infinite_scroll"


class PaginationPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: PaginationType = PaginationType.NONE
    param: str | None = None
    start: int = 1
    step: int = 1
    url_template: str | None = None
    next_selector: str | None = None
    cursor_path: str | None = None
    max_pages: int = 1
    stop_when_empty: bool = True
    detected_from: str | None = None
    confidence: Confidence = Confidence.MEDIUM


class CrawlPlan(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    scope: Literal["single", "template", "section", "domain"] = "single"
    max_pages: int = 20
    max_depth: int = 1
    same_domain_only: bool = True
    include_patterns: list[str] = Field(default_factory=list)
    exclude_patterns: list[str] = Field(default_factory=list)
    use_sitemap: bool = False


class RequestOptions(BaseModel):
    """Advanced-mode HTTP options. Secrets are never persisted from here."""

    model_config = ConfigDict(extra="forbid")

    method: Literal["GET", "POST"] = "GET"
    params: dict[str, str] = Field(default_factory=dict)
    body: str | None = None
    headers: dict[str, str] = Field(default_factory=dict)
    cookies: dict[str, str] = Field(default_factory=dict)
    timeout: float | None = None
    requests_per_second: float | None = None
    max_retries: int | None = None


class ExtractionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str
    mode: Mode = "auto"
    user_goal: str | None = None
    preset: str = "auto"
    max_pages: int = 50
    max_rows: int | None = None
    same_domain_only: bool = True
    respect_robots: bool = True
    allow_browser: bool = True
    allow_ai: bool = False
    ai_mode: Literal["disabled", "auto", "always"] = "auto"
    ai_provider: str | None = None
    allow_cloud: bool = False
    allow_agentic: bool = False
    engine_preference: str | None = None
    selector: str | None = None
    xpath: str | None = None
    records_path: str | None = None
    wait_for: str | None = None
    options: RequestOptions = Field(default_factory=RequestOptions)
    pagination: PaginationPlan = Field(default_factory=PaginationPlan)
    crawl: CrawlPlan = Field(default_factory=CrawlPlan)
    add_provenance_columns: bool = True

    def fingerprint(self) -> str:
        payload = self.model_dump_json(exclude={"options"})
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


class ApiCandidate(BaseModel):
    """A JSON/CSV endpoint discovered from page evidence (spec section 21)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    method: str = "GET"
    content_type: str | None = None
    status: int | None = None
    sample_keys: list[str] = Field(default_factory=list)
    record_count: int | None = None
    records_path: str | None = None
    response_size: int | None = None
    originating_page: str | None = None
    query_params: dict[str, str] = Field(default_factory=dict)
    discovered_by: str = "html"
    confidence: Confidence = Confidence.MEDIUM
    score: float = 0.5


class TableCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    index: int
    rows: int
    columns: int
    column_names: list[str] = Field(default_factory=list)
    caption: str | None = None
    preceding_heading: str | None = None
    score: float = 0.5
    confidence: Confidence = Confidence.MEDIUM


class RepeatedPatternCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    selector: str
    item_count: int
    fields: list[FieldSpec] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    score: float = 0.5
    confidence: Confidence = Confidence.MEDIUM


class DatasetKind(str, Enum):
    FILE = "file"
    API = "api"
    TABLE = "table"
    REPEATED = "repeated"
    STRUCTURED = "structured"
    ARTICLE = "article"
    FEED = "feed"
    LINKS = "links"
    DOCUMENT = "document"


class CandidateDataset(BaseModel):
    """What the researcher actually chooses in the UI."""

    model_config = ConfigDict(extra="forbid")

    id: str
    kind: DatasetKind
    title: str
    description: str = ""
    engine: str
    rows_estimate: int | None = None
    columns: list[str] = Field(default_factory=list)
    sample_rows: list[dict[str, Any]] = Field(default_factory=list)
    score: float = 0.5
    confidence: Confidence = Confidence.MEDIUM
    payload: dict[str, Any] = Field(default_factory=dict)
    why: str = ""


class RobotsStatus(BaseModel):
    model_config = ConfigDict(extra="forbid")

    state: Literal["allowed", "restricted", "unknown", "not_checked"] = "unknown"
    robots_url: str | None = None
    crawl_delay: float | None = None
    sitemaps: list[str] = Field(default_factory=list)
    detail: str = ""

    def symbol(self) -> str:
        return {
            "allowed": "✓",
            "restricted": "⚠",
            "unknown": "?",
            "not_checked": "–",
        }[self.state]


class SourceProfile(BaseModel):
    """Result of the source profiler (spec section 20)."""

    model_config = ConfigDict(extra="forbid")

    url: str
    final_url: str
    status_code: int | None = None
    content_type: str | None = None
    content_length: int | None = None
    is_html: bool = False
    is_json: bool = False
    is_xml: bool = False
    is_feed: bool = False
    is_file: bool = False
    file_format: str | None = None
    title: str | None = None
    has_tables: bool = False
    table_count: int = 0
    tables: list[TableCandidate] = Field(default_factory=list)
    has_json_ld: bool = False
    structured_types: list[str] = Field(default_factory=list)
    has_embedded_json: bool = False
    embedded_json_keys: list[str] = Field(default_factory=list)
    repeated_patterns: list[RepeatedPatternCandidate] = Field(default_factory=list)
    requires_js: bool = False
    js_evidence: list[str] = Field(default_factory=list)
    api_candidates: list[ApiCandidate] = Field(default_factory=list)
    pagination: PaginationPlan = Field(default_factory=PaginationPlan)
    internal_links: list[str] = Field(default_factory=list)
    internal_link_count: int = 0
    downloadable_files: list[dict[str, str]] = Field(default_factory=list)
    feeds: list[str] = Field(default_factory=list)
    sitemaps: list[str] = Field(default_factory=list)
    article_chars: int = 0
    robots: RobotsStatus = Field(default_factory=RobotsStatus)
    login_wall: bool = False
    challenge_detected: bool = False
    candidates: list[CandidateDataset] = Field(default_factory=list)
    recommended_engine: str | None = None
    difficulty: Literal["low", "medium", "high"] = "low"
    confidence: Confidence = Confidence.MEDIUM
    warnings: list[str] = Field(default_factory=list)
    profiled_at: datetime = Field(default_factory=utcnow)
    elapsed_ms: int = 0


class EngineProbe(BaseModel):
    model_config = ConfigDict(extra="forbid")

    engine: str
    available: bool = True
    good_enough: bool = False
    score: float = 0.0
    rows_estimate: int | None = None
    columns: list[str] = Field(default_factory=list)
    reason: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)


class RouteDecision(BaseModel):
    """Why a given engine was chosen — auditable, not chain-of-thought."""

    model_config = ConfigDict(extra="forbid")

    engine: str
    score: float
    rationale: str
    rationale_ar: str = ""
    steps: list[str] = Field(default_factory=list)
    alternatives: list[dict[str, Any]] = Field(default_factory=list)
    uses_ai: bool = False
    uses_cloud: bool = False
    uses_browser: bool = False


class ExtractionResult(BaseModel):
    """Unified engine contract result. ``records`` is bounded; see run_store."""

    model_config = ConfigDict(extra="forbid")

    success: bool
    engine: str
    records: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    source_urls: list[str] = Field(default_factory=list)
    pages_requested: int = 0
    pages_successful: int = 0
    rows: int = 0
    truncated: bool = False
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    error_code: str | None = None
    schema_drift: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    started_at: datetime = Field(default_factory=utcnow)
    finished_at: datetime | None = None
    elapsed_ms: int = 0


class Provenance(BaseModel):
    """Research manifest for one run (spec section 30)."""

    model_config = ConfigDict(extra="forbid")

    run_id: str
    app_version: str
    started_at: datetime
    finished_at: datetime | None = None
    source_url: str
    final_url: str
    retrieved_at: datetime
    engine: str
    engine_detail: str = ""
    route_rationale: str = ""
    pages_requested: int = 0
    pages_successful: int = 0
    rows_raw: int = 0
    rows_clean: int = 0
    columns: list[str] = Field(default_factory=list)
    field_schema: dict[str, Any] = Field(default_factory=dict)
    recipe_hash: str = ""
    robots_status: str = "unknown"
    robots_url: str | None = None
    user_agent: str = ""
    warnings: list[str] = Field(default_factory=list)
    cleaning_operations: list[dict[str, Any]] = Field(default_factory=list)
    used_ai: bool = False
    used_cloud_provider: str | None = None

    # Which external service actually produced the data (audit v0.2 section 60).
    # "engine" alone does not answer "who saw my query, and which model wrote
    # this column?", which is exactly what a methods section has to state.
    # Never credentials — only identifiers.
    provider_id: str | None = None
    provider_category: str | None = None
    ai_provider: str | None = None
    ai_model: str | None = None
    remote_browser_provider: str | None = None
    managed_fetch_provider: str | None = None


class QualityReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: int = 0
    columns: int = 0
    missing_cells: int = 0
    missing_pct: float = 0.0
    duplicate_rows: int = 0
    constant_columns: list[str] = Field(default_factory=list)
    high_cardinality_columns: list[str] = Field(default_factory=list)
    conversion_failures: dict[str, int] = Field(default_factory=dict)
    column_stats: list[dict[str, Any]] = Field(default_factory=list)
    validation_errors: list[str] = Field(default_factory=list)
    schema_drift: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    sampled: bool = False

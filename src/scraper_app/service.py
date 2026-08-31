"""Application service layer.

Keeps the Streamlit UI thin: analysis, preview, extraction, cleaning and
packaging all live here, so they are testable without a browser session.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

import pandas as pd

from .config import APP_VERSION, SETTINGS
from .data import dictionary as dictionary_module
from .data import profiler as quality_profiler
from .data import provenance as provenance_module
from .data.cleaner import CleaningOptions, CleaningResult, clean
from .discovery.profiler import profile_source
from .exceptions import ErrorCode, ScraperError
from .extraction import field_mapper
from .extraction.normalizer import add_provenance_columns, records_to_frame
from .logging_config import RunLogger, get_logger
from .models import (
    CandidateDataset,
    Confidence,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    Provenance,
    QualityReport,
    RouteDecision,
    SourceProfile,
)
from .reproducibility import code_generator, report_generator
from .reproducibility import recipe as recipe_module
from .routing import router
from .storage import run_store

PRESETS: dict[str, dict[str, Any]] = {
    "auto": {"label_en": "Auto detect", "label_ar": "اكتشاف تلقائي", "kinds": []},
    "table": {
        "label_en": "Table / statistical table",
        "label_ar": "جدول / جدول إحصائي",
        "kinds": ["table"],
    },
    "listings": {
        "label_en": "Listings / repeated cards",
        "label_ar": "قوائم / بطاقات متكررة",
        "kinds": ["repeated"],
    },
    "article": {"label_en": "Article / news", "label_ar": "مقال / أخبار", "kinds": ["article"]},
    "api": {"label_en": "API / JSON", "label_ar": "API / JSON", "kinds": ["api"]},
    "multipage": {"label_en": "Multi-page section", "label_ar": "قسم متعدد الصفحات", "kinds": []},
    "document": {
        "label_en": "PDF / report / document",
        "label_ar": "PDF / تقرير / مستند",
        "kinds": ["document"],
    },
    "research": {
        "label_en": "Economic / research data",
        "label_ar": "بيانات اقتصادية / بحثية",
        "kinds": ["api", "table", "file"],
    },
}


@dataclass
class AnalysisOutcome:
    profile: SourceProfile
    logger: RunLogger
    run_id: str
    schema: ExtractionSchema | None = None


@dataclass
class ExtractionOutcome:
    run_id: str
    request: ExtractionRequest
    candidate: CandidateDataset | None
    result: ExtractionResult
    decision: RouteDecision
    raw_df: pd.DataFrame
    clean_df: pd.DataFrame
    quality: QualityReport
    schema: ExtractionSchema | None
    mapping: field_mapper.MappingReport | None
    provenance: Provenance
    recipe: dict[str, Any]
    recipe_hash: str
    script: str
    dictionary: pd.DataFrame
    logger: RunLogger
    cleaning: CleaningResult | None = None
    warnings: list[str] = field(default_factory=list)
    preview: bool = False


def analyze(
    url: str,
    *,
    user_goal: str | None = None,
    respect_robots: bool = True,
    use_browser: bool | None = None,
    preset: str = "auto",
    allow_ai: bool = False,
    ai_provider: str | None = None,
) -> AnalysisOutcome:
    """Step 1-2: guard, profile and propose candidate datasets."""
    run_id = run_store.new_run_id()
    logger = get_logger(run_id)
    logger.log("service", "analysis_started", url=url, preset=preset)

    profile = profile_source(
        url,
        respect_robots=respect_robots,
        use_browser=use_browser,
        logger=logger,
    )

    if preset != "auto":
        preferred = set(PRESETS.get(preset, {}).get("kinds", []))
        if preferred:
            profile.candidates.sort(
                key=lambda c: (c.kind.value in preferred, c.score), reverse=True
            )

    schema: ExtractionSchema | None = None
    if user_goal and user_goal.strip():
        from .extraction.schema_builder import parse_request

        schema = parse_request(user_goal)
        if schema.fields:
            logger.log("service", "schema_parsed", fields=len(schema.fields))

    # Deterministic parsing first. AI only fills a gap it could not close, and
    # only when the researcher enabled it.
    if allow_ai and (schema is None or not schema.fields):
        from .ai import service as ai_service

        provider = ai_service.get_provider(ai_provider)
        if provider is not None:
            sample = "\n".join(
                str(row)
                for candidate in profile.candidates[:2]
                for row in candidate.sample_rows[:5]
            )
            proposed = ai_service.propose_schema(
                user_goal=user_goal or "",
                page_content=sample or (profile.title or ""),
                provider_name=ai_provider,
            )
            if proposed and proposed.fields:
                schema = proposed
                logger.log(
                    "service",
                    "schema_proposed_by_ai",
                    provider=provider.name,
                    fields=len(proposed.fields),
                )

    if not profile.candidates:
        raise ScraperError(
            ErrorCode.NO_DATA_DETECTED,
            "The page was reachable but no dataset candidate was recognised.",
            {"final_url": profile.final_url},
        )

    return AnalysisOutcome(profile=profile, logger=logger, run_id=run_id, schema=schema)


def preflight(
    request: ExtractionRequest,
    candidate: CandidateDataset | None,
    profile: SourceProfile | None,
) -> dict[str, Any]:
    """Readable pre-run summary (spec section 106.5)."""
    engine, decision = router.choose_engine(request, candidate, profile)
    pages = max(1, min(request.max_pages, SETTINGS.limits.hard_max_pages))
    if request.pagination.type.value == "none" and not request.crawl.enabled:
        pages = 1
    from .ai import service as ai_service
    from .providers import registry as provider_registry

    configured = provider_registry.configured_summary()
    ai_provider = ai_service.get_provider(request.ai_provider) if request.allow_ai else None

    # An AI call is only *possible* when the engine can use one and AI is on.
    ai_capable = engine.name in {"crawl4ai", "scrapegraph", "agentql"} or not engine.deterministic
    estimated_ai_calls = 1 if (ai_provider is not None and ai_capable) else 0

    remote = configured.get("remote_browser") if decision.uses_browser else None
    cloud_provider = "None"
    if decision.uses_cloud:
        cloud_provider = engine.label
    elif remote:
        cloud_provider = f"{remote} (remote browser)"

    privacy = "Everything stays on this machine."
    if decision.uses_cloud:
        privacy = f"Page content is sent to {engine.label}."
    elif estimated_ai_calls:
        privacy = f"A bounded page excerpt is sent to {ai_provider.label}."
    elif remote:
        privacy = f"Pages are loaded by {remote}, not on this machine."

    return {
        "detected_source": candidate.title if candidate else "Unknown",
        "selected_method": engine.label,
        "engine": engine.name,
        "why": decision.rationale,
        "why_ar": decision.rationale_ar,
        "estimated_pages": pages,
        "estimated_requests": pages + (1 if request.respect_robots else 0),
        "page_limit": request.max_pages,
        "preview_rows": min(SETTINGS.limits.max_preview_rows, candidate.rows_estimate or 100)
        if candidate
        else 100,
        "ai_calls": estimated_ai_calls,
        "ai_provider": ai_provider.label if ai_provider else "None",
        "cloud_provider": cloud_provider,
        "remote_browser": remote or "None",
        "uses_browser": decision.uses_browser,
        "uses_agentic": engine.name in {"stagehand", "browser_use", "skyvern"},
        "cost_mode": engine.cost_mode,
        "privacy_note": privacy,
        "robots_status": profile.robots.state if profile else "not_checked",
        "local_only_available": engine.cost_mode != "metered",
    }


def extract(
    request: ExtractionRequest,
    candidate: CandidateDataset | None,
    *,
    profile: SourceProfile | None = None,
    schema: ExtractionSchema | None = None,
    logger: RunLogger | None = None,
    run_id: str | None = None,
    progress: Callable[[int, int, str], None] | None = None,
    preview: bool = False,
    preview_pages: int = 1,
) -> ExtractionOutcome:
    """Steps 4-5: run the route, build the dataset and every research artifact."""
    run_id = run_id or run_store.new_run_id()
    logger = logger or get_logger(run_id)
    started_at = datetime.now(UTC)

    execution = router.execute(
        request,
        candidate,
        profile,
        schema,
        logger=logger,
        progress=progress,
        limit_pages=preview_pages if preview else None,
    )
    result = execution.result
    decision = execution.decision

    raw_df = records_to_frame(result.records, result.columns)
    if request.add_provenance_columns:
        raw_df = add_provenance_columns(
            raw_df, source_url=request.url, method=result.engine, retrieved_at=result.started_at
        )

    mapping: field_mapper.MappingReport | None = None
    working = raw_df
    ai_usage: dict[str, Any] = {}
    if schema and schema.fields:
        mapping = field_mapper.map_schema(schema, [str(c) for c in raw_df.columns], raw_df)

        # Deterministic mapping first; a model is asked only about what is left.
        if mapping.unmatched and request.allow_ai:
            from .ai import service as ai_service

            usage_log = ai_service.AIUsageLog()
            proposed = ai_service.map_fields(
                requested=mapping.unmatched,
                columns=[str(c) for c in raw_df.columns],
                sample_rows=raw_df.head(3).astype(str).to_dict(orient="records"),
                provider_name=request.ai_provider,
                usage_log=usage_log,
            )
            if proposed:
                for item in mapping.mappings:
                    column = proposed.get(item.requested)
                    if item.matched_column is None and column:
                        item.matched_column = column
                        item.method = "ai_semantic"
                        item.confidence = Confidence.LOW
                mapping.unmatched = [m.requested for m in mapping.mappings if not m.matched_column]
                ai_usage = usage_log.as_dict()
                logger.log("service", "ai_field_mapping_used", mapped=len(proposed))

        if any(m.matched_column for m in mapping.mappings):
            working = field_mapper.apply_mapping(raw_df, mapping)

    quality = quality_profiler.profile(working, schema_drift=result.schema_drift)

    recipe = recipe_module.build(
        name=(candidate.title if candidate else "dataset")[:60],
        request=request,
        candidate=candidate,
        result=result,
        decision=decision,
        schema=schema,
    )
    recipe_hash = recipe_module.recipe_hash(recipe)

    provenance = provenance_module.build(
        run_id=run_id,
        request_url=request.url,
        profile=profile,
        result=result,
        decision=decision,
        schema=schema,
        rows_clean=len(working),
        recipe_hash=recipe_hash,
        started_at=started_at,
    )

    script = code_generator.generate(
        engine=result.engine,
        url=request.url,
        recipe=recipe,
        columns=[str(c) for c in working.columns],
        version=APP_VERSION,
        created=started_at.strftime("%Y-%m-%d %H:%M UTC"),
    )

    data_dictionary = dictionary_module.build(
        working, schema=schema, source_url=request.url, engine=result.engine
    )

    if ai_usage:
        result.metadata.setdefault("ai_usage", ai_usage)

    warnings = list(result.warnings)
    if mapping and mapping.unmatched:
        warnings.append(
            "These requested fields were not found and were left out: "
            + ", ".join(mapping.unmatched)
        )
    if result.schema_drift:
        warnings.extend(result.schema_drift)

    logger.log(
        "service",
        "extraction_complete",
        engine=result.engine,
        rows=len(working),
        pages=result.pages_successful,
        preview=preview,
    )

    return ExtractionOutcome(
        run_id=run_id,
        request=request,
        candidate=candidate,
        result=result,
        decision=decision,
        raw_df=raw_df,
        clean_df=working,
        quality=quality,
        schema=schema,
        mapping=mapping,
        provenance=provenance,
        recipe=recipe,
        recipe_hash=recipe_hash,
        script=script,
        dictionary=data_dictionary,
        logger=logger,
        warnings=warnings,
        preview=preview,
    )


def apply_cleaning(outcome: ExtractionOutcome, options: CleaningOptions) -> ExtractionOutcome:
    """Re-run cleaning from the raw frame so every operation stays reversible."""
    base = outcome.raw_df
    if outcome.mapping and any(m.matched_column for m in outcome.mapping.mappings):
        base = field_mapper.apply_mapping(base, outcome.mapping)

    cleaning = clean(base, options)
    outcome.clean_df = cleaning.frame
    outcome.cleaning = cleaning
    outcome.quality = quality_profiler.profile(
        cleaning.frame,
        conversion_failures=cleaning.conversion_failures,
        schema_drift=outcome.result.schema_drift,
    )
    outcome.dictionary = dictionary_module.build(
        cleaning.frame,
        schema=outcome.schema,
        source_url=outcome.request.url,
        engine=outcome.result.engine,
    )
    outcome.provenance = outcome.provenance.model_copy(
        update={
            "rows_clean": len(cleaning.frame),
            "cleaning_operations": [op.as_dict() for op in cleaning.operations],
        }
    )
    outcome.recipe["cleaning"] = [op.as_dict() for op in cleaning.operations]
    outcome.recipe_hash = recipe_module.recipe_hash(outcome.recipe)
    outcome.warnings = [*outcome.result.warnings, *cleaning.warnings]
    return outcome


def reset_cleaning(outcome: ExtractionOutcome) -> ExtractionOutcome:
    """Return to the exact extracted data."""
    base = outcome.raw_df
    if outcome.mapping and any(m.matched_column for m in outcome.mapping.mappings):
        base = field_mapper.apply_mapping(base, outcome.mapping)
    outcome.clean_df = base
    outcome.cleaning = None
    outcome.quality = quality_profiler.profile(base, schema_drift=outcome.result.schema_drift)
    outcome.recipe["cleaning"] = []
    outcome.provenance = outcome.provenance.model_copy(
        update={"rows_clean": len(base), "cleaning_operations": []}
    )
    return outcome


def persist(outcome: ExtractionOutcome, include_raw: bool = True) -> run_store.RunRecord:
    """Write the run artifacts to disk and return its history record."""
    run_store.save_frame(outcome.run_id, outcome.clean_df, "dataset")
    if include_raw:
        run_store.save_frame(outcome.run_id, outcome.raw_df, "dataset_raw")
    run_store.save_artifact(
        outcome.run_id, "extraction_recipe.json", recipe_module.to_json_bytes(outcome.recipe)
    )
    run_store.save_artifact(
        outcome.run_id, "extraction_recipe.yaml", recipe_module.to_yaml_bytes(outcome.recipe)
    )
    run_store.save_artifact(outcome.run_id, "generated_scraper.py", outcome.script)
    run_store.save_artifact(
        outcome.run_id, "provenance.json", provenance_module.to_json_bytes(outcome.provenance)
    )
    run_store.save_artifact(
        outcome.run_id, "data_dictionary.csv", dictionary_module.to_csv_bytes(outcome.dictionary)
    )

    record = run_store.RunRecord(
        run_id=outcome.run_id,
        created_at=outcome.provenance.started_at.isoformat(),
        source_url=outcome.provenance.source_url,
        engine=outcome.result.engine,
        rows=len(outcome.clean_df),
        columns=int(outcome.clean_df.shape[1]),
        title=(outcome.candidate.title if outcome.candidate else "dataset")[:80],
        recipe_hash=outcome.recipe_hash,
        has_data=True,
    )
    run_store.save_manifest(record)
    return record


def build_bundle(outcome: ExtractionOutcome, include_raw: bool = True) -> bytes:
    return report_generator.build_bundle(
        clean_df=outcome.clean_df,
        raw_df=outcome.raw_df if include_raw else None,
        dictionary=outcome.dictionary,
        provenance=outcome.provenance,
        recipe=outcome.recipe,
        recipe_yaml=recipe_module.to_yaml_bytes(outcome.recipe),
        script=outcome.script,
        quality=outcome.quality,
        include_raw=include_raw,
    )


def rerun_recipe(payload: bytes | str, **overrides: Any) -> ExtractionOutcome:
    """Re-run a saved recipe end to end."""
    recipe = recipe_module.from_json(payload)
    request = recipe_module.to_request(recipe)
    candidate = recipe_module.to_candidate(recipe)
    for key, value in overrides.items():
        if hasattr(request, key) and value is not None:
            setattr(request, key, value)
    return extract(request, candidate)

"""Route selection and execution (spec sections 58, 60).

The router picks the cheapest reliable engine for a candidate dataset, records
an auditable rationale, and falls back down a documented chain when the first
choice fails. It never escalates to a browser or a paid provider when a
deterministic engine already produced usable rows.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..engines.base import BaseEngine
from ..exceptions import ErrorCode, ScraperError
from ..logging_config import RunLogger
from ..models import (
    CandidateDataset,
    DatasetKind,
    ExtractionRequest,
    ExtractionResult,
    ExtractionSchema,
    RouteDecision,
    SourceProfile,
)
from .capability_registry import engine_instances, get_engine
from .scoring import rank_engines

#: Ordered fallbacks per candidate kind. Only engines that are available run.
FALLBACKS: dict[DatasetKind, list[str]] = {
    DatasetKind.FILE: ["direct_file"],
    DatasetKind.API: ["json_api", "playwright"],
    DatasetKind.TABLE: ["table", "playwright", "crawl4ai", "firecrawl"],
    DatasetKind.REPEATED: ["repeated_dom", "playwright", "crawl4ai", "firecrawl"],
    DatasetKind.STRUCTURED: ["structured", "playwright"],
    DatasetKind.ARTICLE: ["article", "playwright"],
    DatasetKind.FEED: ["feed"],
    DatasetKind.LINKS: ["links", "playwright"],
    DatasetKind.DOCUMENT: ["document"],
}

_RATIONALE = {
    "direct_file": (
        "The address points at a published data file, so it is downloaded and parsed directly.",
        "العنوان يشير إلى ملف بيانات منشور، لذلك يتم تنزيله وقراءته مباشرة.",
    ),
    "json_api": (
        "The page data is available as a structured JSON response, which is faster and more "
        "reproducible than scraping the rendered page.",
        "بيانات الصفحة متاحة كاستجابة JSON منظمة، وهي أسرع وأسهل في إعادة الإنتاج من كشط الصفحة المعروضة.",
    ),
    "table": (
        "The values are inside an HTML table, which pandas can read deterministically — "
        "no browser and no AI needed.",
        "القيم داخل جدول HTML يمكن قراءته بشكل حتمي عبر pandas — بدون متصفح وبدون ذكاء اصطناعي.",
    ),
    "repeated_dom": (
        "The page repeats the same block structure, so each block is read as one row using "
        "deterministic selectors.",
        "الصفحة تكرر نفس بنية الكتلة، لذلك تُقرأ كل كتلة كصف واحد باستخدام محددات حتمية.",
    ),
    "structured": (
        "The publisher embeds machine-readable metadata (JSON-LD/microdata), which is read directly.",
        "الناشر يضمّن بيانات وصفية قابلة للقراءة آليًا (JSON-LD/microdata) وتُقرأ مباشرة.",
    ),
    "feed": (
        "The site publishes an RSS/Atom feed, which is more stable than scraping HTML.",
        "الموقع ينشر تغذية RSS/Atom، وهي أكثر ثباتًا من كشط HTML.",
    ),
    "article": (
        "The page reads as an article, so title, author, date and body text are extracted as one record.",
        "الصفحة تُقرأ كمقال، لذلك يتم استخراج العنوان والكاتب والتاريخ والنص كسجل واحد.",
    ),
    "links": (
        "The requested dataset is the list of links/files found on the page.",
        "مجموعة البيانات المطلوبة هي قائمة الروابط/الملفات الموجودة في الصفحة.",
    ),
    "document": (
        "The address resolves to a PDF, so a document parser is used instead of HTML scraping.",
        "العنوان يؤدي إلى ملف PDF، لذلك يُستخدم محلل مستندات بدل كشط HTML.",
    ),
    "playwright": (
        "The requested values are not present in the initial HTML and only appear after JavaScript "
        "rendering, so a local browser is used.",
        "القيم المطلوبة غير موجودة في HTML الأولي وتظهر فقط بعد تنفيذ JavaScript، لذلك يُستخدم متصفح محلي.",
    ),
    "crawl4ai": (
        "Deterministic extraction did not succeed, so a local adaptive engine renders and parses the page.",
        "لم ينجح الاستخراج الحتمي، لذلك يقوم محرك محلي تكيفي بعرض الصفحة وتحليلها.",
    ),
    "firecrawl": (
        "A hosted extraction provider was selected because local methods could not read this source. "
        "Page content leaves this machine for that provider.",
        "تم اختيار مزود استخراج مستضاف لأن الطرق المحلية لم تستطع قراءة هذا المصدر. محتوى الصفحة يغادر هذا الجهاز.",
    ),
}


@dataclass
class RouteExecution:
    result: ExtractionResult
    decision: RouteDecision
    engine: BaseEngine


def build_decision(
    engine_name: str,
    score: float,
    profile: SourceProfile | None,
    candidate: CandidateDataset | None,
    alternatives: list[dict[str, object]],
    extra_steps: list[str] | None = None,
) -> RouteDecision:
    """Assemble the short, auditable explanation shown as 'Why this method?'."""
    english, arabic = _RATIONALE.get(engine_name, ("Selected by the routing heuristic.", ""))
    engine = get_engine(engine_name)

    steps: list[str] = list(extra_steps or [])
    if profile is not None:
        steps.insert(0, f"Static HTTP response checked ({profile.content_type or 'unknown type'}).")
        if profile.api_candidates:
            steps.append(
                f"{len(profile.api_candidates)} structured JSON candidate(s) found "
                f"({profile.api_candidates[0].discovered_by})."
            )
        if profile.has_tables:
            steps.append(f"{profile.table_count} HTML table(s) detected.")
        if profile.repeated_patterns:
            steps.append(f"{len(profile.repeated_patterns)} repeated block group(s) detected.")
        if profile.requires_js:
            steps.append("The static HTML alone did not contain the visible data.")
        if engine_name != "playwright" and not profile.requires_js:
            steps.append("Browser rendering is not necessary.")

    return RouteDecision(
        engine=engine_name,
        score=score,
        rationale=english,
        rationale_ar=arabic,
        steps=steps,
        alternatives=alternatives[:5],
        uses_ai=bool(engine and not engine.deterministic and engine.cost_mode == "metered"),
        uses_cloud=bool(engine and engine.cost_mode == "metered"),
        uses_browser=engine_name == "playwright",
    )


def choose_engine(
    request: ExtractionRequest,
    candidate: CandidateDataset | None,
    profile: SourceProfile | None = None,
) -> tuple[BaseEngine, RouteDecision]:
    """Pick the best available engine for a candidate without running it."""
    engines = engine_instances()

    if request.engine_preference:
        preferred = engines.get(request.engine_preference)
        if preferred is not None and preferred.available():
            return preferred, build_decision(
                preferred.name,
                1.0,
                profile,
                candidate,
                [],
                ["You selected this engine explicitly in Advanced mode."],
            )

    ranked = rank_engines(engines, candidate, request)
    order = FALLBACKS.get(candidate.kind, []) if candidate else []
    ranked_names = [item.engine for item in ranked if item.score > 0 and item.available]

    chosen_name: str | None = None
    for name in order:
        if name in ranked_names:
            chosen_name = name
            break
    if chosen_name is None:
        chosen_name = ranked_names[0] if ranked_names else None
    if chosen_name is None:
        raise ScraperError(
            ErrorCode.NO_ROUTE,
            "No available engine can read this source with the current settings.",
        )

    score = next((item.score for item in ranked if item.engine == chosen_name), 0.0)
    alternatives = [item.as_dict() for item in ranked if item.engine != chosen_name][:5]
    engine = engines[chosen_name]
    return engine, build_decision(chosen_name, score, profile, candidate, alternatives)


def execute(
    request: ExtractionRequest,
    candidate: CandidateDataset | None,
    profile: SourceProfile | None = None,
    schema: ExtractionSchema | None = None,
    *,
    logger: RunLogger | None = None,
    progress=None,
    limit_pages: int | None = None,
) -> RouteExecution:
    """Run the chosen engine, falling back down the documented chain on failure."""
    engines = engine_instances()
    engine, decision = choose_engine(request, candidate, profile)

    chain: list[str] = [engine.name]
    if candidate is not None:
        for name in FALLBACKS.get(candidate.kind, []):
            if name not in chain:
                chain.append(name)

    errors: list[str] = []
    for index, name in enumerate(chain):
        current = engines.get(name)
        if current is None or not current.available():
            continue
        if current.cost_mode == "metered" and not request.allow_cloud:
            continue
        if name == "playwright" and not request.allow_browser:
            continue
        try:
            if logger:
                logger.log("router", "engine_selected", engine=name, url=request.url, attempt=index + 1)
            result = current.extract(
                request,
                candidate,
                schema,
                logger=logger,
                progress=progress,
                limit_pages=limit_pages,
            )
            if result.success and result.rows:
                if name != decision.engine:
                    decision = build_decision(
                        name,
                        decision.score,
                        profile,
                        candidate,
                        decision.alternatives,
                        [f"The first choice ({decision.engine}) did not return rows."],
                    )
                result.metadata.setdefault("fallback_chain", chain[: index + 1])
                return RouteExecution(result=result, decision=decision, engine=current)
            errors.append(f"{name}: returned no rows")
        except ScraperError as exc:
            errors.append(f"{name}: {exc.code.value}")
            if logger:
                logger.warn("router", "engine_failed", engine=name, url=request.url, code=exc.code.value)
            if exc.code in {
                ErrorCode.ROBOTS_RESTRICTED,
                ErrorCode.URL_PRIVATE_NETWORK_BLOCKED,
                ErrorCode.URL_INVALID,
                ErrorCode.CAPTCHA_OR_CHALLENGE,
                ErrorCode.LOGIN_REQUIRED,
            }:
                raise
            if index == len(chain) - 1:
                raise
        except Exception as exc:  # unexpected engine failure -> taxonomy, no traceback in UI
            errors.append(f"{name}: {exc.__class__.__name__}")
            if logger:
                logger.error("router", "engine_exception", engine=name, error=exc.__class__.__name__)
            if index == len(chain) - 1:
                raise ScraperError(
                    ErrorCode.INTERNAL, f"{name} failed ({exc.__class__.__name__})."
                ) from exc

    raise ScraperError(
        ErrorCode.NO_ROUTE,
        "Every available method was tried without success: " + "; ".join(errors[:4]),
    )

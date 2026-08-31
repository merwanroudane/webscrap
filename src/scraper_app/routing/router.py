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
    DatasetKind.API: ["json_api", "playwright", "managed_fetch"],
    DatasetKind.TABLE: [
        "table",
        "playwright",
        "scrapling",
        "crawl4ai",
        "managed_fetch",
        "firecrawl",
        "scrapegraph",
        "agentql",
    ],
    DatasetKind.REPEATED: [
        "repeated_dom",
        "playwright",
        "scrapling",
        "crawl4ai",
        "managed_fetch",
        "firecrawl",
        "scrapegraph",
        "agentql",
    ],
    DatasetKind.STRUCTURED: ["structured", "playwright", "scrapling"],
    DatasetKind.ARTICLE: ["article", "playwright", "semantic_content", "crawl4ai"],
    DatasetKind.FEED: ["feed"],
    DatasetKind.LINKS: ["links", "playwright"],
    DatasetKind.DOCUMENT: ["document"],
}

#: Engines that may only run when the researcher explicitly enabled agentic mode.
AGENTIC_ENGINES = {"stagehand", "browser_use", "skyvern"}

#: Multi-page crawls can be handed to a framework when one is installed.
CRAWLER_ENGINES = ("scrapy", "crawlee")


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
    "scrapling": (
        "Deterministic selectors did not match, so an adaptive local engine relocated the "
        "equivalent elements. Nothing left this machine.",
        "لم تتطابق المحددات الحتمية، لذلك أعاد محرك محلي تكيفي تحديد العناصر المكافئة. لم يغادر شيء هذا الجهاز.",
    ),
    "scrapy": (
        "Several pages are needed, so a crawler framework fetched them with a proper request "
        "queue and rate limiting.",
        "المطلوب عدة صفحات، لذلك جلبها إطار زحف باستخدام طابور طلبات وتحديد معدل مناسب.",
    ),
    "crawlee": (
        "Several pages are needed, so a crawler framework fetched them with a proper request "
        "queue and rate limiting.",
        "المطلوب عدة صفحات، لذلك جلبها إطار زحف باستخدام طابور طلبات وتحديد معدل مناسب.",
    ),
    "selenium": (
        "A browser was required and Selenium is the configured compatibility path.",
        "كان المتصفح مطلوبًا، وSelenium هو مسار التوافق المهيأ.",
    ),
    "scrapegraph": (
        "Local methods could not read this source, so a hosted AI extraction service was used. "
        "Page content left this machine for that provider.",
        "لم تستطع الطرق المحلية قراءة هذا المصدر، لذلك استُخدمت خدمة استخراج مستضافة بالذكاء الاصطناعي. غادر محتوى الصفحة هذا الجهاز.",
    ),
    "agentql": (
        "The requested fields were described semantically because the page has no stable "
        "selectors. The query and URL were sent to AgentQL.",
        "تم وصف الحقول المطلوبة دلاليًا لأن الصفحة لا تملك محددات ثابتة. أُرسل الاستعلام والرابط إلى AgentQL.",
    ),
    "managed_fetch": (
        "A managed fetch provider retrieved the page, then the same deterministic parsers read "
        "it. Only the fetch was outsourced.",
        "قام مزود جلب مُدار بإحضار الصفحة، ثم قرأتها نفس المحللات الحتمية. الجلب فقط هو ما تم إسناده خارجيًا.",
    ),
    "semantic_content": (
        "This page is prose rather than a table, so a content service returned clean article "
        "text and metadata.",
        "هذه الصفحة نص وليست جدولًا، لذلك أعادت خدمة محتوى نصًا نظيفًا مع بيانات وصفية.",
    ),
    "stagehand": (
        "This source needs multi-step interaction, so an agentic browser performed the steps. "
        "It never signs in or bypasses access controls.",
        "يحتاج هذا المصدر تفاعلًا متعدد الخطوات، لذلك نفذ متصفح وكيل الخطوات. لا يسجل الدخول ولا يتجاوز ضوابط الوصول.",
    ),
    "browser_use": (
        "This source needs multi-step interaction, so an agentic browser performed the steps. "
        "It never signs in or bypasses access controls.",
        "يحتاج هذا المصدر تفاعلًا متعدد الخطوات، لذلك نفذ متصفح وكيل الخطوات. لا يسجل الدخول ولا يتجاوز ضوابط الوصول.",
    ),
    "skyvern": (
        "This source needs multi-step interaction, so a hosted agent performed the steps. "
        "It never signs in or bypasses access controls.",
        "يحتاج هذا المصدر تفاعلًا متعدد الخطوات، لذلك نفذ وكيل مستضاف الخطوات. لا يسجل الدخول ولا يتجاوز ضوابط الوصول.",
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

    # A genuine multi-page job is better served by a crawler framework than by
    # repeated single fetches, when one is installed.
    wants_many_pages = (limit_pages or request.max_pages or 1) > 1 or request.crawl.enabled
    if wants_many_pages:
        for name in CRAWLER_ENGINES:
            crawler = engines.get(name)
            if crawler is not None and crawler.available() and name not in chain:
                chain.append(name)

    if candidate is not None:
        for name in FALLBACKS.get(candidate.kind, []):
            if name not in chain:
                chain.append(name)

    # Agentic engines are the documented last resort and only on request.
    if request.allow_agentic:
        for name in ("stagehand", "browser_use", "skyvern"):
            if name not in chain:
                chain.append(name)

    errors: list[str] = []
    for index, name in enumerate(chain):
        current = engines.get(name)
        if current is None or not current.available():
            continue
        if current.cost_mode == "metered" and not request.allow_cloud:
            continue
        if name in {"playwright", "selenium"} and not request.allow_browser:
            continue
        if name in AGENTIC_ENGINES and not request.allow_agentic:
            continue
        # A non-deterministic engine that would call a model needs AI enabled.
        if not current.deterministic and name in {"crawl4ai"} and not request.allow_ai:
            # Crawl4AI still runs in deterministic DOM mode; semantic mode is
            # gated inside the engine itself, so this is not a hard skip.
            pass
        try:
            if logger:
                logger.log(
                    "router", "engine_selected", engine=name, url=request.url, attempt=index + 1
                )
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
                logger.warn(
                    "router", "engine_failed", engine=name, url=request.url, code=exc.code.value
                )
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
                logger.error(
                    "router", "engine_exception", engine=name, error=exc.__class__.__name__
                )
            if index == len(chain) - 1:
                raise ScraperError(
                    ErrorCode.INTERNAL, f"{name} failed ({exc.__class__.__name__})."
                ) from exc

    raise ScraperError(
        ErrorCode.NO_ROUTE,
        "Every available method was tried without success: " + "; ".join(errors[:4]),
    )

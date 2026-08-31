"""Natural language → ExtractionSchema (spec section 25).

Deterministic first: the researcher's sentence is parsed with a bilingual
term dictionary and simple separators. An LLM is only consulted when the user
has enabled AI *and* the deterministic parse produced nothing useful — and even
then the output is validated against the Pydantic schema and shown for review
before extraction. Field names are never silently invented.
"""

from __future__ import annotations

import re
from typing import Any

from ..models import Confidence, ExtractionSchema, FieldSpec, NameSource

# Bilingual term dictionary: phrase -> (canonical name, dtype)
TERM_MAP: dict[str, tuple[str, str]] = {
    "country": ("country", "string"),
    "countries": ("country", "string"),
    "nation": ("country", "string"),
    "الدولة": ("country", "string"),
    "البلد": ("country", "string"),
    "year": ("year", "integer"),
    "السنة": ("year", "integer"),
    "date": ("date", "date"),
    "التاريخ": ("date", "date"),
    "month": ("month", "string"),
    "inflation": ("inflation", "number"),
    "inflation rate": ("inflation", "number"),
    "التضخم": ("inflation", "number"),
    "معدل التضخم": ("inflation", "number"),
    "gdp": ("gdp", "number"),
    "gross domestic product": ("gdp", "number"),
    "الناتج المحلي": ("gdp", "number"),
    "الناتج المحلي الإجمالي": ("gdp", "number"),
    "unemployment": ("unemployment", "number"),
    "unemployment rate": ("unemployment", "number"),
    "البطالة": ("unemployment", "number"),
    "معدل البطالة": ("unemployment", "number"),
    "population": ("population", "number"),
    "السكان": ("population", "number"),
    "price": ("price", "number"),
    "السعر": ("price", "number"),
    "value": ("value", "number"),
    "القيمة": ("value", "number"),
    "unit": ("unit", "string"),
    "الوحدة": ("unit", "string"),
    "source": ("source", "string"),
    "المصدر": ("source", "string"),
    "title": ("title", "string"),
    "العنوان": ("title", "string"),
    "author": ("author", "string"),
    "الكاتب": ("author", "string"),
    "link": ("link", "url"),
    "url": ("url", "url"),
    "الرابط": ("link", "url"),
    "name": ("name", "string"),
    "الاسم": ("name", "string"),
    "description": ("description", "string"),
    "الوصف": ("description", "string"),
    "category": ("category", "string"),
    "التصنيف": ("category", "string"),
    "rating": ("rating", "number"),
    "التقييم": ("rating", "number"),
    "currency": ("currency", "string"),
    "العملة": ("currency", "string"),
    "region": ("region", "string"),
    "المنطقة": ("region", "string"),
    "code": ("code", "string"),
    "الرمز": ("code", "string"),
}

_SPLIT = re.compile(r"[,،;؛\n]| and | و |&")
_LEAD = re.compile(
    r"(?i)^(please\s+)?(extract|get|collect|scrape|i\s+want|i\s+need|give\s+me|"
    r"استخرج|أريد|اريد|اجمع|أعطني|اعطني)\s*", re.UNICODE
)
_NOISE = re.compile(r"(?i)\b(the|a|an|for|each|every|all|of|from|per|كل|لكل|من)\b")


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^0-9a-zA-Z؀-ۿ]+", "_", text.strip()).strip("_").lower()
    return re.sub(r"_+", "_", cleaned)[:40]


def parse_request(text: str, dataset_name: str = "dataset") -> ExtractionSchema:
    """Turn a natural-language request into a validated schema, deterministically."""
    if not text or not text.strip():
        return ExtractionSchema(name=dataset_name, fields=[])

    body = _LEAD.sub("", text.strip())
    fields: list[FieldSpec] = []
    seen: set[str] = set()

    for chunk in _SPLIT.split(body):
        phrase = chunk.strip().strip(".").strip()
        if not phrase or len(phrase) > 80:
            continue
        lowered = phrase.lower()

        canonical: tuple[str, str] | None = TERM_MAP.get(lowered)
        if canonical is None:
            for term, mapped in TERM_MAP.items():
                if re.search(rf"(?<![\w؀-ۿ]){re.escape(term)}(?![\w؀-ۿ])", lowered):
                    canonical = mapped
                    break

        if canonical is not None:
            name, dtype = canonical
            source = NameSource.USER_DEFINED
            confidence = Confidence.HIGH
        else:
            stripped = _NOISE.sub(" ", lowered).strip()
            name = _slug(stripped)
            dtype = "string"
            source = NameSource.USER_DEFINED
            confidence = Confidence.MEDIUM
            if not name or len(name) < 2:
                continue

        if name in seen:
            continue
        seen.add(name)
        fields.append(
            FieldSpec(
                name=name,
                label=phrase[:60],
                dtype=dtype,
                required=len(fields) < 2,
                name_source=source,
                confidence=confidence,
            )
        )

    return ExtractionSchema(name=dataset_name, fields=fields)


def schema_from_columns(
    columns: list[str], name_source: NameSource = NameSource.SOURCE_NATIVE, name: str = "dataset"
) -> ExtractionSchema:
    return ExtractionSchema(
        name=name,
        fields=[
            FieldSpec(
                name=str(column),
                label=str(column),
                name_source=name_source,
                confidence=Confidence.HIGH,
            )
            for column in columns
        ],
    )


def suggest_with_llm(
    excerpt: str, user_goal: str, provider: str = "anthropic"
) -> ExtractionSchema | None:
    """Optional AI field proposal (spec section 83.1).

    Returns ``None`` when no provider is configured. The page excerpt is wrapped
    as untrusted content and no secrets are included in the prompt.
    """
    from ..config import has_credentials
    from ..security.content_safety import wrap_untrusted

    if not has_credentials(provider):
        return None

    prompt = (
        "You propose dataset field names for a research web-scraping tool.\n"
        "Return ONLY a JSON object of the form "
        '{"fields":[{"name":"snake_case","type":"string|number|integer|date|url","required":true}]}.\n'
        "Base the field names on evidence in the excerpt. Do not invent fields that are not visible.\n"
        f"Researcher request: {user_goal[:500]}\n\n"
        f"{wrap_untrusted(excerpt, 4000)}"
    )

    try:  # pragma: no cover - requires a provider key
        raw = _call_provider(provider, prompt)
        return _parse_llm_fields(raw)
    except Exception:
        return None


def _call_provider(provider: str, prompt: str) -> str:  # pragma: no cover - network
    import os

    if provider == "anthropic":
        import anthropic  # type: ignore

        client = anthropic.Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        message = client.messages.create(
            model="claude-sonnet-5",
            max_tokens=800,
            messages=[{"role": "user", "content": prompt}],
        )
        return "".join(block.text for block in message.content if hasattr(block, "text"))
    if provider == "openai":
        from openai import OpenAI  # type: ignore

        client = OpenAI(api_key=os.environ["OPENAI_API_KEY"])
        response = client.responses.create(model="gpt-4o-mini", input=prompt)
        return response.output_text
    raise RuntimeError(f"Unsupported provider {provider}")


def _parse_llm_fields(raw: str) -> ExtractionSchema | None:
    import json

    match = re.search(r"\{.*\}", raw or "", flags=re.DOTALL)
    if not match:
        return None
    try:
        payload: dict[str, Any] = json.loads(match.group(0))
    except Exception:
        return None
    fields: list[FieldSpec] = []
    for item in payload.get("fields", [])[:40]:
        name = _slug(str(item.get("name", "")))
        if not name:
            continue
        fields.append(
            FieldSpec(
                name=name,
                label=str(item.get("label") or name),
                dtype=str(item.get("type") or "string"),
                required=bool(item.get("required", False)),
                name_source=NameSource.AI_INFERRED,
                confidence=Confidence.MEDIUM,
                notes="Proposed by AI — review before use.",
            )
        )
    return ExtractionSchema(name="ai_schema", fields=fields) if fields else None

"""Typed error taxonomy (spec section 36).

Every failure surfaced to a researcher must be a ``ScraperError`` carrying a
machine code, a plain-language message and concrete recovery actions. Raw
tracebacks stay in the sanitized technical log.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class ErrorCode(str, Enum):
    URL_INVALID = "URL_INVALID"
    URL_PRIVATE_NETWORK_BLOCKED = "URL_PRIVATE_NETWORK_BLOCKED"
    ROBOTS_RESTRICTED = "ROBOTS_RESTRICTED"
    HTTP_403 = "HTTP_403"
    HTTP_404 = "HTTP_404"
    HTTP_429_RATE_LIMIT = "HTTP_429_RATE_LIMIT"
    HTTP_ERROR = "HTTP_ERROR"
    TIMEOUT = "TIMEOUT"
    SSL_ERROR = "SSL_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    CONTENT_UNSUPPORTED = "CONTENT_UNSUPPORTED"
    CONTENT_TOO_LARGE = "CONTENT_TOO_LARGE"
    NO_DATA_DETECTED = "NO_DATA_DETECTED"
    JS_REQUIRED = "JS_REQUIRED"
    LOGIN_REQUIRED = "LOGIN_REQUIRED"
    CAPTCHA_OR_CHALLENGE = "CAPTCHA_OR_CHALLENGE"
    API_AUTH_REQUIRED = "API_AUTH_REQUIRED"
    SELECTOR_NOT_FOUND = "SELECTOR_NOT_FOUND"
    PAGINATION_LOOP = "PAGINATION_LOOP"
    SCHEMA_MISMATCH = "SCHEMA_MISMATCH"
    EXPORT_FORMAT_LIMITATION = "EXPORT_FORMAT_LIMITATION"
    OPTIONAL_ENGINE_NOT_INSTALLED = "OPTIONAL_ENGINE_NOT_INSTALLED"
    API_KEY_MISSING = "API_KEY_MISSING"
    NO_ROUTE = "NO_ROUTE"
    CANCELLED = "CANCELLED"
    INTERNAL = "INTERNAL"


#: Plain-language message + recovery actions for each code, in English and Arabic.
ERROR_GUIDE: dict[ErrorCode, dict[str, object]] = {
    ErrorCode.URL_INVALID: {
        "en": "That does not look like a usable web address.",
        "ar": "هذا العنوان لا يبدو رابط ويب صالحًا.",
        "actions_en": [
            "Check the address starts with http:// or https://",
            "Paste the link again from your browser",
        ],
        "actions_ar": [
            "تأكد أن العنوان يبدأ بـ http:// أو https://",
            "انسخ الرابط مجددًا من المتصفح",
        ],
    },
    ErrorCode.URL_PRIVATE_NETWORK_BLOCKED: {
        "en": "This address points to a private or internal network, which the app never requests.",
        "ar": "هذا العنوان يشير إلى شبكة داخلية أو خاصة، والتطبيق لا يطلبها أبدًا.",
        "actions_en": [
            "Use a public website address",
            "Ask the data owner for a public URL or API",
        ],
        "actions_ar": ["استخدم عنوان موقع عام", "اطلب من صاحب البيانات رابطًا أو API عامًا"],
    },
    ErrorCode.ROBOTS_RESTRICTED: {
        "en": "The robots.txt file of this site asks automated tools not to read this path.",
        "ar": "ملف robots.txt في الموقع يطلب من الأدوات الآلية عدم قراءة هذا المسار.",
        "actions_en": [
            "Look for an official API or data download",
            "Choose another public source",
            "Contact the site owner for permission",
        ],
        "actions_ar": [
            "ابحث عن API رسمي أو ملف بيانات للتنزيل",
            "اختر مصدرًا عامًا آخر",
            "اطلب إذنًا من صاحب الموقع",
        ],
    },
    ErrorCode.HTTP_403: {
        "en": "The site refused the request (403).",
        "ar": "رفض الموقع الطلب (403).",
        "actions_en": [
            "Try the official API if one exists",
            "Use another public source",
            "Open Advanced details to add authorised headers",
        ],
        "actions_ar": [
            "جرّب الـAPI الرسمي إن وُجد",
            "استخدم مصدرًا عامًا آخر",
            "افتح الوضع المتقدم لإضافة ترويسات مصرح بها",
        ],
    },
    ErrorCode.HTTP_404: {
        "en": "The page was not found (404).",
        "ar": "الصفحة غير موجودة (404).",
        "actions_en": ["Check the address", "Search the site for the current location of the data"],
        "actions_ar": ["تحقق من العنوان", "ابحث داخل الموقع عن الموقع الحالي للبيانات"],
    },
    ErrorCode.HTTP_429_RATE_LIMIT: {
        "en": "The site asked us to slow down (429).",
        "ar": "طلب الموقع تخفيض معدل الطلبات (429).",
        "actions_en": [
            "Lower the request rate in settings",
            "Reduce the page limit",
            "Retry later",
        ],
        "actions_ar": ["خفّض معدل الطلبات في الإعدادات", "قلّل عدد الصفحات", "أعد المحاولة لاحقًا"],
    },
    ErrorCode.HTTP_ERROR: {
        "en": "The site returned an error response.",
        "ar": "أعاد الموقع استجابة خطأ.",
        "actions_en": ["Retry once", "Check the address in a browser"],
        "actions_ar": ["أعد المحاولة مرة واحدة", "افتح العنوان في المتصفح للتحقق"],
    },
    ErrorCode.TIMEOUT: {
        "en": "The site took too long to answer.",
        "ar": "استغرق الموقع وقتًا طويلًا للرد.",
        "actions_en": [
            "Retry",
            "Increase the timeout in Advanced mode",
            "Reduce the number of pages",
        ],
        "actions_ar": ["أعد المحاولة", "زد المهلة في الوضع المتقدم", "قلّل عدد الصفحات"],
    },
    ErrorCode.SSL_ERROR: {
        "en": "The secure connection to the site could not be verified.",
        "ar": "تعذر التحقق من الاتصال الآمن بالموقع.",
        "actions_en": ["Check the address", "Try the address published by the site owner"],
        "actions_ar": ["تحقق من العنوان", "جرّب النسخة التي ينشرها صاحب الموقع"],
    },
    ErrorCode.CONNECTION_ERROR: {
        "en": "The site could not be reached.",
        "ar": "تعذر الوصول إلى الموقع.",
        "actions_en": ["Check your internet connection", "Verify the domain name"],
        "actions_ar": ["تحقق من اتصال الإنترنت", "تأكد من اسم النطاق"],
    },
    ErrorCode.CONTENT_UNSUPPORTED: {
        "en": "This content type is not supported by the selected method.",
        "ar": "نوع المحتوى هذا غير مدعوم بالطريقة المختارة.",
        "actions_en": ["Try document extraction if this is a PDF", "Look for a CSV/JSON version"],
        "actions_ar": ["جرّب استخراج المستندات إذا كان الملف PDF", "ابحث عن نسخة CSV/JSON"],
    },
    ErrorCode.CONTENT_TOO_LARGE: {
        "en": "The response is larger than the configured safety limit.",
        "ar": "حجم الاستجابة أكبر من الحد الآمن المحدد.",
        "actions_en": [
            "Raise the size limit in settings if you trust the source",
            "Download the file directly",
        ],
        "actions_ar": ["ارفع حد الحجم في الإعدادات إذا كنت تثق بالمصدر", "نزّل الملف مباشرة"],
    },
    ErrorCode.NO_DATA_DETECTED: {
        "en": "No structured dataset was detected on this page.",
        "ar": "لم يتم اكتشاف بيانات منظمة في هذه الصفحة.",
        "actions_en": [
            "Describe the fields you need in the request box",
            "Try browser mode",
            "Try article or document extraction",
        ],
        "actions_ar": [
            "صف الحقول التي تريدها في صندوق الطلب",
            "جرّب وضع المتصفح",
            "جرّب استخراج المقال أو المستند",
        ],
    },
    ErrorCode.JS_REQUIRED: {
        "en": "This page builds its content with JavaScript after loading.",
        "ar": "هذه الصفحة تبني محتواها عبر JavaScript بعد التحميل.",
        "actions_en": ["Retry with browser mode", "Inspect the detected network data"],
        "actions_ar": ["أعد المحاولة بوضع المتصفح", "اطّلع على بيانات الشبكة المكتشفة"],
    },
    ErrorCode.LOGIN_REQUIRED: {
        "en": "This source requires a signed-in session.",
        "ar": "هذا المصدر يتطلب جلسة مسجّلة الدخول.",
        "actions_en": [
            "Use an official API with a token you are authorised to use",
            "Choose a public source",
        ],
        "actions_ar": ["استخدم API رسميًا برمز مصرح لك باستخدامه", "اختر مصدرًا عامًا"],
    },
    ErrorCode.CAPTCHA_OR_CHALLENGE: {
        "en": "The source requires interactive verification. This app does not bypass such checks.",
        "ar": "المصدر يتطلب تحققًا تفاعليًا. هذا التطبيق لا يتجاوز هذه الفحوص.",
        "actions_en": [
            "Use an official API",
            "Complete the verification manually if you are permitted",
            "Choose another source",
        ],
        "actions_ar": [
            "استخدم API رسميًا",
            "أكمل التحقق يدويًا إن كان مسموحًا لك",
            "اختر مصدرًا آخر",
        ],
    },
    ErrorCode.API_AUTH_REQUIRED: {
        "en": "This API needs a key or token.",
        "ar": "هذا الـAPI يحتاج مفتاحًا أو رمزًا.",
        "actions_en": [
            "Add your own authorised key in Advanced mode",
            "Look for the public endpoint",
        ],
        "actions_ar": ["أضف مفتاحك المصرح به في الوضع المتقدم", "ابحث عن نقطة النهاية العامة"],
    },
    ErrorCode.SELECTOR_NOT_FOUND: {
        "en": "The selector you supplied matched nothing on the page.",
        "ar": "المحدد الذي أدخلته لم يطابق أي عنصر في الصفحة.",
        "actions_en": ["Check the selector", "Let automatic detection propose datasets instead"],
        "actions_ar": ["تحقق من المحدد", "دع الاكتشاف التلقائي يقترح مجموعات البيانات"],
    },
    ErrorCode.PAGINATION_LOOP: {
        "en": "Pagination started repeating the same page, so it was stopped.",
        "ar": "بدأ الترقيم بتكرار الصفحة نفسها، لذلك تم إيقافه.",
        "actions_en": [
            "Reduce max pages",
            "Choose a different pagination mode in Advanced mode",
        ],
        "actions_ar": ["قلّل الحد الأقصى للصفحات", "اختر نمط ترقيم آخر في الوضع المتقدم"],
    },
    ErrorCode.SCHEMA_MISMATCH: {
        "en": "The fields found do not match the requested schema.",
        "ar": "الحقول الموجودة لا تطابق المخطط المطلوب.",
        "actions_en": ["Review the field mapping", "Reduce the required fields"],
        "actions_ar": ["راجع ربط الحقول", "قلّل الحقول المطلوبة"],
    },
    ErrorCode.EXPORT_FORMAT_LIMITATION: {
        "en": "This format cannot safely represent the current data.",
        "ar": "هذه الصيغة لا تستطيع تمثيل البيانات الحالية بأمان.",
        "actions_en": [
            "Export CSV or Parquet instead",
            "Simplify or rename the affected columns",
        ],
        "actions_ar": ["صدّر CSV أو Parquet بدلًا منها", "بسّط أو أعد تسمية الأعمدة المتأثرة"],
    },
    ErrorCode.OPTIONAL_ENGINE_NOT_INSTALLED: {
        "en": "This optional engine is not installed in the current environment.",
        "ar": "هذا المحرك الاختياري غير مثبت في البيئة الحالية.",
        "actions_en": [
            "See Settings and Engines for the install command",
            "Continue with the built-in engines",
        ],
        "actions_ar": ["راجع الإعدادات ← المحركات لمعرفة أمر التثبيت", "تابع بالمحركات المدمجة"],
    },
    ErrorCode.API_KEY_MISSING: {
        "en": "This provider needs an API key that is not configured.",
        "ar": "هذا المزود يحتاج مفتاح API غير مضبوط.",
        "actions_en": ["Add the key to your .env file", "Use a local-only method instead"],
        "actions_ar": ["أضف المفتاح إلى ملف .env", "استخدم طريقة محلية بالكامل"],
    },
    ErrorCode.NO_ROUTE: {
        "en": "No reliable extraction method was found for this source.",
        "ar": "لم يتم العثور على طريقة استخراج موثوقة لهذا المصدر.",
        "actions_en": [
            "Describe the fields you need",
            "Enable browser mode",
            "Try a different page of the same site",
        ],
        "actions_ar": ["صف الحقول التي تريدها", "فعّل وضع المتصفح", "جرّب صفحة أخرى من الموقع نفسه"],
    },
    ErrorCode.CANCELLED: {
        "en": "The run was cancelled.",
        "ar": "تم إلغاء التشغيل.",
        "actions_en": ["Start a new extraction"],
        "actions_ar": ["ابدأ استخراجًا جديدًا"],
    },
    ErrorCode.INTERNAL: {
        "en": "Something went wrong inside the application.",
        "ar": "حدث خطأ داخلي في التطبيق.",
        "actions_en": [
            "Open Diagnostics for the sanitized technical log",
            "Retry with a smaller scope",
        ],
        "actions_ar": ["افتح التشخيص لعرض السجل التقني", "أعد المحاولة بنطاق أصغر"],
    },
}


@dataclass
class ScraperError(Exception):
    """Application error with a stable code and human guidance."""

    code: ErrorCode
    detail: str = ""
    context: dict[str, object] = field(default_factory=dict)

    def __post_init__(self) -> None:
        super().__init__(f"{self.code.value}: {self.detail}" if self.detail else self.code.value)

    def message(self, lang: str = "en") -> str:
        guide = ERROR_GUIDE.get(self.code, {})
        base = str(guide.get("ar" if lang == "ar" else "en", self.code.value))
        return f"{base} {self.detail}".strip() if self.detail else base

    def actions(self, lang: str = "en") -> list[str]:
        guide = ERROR_GUIDE.get(self.code, {})
        key = "actions_ar" if lang == "ar" else "actions_en"
        return list(guide.get(key, []))  # type: ignore[arg-type]


class UrlBlocked(ScraperError):
    """Raised by the URL guard; kept as a distinct type for tests and logging."""


def http_status_code(status: int) -> ErrorCode:
    """Map an HTTP status onto the error taxonomy."""
    return {
        401: ErrorCode.API_AUTH_REQUIRED,
        403: ErrorCode.HTTP_403,
        404: ErrorCode.HTTP_404,
        429: ErrorCode.HTTP_429_RATE_LIMIT,
    }.get(status, ErrorCode.HTTP_ERROR)

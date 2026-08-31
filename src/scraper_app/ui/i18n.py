"""Translation dictionary (spec section 18).

Language never touches extraction logic: it only selects a label. Technical
identifiers (URLs, selectors, field names, code) stay left-to-right in both
languages.
"""

from __future__ import annotations

LANGUAGES = {"en": "English", "ar": "العربية"}

STRINGS: dict[str, dict[str, str]] = {
    # ---------------------------------------------------------------- shell
    "app_title": {"en": "Smart Research Web Scraper", "ar": "أداة جمع بيانات الويب للباحثين"},
    "app_tagline": {
        "en": "Turn web pages into organised research data — without writing code.",
        "ar": "حوّل صفحات الويب إلى بيانات بحثية منظمة بدون كتابة كود.",
    },
    "language": {"en": "Language", "ar": "اللغة"},
    "developed_by": {"en": "developed by", "ar": "تطوير"},
    "workflow": {"en": "Workflow", "ar": "مسار العمل"},
    "mode": {"en": "Mode", "ar": "الوضع"},
    "auto": {"en": "Auto", "ar": "تلقائي"},
    "guided": {"en": "Guided", "ar": "موجّه"},
    "advanced": {"en": "Advanced", "ar": "متقدم"},
    "auto_help": {
        "en": "Paste a link and let the app find the data.",
        "ar": "الصق رابطًا ودع التطبيق يجد البيانات.",
    },
    "guided_help": {
        "en": "Choose the dataset, fields and scope yourself.",
        "ar": "اختر مجموعة البيانات والحقول والنطاق بنفسك.",
    },
    "advanced_help": {
        "en": "Full control: headers, selectors, pagination, engine.",
        "ar": "تحكم كامل: الترويسات، المحددات، الترقيم، المحرك.",
    },
    # ---------------------------------------------------------------- steps
    "step_source": {"en": "Source", "ar": "المصدر"},
    "step_detect": {"en": "Detect", "ar": "الاكتشاف"},
    "step_fields": {"en": "Fields", "ar": "الحقول"},
    "step_preview": {"en": "Preview", "ar": "المعاينة"},
    "step_extract": {"en": "Extract", "ar": "الاستخراج"},
    "step_clean": {"en": "Clean & Explore", "ar": "التنظيف والاستكشاف"},
    "step_export": {"en": "Export", "ar": "التصدير"},
    "completed": {"en": "completed", "ar": "مكتمل"},
    "current": {"en": "current", "ar": "الحالي"},
    "not_started": {"en": "not started", "ar": "لم يبدأ"},
    "needs_review": {"en": "needs review", "ar": "يحتاج مراجعة"},
    # ---------------------------------------------------------------- home
    "url_label": {"en": "Website address", "ar": "عنوان الموقع"},
    "url_help": {
        "en": "Paste the page that shows the data you need. Only public http/https addresses are allowed.",
        "ar": "الصق الصفحة التي تعرض البيانات المطلوبة. يُسمح فقط بعناوين http/https العامة.",
    },
    "goal_label": {
        "en": "What data do you need? (optional)",
        "ar": "ما البيانات التي تحتاجها؟ (اختياري)",
    },
    "goal_placeholder": {
        "en": "Example: Extract country, year, inflation rate, GDP and source link.",
        "ar": "مثال: استخرج الدولة، السنة، معدل التضخم، الناتج المحلي، ورابط المصدر.",
    },
    "preset": {"en": "What kind of page is it?", "ar": "ما نوع الصفحة؟"},
    "analyze": {"en": "Analyze website", "ar": "تحليل الموقع"},
    "try_demo": {"en": "Try the built-in demo", "ar": "جرّب العرض التجريبي"},
    "quick_start": {"en": "Quick start", "ar": "بداية سريعة"},
    # ---------------------------------------------------------------- analysis
    "analysis_title": {"en": "Source analysis", "ar": "تحليل المصدر"},
    "status": {"en": "Status", "ar": "الحالة"},
    "accessible": {"en": "Accessible", "ar": "متاح"},
    "content": {"en": "Content", "ar": "المحتوى"},
    "tables_found": {"en": "Tables", "ar": "الجداول"},
    "json_found": {"en": "JSON sources", "ar": "مصادر JSON"},
    "links_found": {"en": "Internal links", "ar": "الروابط الداخلية"},
    "robots_status": {"en": "Robots status", "ar": "حالة robots"},
    "difficulty": {"en": "Estimated difficulty", "ar": "الصعوبة المتوقعة"},
    "recommended_method": {"en": "Recommended method", "ar": "الطريقة الموصى بها"},
    "why_this_method": {"en": "Why this method?", "ar": "لماذا هذه الطريقة؟"},
    "detected_datasets": {"en": "Detected datasets", "ar": "مجموعات البيانات المكتشفة"},
    "overview": {"en": "Overview", "ar": "نظرة عامة"},
    "technical_details": {"en": "Technical details", "ar": "تفاصيل تقنية"},
    "use_this": {"en": "Use this dataset", "ar": "استخدم هذه المجموعة"},
    "sample": {"en": "Sample", "ar": "عيّنة"},
    "rows": {"en": "Rows", "ar": "الصفوف"},
    "columns": {"en": "Columns", "ar": "الأعمدة"},
    # ---------------------------------------------------------------- fields
    "fields_title": {"en": "Choose the fields", "ar": "اختر الحقول"},
    "include": {"en": "Include", "ar": "تضمين"},
    "field": {"en": "Field", "ar": "الحقل"},
    "rename": {"en": "Rename to", "ar": "إعادة التسمية"},
    "detected_type": {"en": "Detected type", "ar": "النوع المكتشف"},
    "confidence": {"en": "Confidence", "ar": "الثقة"},
    "preview_extraction": {"en": "Preview extraction", "ar": "معاينة الاستخراج"},
    # ---------------------------------------------------------------- run
    "scope": {"en": "How much to collect", "ar": "حجم الجمع"},
    "single_page": {"en": "This page only", "ar": "هذه الصفحة فقط"},
    "several_pages": {"en": "Follow pagination", "ar": "تتبع ترقيم الصفحات"},
    "max_pages": {"en": "Maximum pages", "ar": "الحد الأقصى للصفحات"},
    "max_rows": {"en": "Maximum rows", "ar": "الحد الأقصى للصفوف"},
    "preflight": {"en": "Before we start", "ar": "قبل البدء"},
    "start_extraction": {"en": "Start extraction", "ar": "ابدأ الاستخراج"},
    "change_settings": {"en": "Change settings", "ar": "تغيير الإعدادات"},
    "local_only": {"en": "Use local-only mode", "ar": "استخدم الوضع المحلي فقط"},
    "cancel": {"en": "Cancel", "ar": "إلغاء"},
    "running": {"en": "Collecting data…", "ar": "جارٍ جمع البيانات…"},
    # ---------------------------------------------------------------- workspace
    "tab_data": {"en": "Data", "ar": "البيانات"},
    "tab_variables": {"en": "Variables", "ar": "المتغيرات"},
    "tab_quality": {"en": "Quality", "ar": "الجودة"},
    "tab_charts": {"en": "Charts", "ar": "الرسوم"},
    "tab_sources": {"en": "Sources", "ar": "المصادر"},
    "tab_recipe": {"en": "Recipe", "ar": "الوصفة"},
    "tab_code": {"en": "Code", "ar": "الكود"},
    "tab_downloads": {"en": "Downloads", "ar": "التنزيلات"},
    "tab_diagnostics": {"en": "Diagnostics", "ar": "التشخيص"},
    "missing_cells": {"en": "Missing cells", "ar": "الخلايا الناقصة"},
    "duplicates": {"en": "Duplicate rows", "ar": "الصفوف المكررة"},
    "clean_validate": {"en": "Clean & validate", "ar": "التنظيف والتحقق"},
    "apply_cleaning": {"en": "Apply cleaning", "ar": "طبّق التنظيف"},
    "reset_cleaning": {"en": "Reset to extracted data", "ar": "إعادة إلى البيانات المستخرجة"},
    "download_bundle": {
        "en": "Download the complete research package (ZIP)",
        "ar": "نزّل حزمة البحث الكاملة (ZIP)",
    },
    "common_formats": {"en": "Common", "ar": "شائعة"},
    "research_formats": {"en": "Research software", "ar": "برامج بحثية"},
    "database_formats": {"en": "Database", "ar": "قواعد بيانات"},
    "reproducible_formats": {"en": "Reproducible", "ar": "قابلة لإعادة الإنتاج"},
    # ---------------------------------------------------------------- misc
    "new_extraction": {"en": "New extraction", "ar": "استخراج جديد"},
    "start_over": {"en": "Start over", "ar": "البدء من جديد"},
    "clear_session": {"en": "Clear session data", "ar": "مسح بيانات الجلسة"},
    "history": {"en": "History", "ar": "السجل"},
    "engines": {"en": "Engines & keys", "ar": "المحركات والمفاتيح"},
    "help": {"en": "Help", "ar": "المساعدة"},
    "find_sources": {"en": "Find sources", "ar": "البحث عن مصادر"},
    "search_sources": {"en": "Search for sources", "ar": "ابحث عن مصادر"},
    "analyze_this": {"en": "Analyze this", "ar": "حلّل هذا"},
    "ai_assistance": {"en": "AI assistance", "ar": "مساعدة الذكاء الاصطناعي"},
    "ai_mode": {"en": "When may a model be used?", "ar": "متى يُسمح باستخدام نموذج؟"},
    "ai_provider": {"en": "Model provider", "ar": "مزود النموذج"},
    "agentic_mode": {
        "en": "Allow agentic browsing for multi-step pages",
        "ar": "السماح بالتصفح الوكيل للصفحات متعددة الخطوات",
    },
    "what_next": {"en": "What you can do next", "ar": "ما يمكنك فعله الآن"},
    "no_results_yet": {
        "en": "No dataset yet — start from the Home page.",
        "ar": "لا توجد بيانات بعد — ابدأ من الصفحة الرئيسية.",
    },
}


def t(key: str, lang: str = "en") -> str:
    """Translate a key, falling back to English and then to the key itself."""
    entry = STRINGS.get(key)
    if not entry:
        return key
    return entry.get(lang) or entry.get("en") or key


def is_rtl(lang: str) -> bool:
    return lang == "ar"

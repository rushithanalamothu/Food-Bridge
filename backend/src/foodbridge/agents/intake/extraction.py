"""Conservative offline extraction. Missing is distinct from an explicitly declared empty list."""

import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from foodbridge.agents.intake.policy import ALLERGENS, normalize
from foodbridge.domain.contracts import PickupWindow
from foodbridge.domain.intake import ExtractionResult, ProposedFields, ReviewIssue

REQUIRED = (
    "food_name",
    "category",
    "quantity_kg",
    "storage",
    "allergens",
    "pickup_window",
    "safe_use_by",
)


def review_issues(fields: ProposedFields) -> list[ReviewIssue]:
    return [
        ReviewIssue(field=name, code="missing", message=f"Please confirm {name.replace('_', ' ')}.")
        for name in REQUIRED
        if getattr(fields, name) is None
    ]


def _clock(hour: str, minute: str | None, meridiem: str, day: datetime) -> datetime:
    h = int(hour)
    if not 1 <= h <= 12:
        raise ValueError("ambiguous hour")
    return day.replace(
        hour=h % 12 + (12 if meridiem.lower() == "pm" else 0),
        minute=int(minute or 0),
        second=0,
        microsecond=0,
    )


def extract_rules(description: str, timezone: str, now: datetime) -> ExtractionResult:
    text = description.lower()
    fields = ProposedFields()
    evidence: dict[str, str] = {}
    local = now.astimezone(ZoneInfo(timezone))
    if "tomorrow" in text:
        local += timedelta(days=1)
    # Never infer dates beyond an explicit today/tomorrow. Ambiguous times remain missing.
    explicit_day = bool(re.search(r"\b(today|tomorrow|tonight)\b", text)) and not (
        "tomorrow" in text and re.search(r"\b(today|tonight)\b", text)
    )
    weight = re.search(r"\b(\d+(?:\.\d+)?)\s*(kg|kilograms?|grams?|g|lbs?|pounds?)\b", text)
    if weight:
        amount = float(weight[1])
        amount *= (
            0.001
            if weight[2] in {"g", "gram", "grams"}
            else (0.45359237 if weight[2] in {"lb", "lbs", "pound", "pounds"} else 1)
        )
        if round(amount, 3) > 0:
            fields.quantity_kg = round(amount, 3)
            evidence["quantity_kg"] = description[weight.start() : weight.end()]
    count = re.search(
        r"\b(\d+)\s+(?:individually\s+boxed\s+|boxed\s+)?(?:meals?|portions?|servings?)\b", text
    )
    if count and int(count[1]) > 0:
        fields.portions = int(count[1])
        evidence["portions"] = description[count.start() : count.end()]
    # Only use an explicit item label, rather than turning arbitrary prose into a food name.
    item = re.search(r"(?:^|[\n.;])\s*(?:food|item)\s*:\s*([^\n.;]+)", description, re.I)
    if item:
        fields.food_name = item[1].strip()[:200]
        evidence["food_name"] = item[0].strip()
    categories = [
        ("prepared_meals", r"\b(meals?|cooked rice|rice bowls?|boxed lunches)\b"),
        ("bakery", r"\b(bread|pastries|bagels)\b"),
        ("produce", r"\b(fresh vegetables|fresh fruit|produce|apples)\b"),
        ("dairy", r"\b(milk|yogurt|cheese)\b"),
        ("pantry", r"\b(canned|shelf.stable)\b"),
    ]
    found = [(category, re.search(pattern, text)) for category, pattern in categories]
    found = [(category, match) for category, match in found if match]
    if len(found) == 1:
        fields.category = found[0][0]
        evidence["category"] = description[found[0][1].start() : found[0][1].end()]
    for storage, pattern in [
        ("chilled", r"\b(refrigerated|fridge|chilled)\b"),
        ("frozen", r"\b(frozen|freezer)\b"),
        ("ambient", r"\b(ambient|room temperature|shelf.stable)\b"),
    ]:
        match = re.search(pattern, text)
        if match:
            if fields.storage is not None:
                fields.storage = None
                evidence.pop("storage", None)
                break
            fields.storage = storage
            evidence["storage"] = description[match.start() : match.end()]
    tags = [
        tag
        for tag in ("vegetarian", "vegan", "halal", "gluten-free", "dairy-free")
        if re.search(rf"\b{tag}\b", text) and not re.search(rf"\bnot\s+{tag}\b", text)
    ]
    fields.dietary_tags = tags or None
    allergen = re.search(r"\b(?:allergens?|contains)\s*:\s*([^.;\n]+)", text)
    if allergen:
        raw = allergen[1].strip()
        if raw in {"none", "none declared", "no known allergens"}:
            fields.allergens = []
        elif re.fullmatch(r"[a-z ,/-]+", raw) and not any(
            v in raw for v in ("unknown", "unsure", "maybe", "not ")
        ):
            parsed = [v.strip() for v in re.split(r",|\band\b", raw) if v.strip()]
            if parsed and {normalize(v) for v in parsed} <= ALLERGENS:
                fields.allergens = parsed
        evidence["allergens"] = description[allergen.start() : allergen.end()]
    window = re.search(
        r"\bpickup\s*:?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\s*(?:-|–|to)\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b",
        text,
    )
    deadline = re.search(
        r"\b(?:use by|safe.use by|safe until)\s*:?\s*(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b", text
    )
    if explicit_day:
        try:
            if window:
                start = _clock(window[1], window[2], window[3], local)
                end = _clock(window[4], window[5], window[6], local)
                if end > start:
                    fields.pickup_window = PickupWindow(start=start, end=end)
                    evidence["pickup_window"] = description[window.start() : window.end()]
            if deadline:
                fields.safe_use_by = _clock(deadline[1], deadline[2], deadline[3], local)
                evidence["safe_use_by"] = description[deadline.start() : deadline.end()]
        except ValueError:
            fields.pickup_window = None
            fields.safe_use_by = None
    return ExtractionResult(
        fields=fields, provider="rules", evidence=evidence, issues=review_issues(fields)
    )

"""A compact dispatch draft for one conversation, independent of the transcript."""
from dataclasses import dataclass, replace
from datetime import date
import re

from agent.parse import ORDER, resolve_order, split_line
from desk.data import TODAY
from desk.schemas import ConstraintKind, Objective, ParsedRequest

TRADEOFF = (
    (100, 0), (75, 25), (50, 50), (25, 75), (0, 100),
)
PREFERENCES = {
    ConstraintKind.FASTEST, ConstraintKind.CHEAPEST_ON_TIME, ConstraintKind.LOWEST_DEFECT_ON_TIME,
}
DONT_SPLIT = re.compile(r"\b(?:do not|don't|must not|never|cannot|can't|no)\s+split\b"
                        r"|\b(?:one|a single)\s+workshop\b", re.I)
EXPLICIT_SPLIT = re.compile(r"\b(?:can|may|could|please|go ahead and)\s+split\b"
                            r"|\bsplit\s+(?:it|the batch)\b", re.I)
DATE_WORDS = re.compile(
    r"\b(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|"
    r"Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\.?\s+"
    r"(\d{1,2})(?:st|nd|rd|th)?(?:[ ,]+(\d{4}))?\b", re.I,
)
ISO_DATE = re.compile(r"\b\d{4}-\d{2}-\d{2}\b")
COUNT = r"(?:\d{1,3}(?:,\d{3})+|\d+)"
QUANTITY_CHANGE = re.compile(rf"\bfrom\s+{COUNT}\s+to\s+({COUNT})(?![\d,.])", re.I)
BARE_QUANTITY = re.compile(rf"^\s*(?:(make (?:it|that)|change (?:it )?to)\s+)?({COUNT})\s*(pieces|pcs|units)?[.!]?\s*$", re.I)
MONTHS = "jan feb mar apr may jun jul aug sep oct nov dec".split()
RECHECK = re.compile(r"^(?:recheck|recalculate|compare|show (?:the )?options)[?!. ]*$", re.I)


def objective_for(level: int) -> Objective:
    if type(level) is not int or not 0 <= level < len(TRADEOFF):
        raise ValueError("Choose an optimisation level from 0 to 4.")
    cost, defect = TRADEOFF[level]
    return Objective(f"chat_{level}", w_late=0, w_cost=cost / 100, w_defect=defect / 100, on_time_first=True)


@dataclass
class Draft:
    request: ParsedRequest
    turn: int = 0
    no_split: bool = False
    decision_id: str | None = None


def explicit_date(text):
    dates = []
    for match in ISO_DATE.finditer(text):
        dates.append((match.start(), date.fromisoformat(match[0])))
    for match in DATE_WORDS.finditer(text):
        month, day, year = match.groups()
        dates.append((match.start(), date(int(year or TODAY.year), MONTHS.index(month[:3].lower()) + 1, int(day))))
    values = list(dict.fromkeys(value for _, value in sorted(dates)))
    if len(values) > 1 and not re.search(r"\bfrom\b.*\bto\b", text, re.I):
        raise ValueError("Which date should I use? Please give one deadline.")
    return values[-1] if values else None


def merge_turn(line, parser, previous: Draft | None) -> Draft:
    _, _, _, text = split_line(line)
    prior = previous.request if previous else None
    ids = set(oid.upper() for oid in ORDER.findall(text))
    if len(ids) > 1:
        raise ValueError("Please give one order per conversation.")
    if prior and ids:
        oid = next(iter(ids))
        if prior.order_id and oid != prior.order_id:
            raise ValueError("Start a new conversation for a different order.")
        if prior.candidate_orders and oid not in prior.candidate_orders:
            raise ValueError("That order is outside the candidate list. Select a listed order or start a new conversation.")

    try:
        due = explicit_date(text)
    except ValueError as error:
        if str(error).startswith("Which date"):
            raise
        raise ValueError("Please give a valid calendar date, for example Apr 18.") from error
    text_for_count = ISO_DATE.sub(" ", DATE_WORDS.sub(" ", text))
    correction = QUANTITY_CHANGE.search(text_for_count)
    short_quantity = BARE_QUANTITY.fullmatch(text_for_count) if prior else None
    quantity = correction[1] if correction else None
    if short_quantity and ("pieces" in prior.missing or short_quantity[1] or short_quantity[3]):
        quantity = short_quantity[2]
    req = _direct_request(line, parser, prior, due, bool(short_quantity and quantity))
    if due is not None and "due_date" not in req.missing:
        req.due_date = due
    if quantity:
        req.pieces = int(quantity.replace(",", ""))
        req.missing = [field for field in req.missing if field != "pieces"]
    if req.pieces is not None and not 1 <= req.pieces <= 100_000:
        raise ValueError("Enter a quantity between 1 and 100,000 pieces.")

    no_split = (previous.no_split if previous else False)
    if DONT_SPLIT.search(text):
        no_split = True
    elif EXPLICIT_SPLIT.search(text):
        no_split = False
    if req.question_type:
        if prior and not prior.question_type:
            raise ValueError("Open a new conversation for a different question.")
        return Draft(resolve_order(req), (previous.turn if previous else 0) + 1, no_split)

    if prior and not prior.question_type:
        changed = bool(req.order_id or req.due_date or req.pieces is not None or req.suggested_workshop
                       or req.constraints or set(req.missing) - {"order"} or DONT_SPLIT.search(text)
                       or EXPLICIT_SPLIT.search(text) or RECHECK.fullmatch(text))
        if not changed:
            raise ValueError("Give a new quantity, deadline or instruction for this order, or start a new conversation.")
        req = _carry_forward(prior, req)
    if no_split:
        req.constraints = [item for item in req.constraints if item.kind != ConstraintKind.SPLIT_ALLOWED]
    req = resolve_order(req, req.customer, req.product, preserve_candidates=True)
    return Draft(req, (previous.turn if previous else 0) + 1, no_split)


def _direct_request(line, parser, prior, due, short_quantity):
    # Parse a simple answer locally. Keep the selected parser for full messages with instructions.
    from agent.parse import parse_baseline
    _, _, _, text = split_line(line)
    remainder = DATE_WORDS.sub("", ISO_DATE.sub("", text)).strip(" .,!?")
    simple_date = due is not None and re.fullmatch(r"(?:(?:due|by|back by|now due|make it|move it to)\s*)?",
                                                    remainder, re.I)
    if simple_date or short_quantity or (
            prior and (ORDER.fullmatch(text) or RECHECK.fullmatch(text))):
        req = parse_baseline(line, resolve=False)
        req.parser = "follow-up"
        if simple_date:
            req.pieces = None
        return req
    req = parser(line, resolve=False)
    if due and req.pieces is not None:
        without_dates = ISO_DATE.sub(" ", DATE_WORDS.sub(" ", text))
        without_ids = ORDER.sub(" ", without_dates)
        counts = {int(value.replace(",", "")) for value in re.findall(COUNT, without_ids)}
        if req.pieces not in counts:
            req.pieces = None
    return req


def _carry_forward(prior, req):
    missing = set(prior.missing) | (set(req.missing) - {"order"})
    values = {}
    for field in ("order", "pieces", "due_date"):
        key = "order_id" if field == "order" else field
        new_value = getattr(req, key)
        if new_value is not None and field not in req.missing:
            missing.discard(field)
        value = new_value if new_value is not None else getattr(prior, key)
        values[key] = None if field in missing else value

    new_preferences = any(item.kind in PREFERENCES for item in req.constraints)
    constraints = {
        (item.kind, item.value): item for item in prior.constraints
        if not (new_preferences and item.kind in PREFERENCES)
    }
    constraints.update({(item.kind, item.value): item for item in req.constraints})
    return replace(
        req, **values,
        customer=req.customer or prior.customer, product=req.product or prior.product,
        candidate_orders=[] if values["order_id"] else prior.candidate_orders,
        missing=[field for field in ("order", "pieces", "due_date") if field in missing],
        suggested_workshop=req.suggested_workshop or prior.suggested_workshop,
        constraints=list(constraints.values()),
    )

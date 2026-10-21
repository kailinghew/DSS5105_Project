"""
parse.py — chat message -> ParsedRequest.

Two parsers share one output contract (desk.schemas.ParsedRequest):

  parse_llm(line)       Claude Haiku 5.5 extracts; deterministic code validates every value
                        against the message and resolves the order. The LLM's real job.
  parse_baseline(line)  Regex + lookups, no LLM. Runs today so the pipeline works end to
                        end, and stays as the baseline the LLM parser must beat on the
                        30 inbox requests and on the held-out paraphrases.

Neither parser decides the behaviour or does arithmetic; desk_agent.handle() does that
with the tools.
"""
from __future__ import annotations

import re
from datetime import date

from desk.data import orders, workshop_by_name, workshops
from desk.schemas import Constraint, ConstraintKind, ParsedRequest
from desk.tools import find_orders, get_order

LINE = re.compile(r"^(R\d+)\s+\[(\d\d:\d\d)\]\s+([^:]+):\s*(.*)$")
MONTHS = {m: i for i, m in enumerate("jan feb mar apr may jun jul aug sep oct nov dec".split(), 1)}
DATE = re.compile(r"\b(Jan|Feb|Mar|Apr|May|Jun)[a-z]*\.?\s+(\d{1,2})\b", re.I)
PIECES = re.compile(r"\b(\d[\d,]*)\s+(?!(?:days?|weeks?)\b)[a-z]", re.I)
ORDER = re.compile(r"\bORD-\d+\b", re.I)


def split_line(line: str) -> tuple[str, str, str, str]:
    m = LINE.match(line.strip())
    if not m:
        raise ValueError(f"not a chat line: {line!r}")
    return m.groups()


# ------------------------------------------------------------------------------ LLM
_KINDS = [k.value for k in ConstraintKind]

LLM_SCHEMA = {
    "type": "object",
    "properties": {
        "order_id": {"type": ["string", "null"]},
        "pieces": {"type": ["integer", "null"]},
        "due_date": {"type": ["string", "null"]},
        "customer": {"type": ["string", "null"]},
        "product": {"type": ["string", "null"]},
        "suggested_workshop": {"type": ["string", "null"]},
        "constraints": {"type": "array", "items": {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": _KINDS},
                "value": {"type": ["string", "null"]},
                "imposed_by": {"type": "string"},
                "source_text": {"type": "string"},
            },
            "required": ["kind", "value", "imposed_by", "source_text"],
            "additionalProperties": False}},
        "missing": {"type": "array", "items": {"type": "string", "enum": ["pieces", "due_date", "order"]}},
        "question_type": {"type": ["string", "null"], "enum": ["history", "price", None]},
    },
    "required": ["order_id", "pieces", "due_date", "customer", "product", "suggested_workshop",
                 "constraints", "missing", "question_type"],
    "additionalProperties": False,
}


def llm_system_prompt() -> str:
    names = ", ".join(w.name for w in workshops().values())
    customers = ", ".join(sorted({o["customer"] for o in orders().values()}))
    products = ", ".join(sorted({o["product"] for o in orders().values()}))
    # Examples are invented; none is taken from data/dispatch_requests.txt (no tuning on the eval set).
    return f"""You read one message from a garment factory's dispatch group chat and extract the request.
Today is 2026-04-01. You only EXTRACT. You never decide where the batch goes, never check
eligibility and never calculate anything: tools do that after you.

Known workshops: {names}
Known customers: {customers}
Known products: {products}

Fields (use null or [] when the message does not say; never guess, never fill from memory):
- order_id: an id like "ORD-012" only if the message writes one.
- pieces: the quantity only if the message writes a number of pieces.
- due_date: YYYY-MM-DD only if the message gives a calendar date for when it is due / needed back /
  ships. Words like "this week" or "asap" are not a due date.
- customer, product: as named in the message (product singular, e.g. "Hoodie"), else null.
- suggested_workshop: a workshop the sender proposes to SEND the work to.
- constraints: instructions about HOW to choose. kind is one of:
  exclude_workshop (value = workshop name; "keep it away from X", "nothing new to X"),
  prefer_workshop (value = workshop name), fastest ("cost doesn't matter, fastest", "quickest"),
  cheapest_on_time ("cheapest that still makes the date"), lowest_defect_on_time ("lowest defect rate"),
  split_allowed ("split it across shops").
  imposed_by = the person who set it: if the sender relays someone ("Boss says ..."), that person;
  otherwise the sender. source_text = the exact words.
- missing: list what the sender says is still unknown or what is needed but absent:
  "pieces" (e.g. "usual quantities"), "due_date" (e.g. "will confirm the date"),
  "order" (a new order not yet in the system, "details to follow", or no way to tell which order).
- question_type: "history" if they ask what happened in the past (which workshop was used before);
  "price" if they ask for a quote or price given to a customer. Otherwise null.

Examples (invented):
"R90 [10:00] Ana: ORD-201 — 250 beanies for Cotton Club, back by May 3. Not GiantWeave please."
-> order_id "ORD-201", pieces 250, due_date "2026-05-03", customer "Cotton Club", product "Beanie",
   suggested_workshop null, constraints [exclude_workshop "GiantWeave", imposed_by "Ana"], missing [], question_type null
"R91 [10:05] Leo: the Northwind polos again, same as last time, ASAP"
-> order_id null, pieces null, due_date null, customer "Northwind Apparel", product "Polo shirt",
   constraints [], missing ["pieces", "due_date"], question_type null
"R92 [10:09] Kim: what did SteadyHands charge us for ORD-150?"
-> order_id "ORD-150", question_type "price", everything else null/[]"""


def _num_in_text(n: int, text: str) -> bool:
    return str(n) in re.sub(r"(?<=\d),(?=\d{3})", "", text)


def parse_llm(line: str, fallback: bool = True) -> ParsedRequest:
    """LLM extraction (Claude Haiku 5.5), then deterministic validation and order
    resolution. Any value the model reports that the message does not contain is dropped
    with a warning — the model never supplies a number. If the LLM is unavailable and
    fallback=True, the regex baseline is used and the request says so."""
    from .llm import LLMError, call_json, settings

    rid, time, sender, text = split_line(line)
    try:
        out = call_json(llm_system_prompt(), line.strip(), LLM_SCHEMA)
    except LLMError as e:
        if not fallback:
            raise
        req = parse_baseline(line)
        req.parser = "baseline(fallback)"
        req.warnings.append(f"LLM unavailable, used regex baseline: {e}")
        return req

    req = ParsedRequest(request_id=rid, sender=sender.strip(), time=time, raw_text=line.strip(),
                        parser=f"llm:{settings()['model']}")
    w = req.warnings

    # order id: must be written in the message
    oid = (out.get("order_id") or "").strip().upper()
    if oid:
        if re.fullmatch(r"ORD-\d+", oid) and oid in text.upper():
            req.order_id = oid
        else:
            w.append(f"dropped order_id {oid!r}: not in the message")

    # quantity and date: must be written in the message
    if out.get("pieces") is not None:
        if _num_in_text(out["pieces"], text):
            req.pieces = int(out["pieces"])
        else:
            w.append(f"dropped pieces {out['pieces']}: not in the message")
    if out.get("due_date"):
        try:
            d = date.fromisoformat(out["due_date"])
            if _num_in_text(d.day, text):
                req.due_date = d
            else:
                w.append(f"dropped due_date {d}: day not in the message")
        except ValueError:
            w.append(f"dropped due_date {out['due_date']!r}: not a date")

    def to_ws(name):
        ws = workshop_by_name(name) if name else None
        if name and ws is None:
            w.append(f"unknown workshop {name!r}")
        return ws.workshop_id if ws else None

    req.suggested_workshop = to_ws(out.get("suggested_workshop"))
    for c in out.get("constraints", []):
        kind = ConstraintKind(c["kind"])
        value = to_ws(c.get("value")) if kind in (ConstraintKind.EXCLUDE_WORKSHOP,
                                                  ConstraintKind.PREFER_WORKSHOP) else None
        if kind in (ConstraintKind.EXCLUDE_WORKSHOP, ConstraintKind.PREFER_WORKSHOP) and value is None:
            continue
        if kind == ConstraintKind.PREFER_WORKSHOP and req.suggested_workshop is None:
            req.suggested_workshop = value
        req.constraints.append(Constraint(kind, value, c.get("imposed_by") or req.sender,
                                          c.get("source_text", "")))
    req.missing = [m for m in dict.fromkeys(out.get("missing", []))]
    req.question_type = out.get("question_type")

    customer = _match_known(out.get("customer"), {o["customer"] for o in orders().values()})
    product = _match_known(out.get("product"), {o["product"] for o in orders().values()})
    return resolve_order(req, customer, product)


def _match_known(value: str | None, known: set[str]) -> str | None:
    if not value:
        return None
    v = _singular(value.lower().strip())
    for k in sorted(known, key=len, reverse=True):
        if k.lower() == value.lower().strip() or k.lower().startswith(v) or v.startswith(k.lower().split()[0]):
            return k
    return None


# ------------------------------------------------------------------------- baseline
_EXCLUDE_CUES = ("away from", "nothing new to", "not to", "avoid", "except")


def _singular(w: str) -> str:
    if w.endswith("ves"):
        return w[:-3] + "f"          # scarves -> scarf
    if w.endswith("s") and not w.endswith("ss"):
        return w[:-1]                # vests -> vest, hoodies -> hoodie
    return w


def parse_baseline(line: str) -> ParsedRequest:
    rid, time, sender, text = split_line(line)
    low = text.lower()
    req = ParsedRequest(request_id=rid, sender=sender.strip(), time=time, raw_text=line.strip())

    # questions this data cannot answer
    if re.search(r"which workshop did we|did we use", low):
        req.question_type = "history"
    elif re.search(r"what price|how much did we (quote|charge)", low):
        req.question_type = "price"

    # who imposed constraints: "Boss says ..." else the sender
    says = re.search(r"\b(\w+) (?:says|wants)\b", text)
    imposer = says.group(1) if says else req.sender

    # workshops mentioned
    for w in workshops().values():
        idx = low.find(w.name.lower())
        if idx < 0:
            continue
        before = low[max(0, idx - 25):idx]
        if any(cue in before for cue in _EXCLUDE_CUES):
            req.constraints.append(Constraint(ConstraintKind.EXCLUDE_WORKSHOP, w.workshop_id,
                                              imposer, text[max(0, idx - 25):idx + len(w.name)].strip(" .…—")))
        else:
            req.suggested_workshop = w.workshop_id

    # objective-style constraints
    for pat, kind in [(r"fastest|quickest", ConstraintKind.FASTEST),
                      (r"cheapest", ConstraintKind.CHEAPEST_ON_TIME),
                      (r"lowest defect", ConstraintKind.LOWEST_DEFECT_ON_TIME),
                      (r"\bsplit\b", ConstraintKind.SPLIT_ALLOWED)]:
        m = re.search(pat, low)
        if m:
            req.constraints.append(Constraint(kind, None, imposer, m.group(0)))

    # explicit gaps
    if re.search(r"usual quantit", low):
        req.missing.append("pieces")
    if re.search(r"(will )?confirm the new date|date tbc|new date after", low):
        req.missing.append("due_date")
    if re.search(r"details to follow", low):
        req.missing.append("order")

    # numbers stated in the message
    d = DATE.search(text)
    if d:
        req.due_date = date(2026, MONTHS[d.group(1)[:3].lower()], int(d.group(2)))
    text_wo_dates = DATE.sub(" ", text)
    p = PIECES.search(ORDER.sub(" ", text_wo_dates))
    if p:
        req.pieces = int(p.group(1).replace(",", ""))

    # which order?
    m = ORDER.search(text)
    customer = product = None
    if m:
        req.order_id = m.group(0).upper()
    else:
        customer = next((c for c in sorted({o["customer"] for o in orders().values()}, key=len,
                                           reverse=True) if c.lower() in low), None)
        words = {_singular(w) for w in re.findall(r"[a-z]+", low)}
        product = next((pr for pr in sorted({o["product"] for o in orders().values()})
                        if pr.lower().split()[0] in words), None)
    return resolve_order(req, customer, product)


def resolve_order(req: ParsedRequest, customer: str | None = None,
                  product: str | None = None) -> ParsedRequest:
    """Shared by both parsers: turn what was extracted into a known order (or a list of
    candidates to ask about), and fill from orders.csv what the message did not state."""
    if req.order_id:
        if get_order(req.order_id) is None:
            req.question_type = req.question_type or "unknown_order"
            return req
    else:
        if (customer or product) and "order" not in req.missing:   # a new order can't match
            matches = find_orders(customer=customer, product=product)
            if len(matches) == 1 and not req.missing:
                req.order_id = matches[0]["order_id"]
            else:
                req.candidate_orders = [o["order_id"] for o in matches]
        if not req.order_id and "order" not in req.missing:
            req.missing.append("order")
        if not req.order_id:
            return req

    o = get_order(req.order_id)
    if req.pieces is None and "pieces" not in req.missing:
        req.pieces = o["pieces"]
    if req.due_date is None and "due_date" not in req.missing:
        req.due_date = o["due_date"]
    return req

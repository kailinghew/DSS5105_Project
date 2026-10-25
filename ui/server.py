"""
server.py — the dispatcher desk web app. Standard library only (plus `anthropic` for the
LLM parser), so it runs the same on a laptop and on Render.

    python -m ui.server                # http://localhost:8000
    PORT=10000 python -m ui.server     # what Render does

JSON API (the page in ui/static/ is the only client):
    GET  /api/status                   LLM available? today's date, objectives
    GET  /api/inbox                    the 30 chat requests
    POST /api/handle   {line, parser, objective}   -> decision (+ id, reply text)
    POST /api/confirm  {id, confirmed_by}          -> logs a confirmed decision
    GET  /api/log                      latest decisions from logs/decisions.jsonl
    GET  /api/register?category=TOPS&pieces=1500&due=2026-04-13   -> 8 workshops evaluated

Notes for deployment: the audit log lives on local disk, which Render's free tier wipes
on every restart — fine for a demo, say so in the report. The API key stays on the
server (ANTHROPIC_API_KEY); the browser never sees it.
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import uuid
from datetime import date, datetime
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "harness")]

from agent.desk_agent import handle_line  # noqa: E402
from agent.parse import parse_baseline, parse_llm, split_line  # noqa: E402
from desk import audit  # noqa: E402
from desk.allocator import CONFIG as OBJECTIVES, load_objective  # noqa: E402
from desk.data import DATA, TODAY, workshops  # noqa: E402
from desk.explain import fmt_date  # noqa: E402
from desk.tools import evaluate_all  # noqa: E402

STATIC = Path(__file__).resolve().parent / "static"
MAX_MESSAGE = 500                 # characters; a chat line, not an essay
LLM_CALLS_PER_HOUR = 200          # protects the API budget on a public demo link

_decisions: dict[str, object] = {}      # id -> Decision, for confirm
_lock = threading.Lock()
_llm_calls: list[float] = []


def _llm_available() -> bool:
    from agent.llm import _load_dotenv
    _load_dotenv()
    try:
        import anthropic  # noqa: F401
    except ImportError:
        return False
    return bool(os.environ.get("ANTHROPIC_API_KEY"))


def _llm_budget_ok() -> bool:
    now = time.time()
    with _lock:
        _llm_calls[:] = [t for t in _llm_calls if now - t < 3600]
        if len(_llm_calls) >= LLM_CALLS_PER_HOUR:
            return False
        _llm_calls.append(now)
        return True


def _jsonable(x):
    if isinstance(x, (date, datetime)):
        return x.isoformat()
    raise TypeError(type(x).__name__)


def _normalise_line(text: str, sender: str) -> str:
    """Accept either a full inbox line ('R07 [08:23] Ravi: ...') or a bare message."""
    text = " ".join(text.split())
    try:
        split_line(text)
        return text
    except ValueError:
        name = re.sub(r"[^\w .&'-]", "", sender or "").strip() or "Dispatcher"
        return f"R00 [{datetime.now():%H:%M}] {name}: {text}"


def _reply_text(dec) -> str:
    """What the dispatcher would paste back into the group chat."""
    return dec.question or dec.explanation


def _decision_payload(dec, did: str) -> dict:
    d = dec.to_dict()
    due = dec.request.due_date
    d["id"] = did
    d["reply"] = _reply_text(dec)
    d["due_in_days"] = (due - TODAY).days if due else None
    d["due_label"] = fmt_date(due) if due else None
    for c in d["candidates"]:
        c["eta_label"] = fmt_date(date.fromisoformat(c["eta_date"])) if c.get("eta_date") else None
    return d


class Handler(SimpleHTTPRequestHandler):
    server_version = "QRDesk/1.0"

    def __init__(self, *a, **k):
        super().__init__(*a, directory=str(STATIC), **k)

    # quieter logs: one line per API call
    def log_message(self, fmt, *args):
        if self.path.startswith("/api/"):
            sys.stderr.write(f"{self.address_string()} {fmt % args}\n")

    def handle_one_request(self):
        # A visitor (or Render's health check) closing the connection mid-response is
        # normal on the internet; don't log it as a crash.
        try:
            super().handle_one_request()
        except (BrokenPipeError, ConnectionResetError):
            self.close_connection = True

    def _send(self, obj, status=HTTPStatus.OK):
        body = json.dumps(obj, default=_jsonable).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, msg, status=HTTPStatus.BAD_REQUEST):
        self._send({"error": msg}, status)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 20_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        super().end_headers()

    # ------------------------------------------------------------------ GET
    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/api/status":
                cfg = json.loads(OBJECTIVES.read_text())
                return self._send({"llm": _llm_available(), "today": TODAY,
                                   "objectives": list(cfg["objectives"]), "primary": cfg["primary"]})
            if url.path == "/api/inbox":
                lines = [l for l in (DATA / "dispatch_requests.txt").read_text(encoding="utf-8").splitlines()
                         if l.strip() and not l.startswith("#")]
                out = []
                for l in lines:
                    rid, t, who, msg = split_line(l)
                    out.append({"id": rid, "time": t, "sender": who, "text": msg, "line": l})
                return self._send(out)
            if url.path == "/api/log":
                return self._send(list(reversed(audit.read_log()))[:100])
            if url.path == "/api/register":
                return self._register(parse_qs(url.query))
            if url.path in ("/", "/index.html"):
                self.path = "/index.html"
            return super().do_GET()
        except (BrokenPipeError, ConnectionResetError):
            raise                                   # client went away; handled above
        except Exception as e:  # never show a stack trace to the browser
            return self._error(f"{type(e).__name__}: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _register(self, q):
        category = (q.get("category", ["TOPS"])[0] or "TOPS").upper()
        if category not in ("TOPS", "ACCESSORIES"):
            return self._error("category must be TOPS or ACCESSORIES")
        try:
            pieces = int(q.get("pieces", ["500"])[0])
            due = date.fromisoformat(q["due"][0]) if q.get("due", [""])[0] else None
        except ValueError:
            return self._error("pieces must be a whole number and due a date (YYYY-MM-DD)")
        if not 1 <= pieces <= 100_000:
            return self._error("pieces must be between 1 and 100,000")
        cards = {w.workshop_id: w for w in workshops().values()}
        rows = []
        for c in evaluate_all(category, pieces, TODAY, due):
            w = cards[c.workshop_id]
            r = c.__dict__.copy()
            r.update(capacity=w.capacity, makes=sorted(w.makes), status=w.status,
                     max_batch=w.max_batch, notes=w.notes,
                     eta_label=fmt_date(c.eta_date) if c.eta_date else None)
            rows.append(r)
        rows.sort(key=lambda r: (not r["eligible"], r["eta_days"]))
        return self._send({"category": category, "pieces": pieces, "due": due,
                           "due_in_days": (due - TODAY).days if due else None,
                           "due_label": fmt_date(due) if due else None, "rows": rows})

    # ----------------------------------------------------------------- POST
    def do_POST(self):
        url = urlparse(self.path)
        try:
            body = self._body()
        except (ValueError, json.JSONDecodeError):
            return self._error("body must be JSON")
        try:
            if url.path == "/api/handle":
                return self._handle(body)
            if url.path == "/api/confirm":
                return self._confirm(body)
            return self._error("unknown endpoint", HTTPStatus.NOT_FOUND)
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as e:
            return self._error(f"{type(e).__name__}: {e}", HTTPStatus.INTERNAL_SERVER_ERROR)

    def _handle(self, body):
        text = str(body.get("line", "")).strip()
        if not text:
            return self._error("Type or pick a chat message first.")
        if len(text) > MAX_MESSAGE:
            return self._error(f"Message is too long ({len(text)} characters, limit {MAX_MESSAGE}).")
        line = _normalise_line(text, str(body.get("sender", "")))
        objective = str(body.get("objective") or "")
        try:
            obj = load_objective(objective or None)
        except KeyError:
            return self._error(f"unknown objective {objective!r}")

        use_llm = body.get("parser") == "llm"
        note = None
        if use_llm and not _llm_available():
            use_llm, note = False, "Claude is not configured on this server, so the regex parser was used."
        elif use_llm and not _llm_budget_ok():
            use_llm, note = False, "Hourly Claude budget for this demo is used up, so the regex parser was used."
        dec = handle_line(line, parse_llm if use_llm else parse_baseline, objective=obj)
        if note:
            dec.request.warnings.insert(0, note)

        did = uuid.uuid4().hex[:12]
        with _lock:
            _decisions[did] = dec
            if len(_decisions) > 500:                       # keep memory bounded
                for k in list(_decisions)[:100]:
                    _decisions.pop(k, None)
        if dec.behaviour.value != "allocate":               # nothing to confirm: log now
            audit.record(dec)
        return self._send(_decision_payload(dec, did))

    def _confirm(self, body):
        who = re.sub(r"[^\w .&'-]", "", str(body.get("confirmed_by", ""))).strip()[:40]
        if not who:
            return self._error("Enter your name before confirming.")
        with _lock:
            dec = _decisions.get(str(body.get("id", "")))
        if dec is None:
            return self._error("That decision has expired. Read the request again.", HTTPStatus.NOT_FOUND)
        if dec.confirmed_by:
            return self._error(f"Already confirmed by {dec.confirmed_by}.", HTTPStatus.CONFLICT)
        rec = audit.confirm(dec, who)
        return self._send({"ok": True, "confirmed_by": who, "created_at": rec["created_at"]})


def main():
    port = int(os.environ.get("PORT", "8000"))
    host = os.environ.get("HOST", "0.0.0.0")
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Subcontracting desk on http://{'localhost' if host == '0.0.0.0' else host}:{port}  "
          f"(Claude {'on' if _llm_available() else 'off: regex parser only'})", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()

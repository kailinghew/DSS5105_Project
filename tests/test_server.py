"""Smoke test for the web app: start it on a free port and hit every endpoint."""
import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

from ui.server import Handler


def _server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd, f"http://127.0.0.1:{httpd.server_address[1]}"


def _get(url):
    with urllib.request.urlopen(url) as r:
        return r.status, r.read()


def _post(url, body):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_endpoints(tmp_path, monkeypatch):
    from desk import audit
    monkeypatch.setattr(audit, "LOG", tmp_path / "decisions.jsonl")
    httpd, base = _server()
    try:
        assert _get(base + "/")[0] == 200
        assert b"Subcontracting desk" in _get(base + "/")[1]
        assert len(json.loads(_get(base + "/api/inbox")[1])) == 30
        reg = json.loads(_get(base + "/api/register?category=TOPS&pieces=1500&due=2026-04-13")[1])
        assert sum(r["eligible"] for r in reg["rows"]) == 5

        line = ("R21 [09:33] Chen: ORD-081 — 1500 crewneck sweaters for Harbor Knits, due Apr 13. "
                "Margin is thin on this one — cheapest shop that can still make Apr 13.")
        code, d = _post(base + "/api/handle", {"line": line, "parser": "baseline", "objective": "lateness"})
        assert code == 200 and d["behaviour"] == "allocate" and d["chosen"] == "W5"

        assert _post(base + "/api/confirm", {"id": d["id"], "confirmed_by": ""})[0] == 400
        code, c = _post(base + "/api/confirm", {"id": d["id"], "confirmed_by": "Kai Ling"})
        assert code == 200 and c["confirmed_by"] == "Kai Ling"
        assert _post(base + "/api/confirm", {"id": d["id"], "confirmed_by": "Kai Ling"})[0] == 409
        assert json.loads(_get(base + "/api/log")[1])[0]["confirmed_by"] == "Kai Ling"

        # a bare message (no "R07 [08:23] Name:" prefix) is accepted
        code, d = _post(base + "/api/handle", {"line": "ORD-063, 100 cardigans, back by Apr 29", "sender": "Mei"})
        assert code == 200 and d["behaviour"] == "allocate" and d["request"]["sender"] == "Mei"

        assert _post(base + "/api/handle", {"line": ""})[0] == 400
        assert _post(base + "/api/handle", {"line": "x" * 600})[0] == 400
        assert _post(base + "/api/handle", {"line": "ORD-063", "objective": "nope"})[0] == 400
    finally:
        httpd.shutdown()

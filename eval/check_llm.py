"""
check_llm.py — one live call to Claude Haiku, to prove the setup works before a full run.

    python -m eval.check_llm

Checks the SDK is installed and the key is set (never prints it), sends ONE invented
message (not from the inbox), and shows what Claude extracted, what the validation kept,
the decision, the tokens used and the time taken. Exit code 0 = ready for run_inbox.
"""
from __future__ import annotations

import json
import sys
import time

from agent import llm
from agent.desk_agent import handle
from agent.parse import LLM_SCHEMA, llm_system_prompt, parse_llm

TEST_LINE = ("R99 [11:00] Test: ORD-063, 100 cardigans for Loom & Leaf, needed back by Apr 29. "
             "Keep it away from BudgetWorks.")


def main() -> int:
    print(f"python {sys.version.split()[0]}")
    try:
        import anthropic
        print(f"anthropic SDK {anthropic.__version__}")
    except ImportError:
        print("FAIL: the anthropic package is missing -> pip install -r requirements.txt")
        return 1
    llm._load_dotenv()
    import os
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("FAIL: ANTHROPIC_API_KEY is not set -> copy .env.example to .env and paste your key")
        return 1
    print("API key: set")
    cfg = llm.settings()
    print(f"model {cfg['model']}, effort {cfg.get('effort') or 'default'}, max_tokens {cfg.get('max_tokens')}")

    print(f"\nsending one test message:\n  {TEST_LINE}\n")
    t0 = time.time()
    try:
        raw = llm.call_json(llm_system_prompt(), TEST_LINE, LLM_SCHEMA, use_cache=False)
    except llm.LLMError as e:
        msg = str(e)
        hint = ("the key is wrong or revoked" if "Authentication" in msg else
                "check the model name in config/llm.json" if "NotFound" in msg else
                "no credit on the account, or rate limited" if ("RateLimit" in msg or "credit" in msg.lower()) else
                "network problem (proxy, firewall, offline)" if "Connection" in msg else
                "see the message above")
        print(f"FAIL: {msg}\n -> {hint}")
        return 1
    secs = time.time() - t0
    print("Claude returned:")
    print(json.dumps(raw, indent=2))

    req = parse_llm(TEST_LINE, fallback=False)       # served from the cache just written
    dec = handle(req)
    print(f"\nafter validation: order {req.order_id}, pieces {req.pieces}, due {req.due_date}, "
          f"constraints {[(c.kind.value, c.value, c.imposed_by) for c in req.constraints]}")
    if req.warnings:
        print(f"warnings: {req.warnings}")
    print(f"decision: {dec.behaviour.value} -> {dec.chosen}")
    print(f"reply: {dec.explanation}")

    path = llm.CACHE_DIR / f"{llm.cache_key(cfg['model'], llm_system_prompt(), TEST_LINE, LLM_SCHEMA)}.json"
    rec = json.loads(path.read_text())
    u = rec["usage"]
    print(f"\n{secs:.1f}s, {u['input_tokens']} input + {u['output_tokens']} output tokens, "
          f"effort sent: {rec.get('effort') or 'none'}")

    ok = (req.order_id == "ORD-063" and req.pieces == 100 and str(req.due_date) == "2026-04-29"
          and any(c.value == "W3" for c in req.constraints) and dec.behaviour.value == "allocate"
          and dec.chosen != "W3")
    path.unlink(missing_ok=True)                      # keep the test call out of the eval cache
    print("\nREADY: run  python -m eval.run_inbox --parser llm --show" if ok else
          "\nCHECK: the call worked but the extraction is not what was expected; look at the JSON above")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

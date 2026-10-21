"""
llm.py — the one place the desk talks to an LLM (Claude Haiku 5.5 by default).

    from agent.llm import call_json
    data = call_json(system_prompt, user_text, json_schema)

* Settings live in config/llm.json (model, effort, max_tokens).
* The API key comes from the ANTHROPIC_API_KEY environment variable, or from a .env
  file at the repo root (git-ignored). Never commit a key: the repo is public.
* Every response is cached on disk under eval/llm_cache/, keyed by model + prompt +
  message + schema. Haiku 5.5 does not accept `temperature`, so the cache is what
  makes evaluation runs repeatable. Commit the cache so graders can rerun without a key.
  Changing the prompt or the schema changes the key, so stale answers are never reused.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from desk.data import ROOT

CONFIG = ROOT / "config" / "llm.json"
CACHE_DIR = ROOT / "eval" / "llm_cache"


class LLMError(RuntimeError):
    """The LLM could not give a usable answer (no key, network, refusal, bad JSON)."""


def settings() -> dict:
    return json.loads(CONFIG.read_text())


def _load_dotenv() -> None:
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


_client = None


def _get_client():
    global _client
    if _client is None:
        _load_dotenv()
        if not os.environ.get("ANTHROPIC_API_KEY"):
            raise LLMError("ANTHROPIC_API_KEY is not set (put it in .env at the repo root)")
        try:
            import anthropic
        except ImportError as e:
            raise LLMError("pip install anthropic") from e
        _client = anthropic.Anthropic(max_retries=3, timeout=30.0)
    return _client


def cache_key(model: str, system: str, user: str, schema: dict) -> str:
    blob = json.dumps([model, system, user, schema], sort_keys=True)
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def call_json(system: str, user: str, schema: dict, use_cache: bool = True) -> dict:
    """Ask the model for one JSON object matching `schema` (enforced by the API's
    structured outputs). Raises LLMError on any failure; the caller decides the fallback."""
    cfg = settings()
    model = cfg["model"]
    key = cache_key(model, system, user, schema)
    path = CACHE_DIR / f"{key}.json"
    if use_cache and path.exists():
        return json.loads(path.read_text())["output"]

    client = _get_client()
    output_config = {"format": {"type": "json_schema", "schema": schema}}
    if cfg.get("effort"):
        output_config["effort"] = cfg["effort"]
    try:
        resp = client.messages.create(
            model=model,
            max_tokens=cfg.get("max_tokens", 1024),
            system=system,
            messages=[{"role": "user", "content": user}],
            output_config=output_config,
        )
    except Exception as e:   # network, auth, rate limit after retries, 4xx on bad params
        raise LLMError(f"{type(e).__name__}: {e}") from e

    if resp.stop_reason == "refusal":
        raise LLMError("model refused")
    if resp.stop_reason == "max_tokens":
        raise LLMError("hit max_tokens before finishing the JSON — raise max_tokens in config/llm.json")
    text = next((b.text for b in resp.content if b.type == "text"), None)
    if not text:
        raise LLMError("no text block in response")
    try:
        out = json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"invalid JSON: {text[:200]}") from e

    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "model": model, "user": user, "output": out,
        "usage": {"input_tokens": resp.usage.input_tokens, "output_tokens": resp.usage.output_tokens},
    }, indent=1))
    return out

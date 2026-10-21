# Quick-Response Subcontracting Desk (DSS5105 Track 2)

Takes the dispatch group chat as input and returns, for each request, an eligible
workshop allocation with its reasoning on record. Otherwise it asks a clarifying
question, refuses with the reason and an alternative, says the date is impossible and
lays out the options, or declines to answer.

**Rule of the house:** the LLM handles language only. Every date, cost and queue figure
comes from the deterministic tools in `desk/tools.py`.

## Run it

Python 3.10+, standard library only for the core.

```bash
pip install -r requirements.txt
cp .env.example .env               # then paste your ANTHROPIC_API_KEY into .env (never commit it)

python -m eval.run_inbox --parser llm --show   # Claude Haiku 5.5 parser on the 30 requests
python -m eval.run_inbox --show     # all 30 chat requests, scored against eval/gold_labels.json
python -m eval.run_sim              # every objective vs the 3 baselines + the earliest-finish rule,
                                    # normal and --shock, 10 seeds -> eval/results_sim.csv
python -m pytest -q                 # unit tests (pip install pytest)
pip install streamlit && streamlit run ui/app.py    # starter dispatcher screen
```

## Layout and owners

| Path | What | Owner | Status |
|---|---|---|---|
| `desk/schemas.py` | **The contracts**: ParsedRequest, Candidate, Decision, Objective. Changing one means telling the team | all | done |
| `desk/data.py` | Loads the CSVs and reuses the harness's eligibility rule | [name] | done |
| `desk/tools.py` | The tool layer, with the spec table in its docstring | [name] | done (v1) |
| `desk/allocator.py` | Simulator policy built on the same `allocate()`; the earliest-finish rule to beat | [name] | done (v1) |
| `config/objectives.json` | Objective weights: lateness (primary), fair, defects, robust, hybrid | [name] | done |
| `agent/parse.py` | `parse_llm`: Haiku 5.5 extracts, code validates. `parse_baseline`: regex, no LLM | [name] | built, **not yet run against the API** |
| `agent/llm.py`, `config/llm.json` | API client: structured JSON output, retries, response cache in `eval/llm_cache/` (commit it) | [name] | built |
| `agent/desk_agent.py` | Routes a request to allocate / clarify / refuse / impossible / decline, with templated explanations | [name] | done (v1) |
| `desk/explain.py` | `untraced_numbers()`, the faithfulness check | [name] | done |
| `desk/audit.py` | Append-only JSONL decision log (`logs/decisions.jsonl`) | [name] | done |
| `ui/app.py` | Starter Streamlit screen | [name] | starter |
| `eval/` | Gold labels, inbox scorer, simulator runner | [name] | done (v1) |
| `harness/`, `data/` | Course files, copied unchanged from track2/ | — | — |

## Current numbers (17 Oct, dev only)

**Inbox, regex baseline parser:** 30/30 right behaviour, 30/30 right decision details,
30/30 explanations pass the number-trace check. **This is the development set:** the
parser was written while looking at these 30 lines, so this score is not a result.
Report it as "dev". Score the held-out paraphrase set (to do: `eval/heldout.txt`)
before claiming anything.

**Simulator, 10 seeds:**

| Policy | % late (normal) | % late (shock) | Max share |
|---|---|---|---|
| random | 34% | 38% | 23% |
| earliest-finish rule | 2% | 2% | 26% |
| desk_lateness | 2% | 2% | 26% |
| desk_fair | 8% | 10% | 20% |
| desk_hybrid | 20% | 21% | 40% |

desk_lateness ties the rule. That is expected, and the brief says to report it.

## How the LLM is kept honest

- **Structured outputs:** the API makes the model return JSON matching `LLM_SCHEMA`.
- **No numbers from the model:** any order id, quantity or date the model returns that
  is not written in the message is dropped with a warning, then filled from
  `orders.csv` or asked for.
- **Extraction only:** the model never decides eligibility, ETAs or the allocation.
- **Response cache:** Haiku 5.5 does not accept `temperature`, so every response is
  cached and runs are repeatable. Clear `eval/llm_cache/` to re-query.
- **Fallback:** with no key or no network it falls back to regex, says so on every
  request, and `run_inbox` flags it.
- **No eval examples in the prompt:** its examples are invented, not taken from the
  inbox, and a test enforces this.

## Known limitations (start of the failure-analysis list)

- **Regex parser is brittle.** Any rewording outside its patterns breaks it. That is
  why the LLM parser exists, and the held-out set will show it.
- **The trace check counts tokens.** It confirms each number appears somewhere in the
  tool outputs, not that it is attached to the right fact. An "Apr 8" can pass because
  an 8 appears elsewhere. Tighten it: match (number, field) pairs.
- **The robust (stall-watch) config is slightly worse** than plain lateness. The queue
  jump already steers the rule away from the closed shop.
- **Split explanations** report the split ETA, but the simulator never splits.
  Splits are judged on the inbox only.
- **R14** refuses QuickStitch correctly, but the alternative it offers is late too
  (ORD-103 is also an impossible order). The reply should say both.

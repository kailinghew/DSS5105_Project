# Quick-Response Subcontracting Desk (DSS5105 Track 2)

Takes the dispatch group chat as input and returns, for each request, an eligible
workshop allocation with its reasoning on record. Otherwise it asks a clarifying
question, refuses with the reason and an alternative, says the date is impossible and
lays out the options, or declines to answer.

**Rule of the house:** the LLM handles language only. Every date, cost and queue figure
comes from the deterministic tools in `desk/tools.py`.

## Run it

Python 3.10+. The core and the web app use only the standard library; `anthropic` is
the one runtime dependency.

```bash
pip install -r requirements-dev.txt
cp .env.example .env               # then paste your ANTHROPIC_API_KEY into .env (never commit it)

python -m ui.server                # the dispatcher desk at http://localhost:8000

python -m eval.run_inbox --parser llm --show   # Claude Haiku 5.5 parser on the 30 requests
python -m eval.run_inbox --show     # all 30 chat requests, scored against eval/gold_labels.json
python -m eval.run_sim              # every objective vs the 3 baselines + the earliest-finish rule,
                                    # normal and --shock, 10 seeds -> eval/results_sim.csv
python -m pytest -q                 # 23 tests, no API key needed
```

## The dispatcher desk (UI)

`ui/server.py` (standard-library web server and JSON API) plus `ui/static/` (one HTML
page, one stylesheet, one script, no build step).

- **Requests:** the morning's group chat on the left. Pick a message, or type one, and
  the desk shows:
  - the verdict: send to a shop, ask first, refuse, date impossible, or can't answer;
  - the key numbers;
  - whose instructions it followed;
  - a strip per workshop showing queue wait, making time, expected rework and
    transport against the due date, so you can see why the winner won.
- **Confirm and log:** writes the allocation, with the confirmer's name, to the audit
  log. "Copy reply" gives the text to paste back into the chat. "Read all" triages the
  whole inbox at once.
- **Workshops:** asks "who can take N pieces by date X?" across all 8 shops, and shows
  their profile cards.
- **Decision log:** every decision, newest first.
- **Settings:** the objective and the parser (Claude Haiku or regex) are switchable in
  the top bar. With no API key on the server, Claude is greyed out and regex is used.
- **Safeguards:**
  - The API key never reaches the browser.
  - Messages are capped at 500 characters.
  - Claude calls are capped at 200 per hour, to protect the budget on a public link.

## Deploy (Render, free tier)

**Live demo: https://qr-subcontracting-desk.onrender.com** (deployed 25 Oct 2026 from
`render.yaml` as a Blueprint on a public repository URL).

Render does **not** redeploy on push in this setup. After pushing changes, open the
service in the Render dashboard and choose **Manual Deploy → Deploy latest commit**.
The 30 inbox requests are answered from the committed `eval/llm_cache/`, so the demo
costs nothing for them; a newly typed message makes one live Claude call (about 5 s).

To set it up again from scratch:

1. Push this repo to a **public** GitHub repo (the course requires it).
2. On render.com, choose **New → Blueprint** and pick the repo. `render.yaml` sets up
   one free web service: it runs `pip install -r requirements.txt` and starts
   `python -m ui.server`.
3. When asked, paste the `ANTHROPIC_API_KEY`.
4. The demo link is `https://<service-name>.onrender.com`. Put it on the Sprint 2 first
   slide, and check it opens in a private window.

Free-tier limits worth stating in the report:
- **Sleep:** the service sleeps after 15 minutes without traffic and takes about a
  minute to wake. Open the link a few minutes before presenting or recording.
- **Disk:** the disk is not persistent, so `logs/decisions.jsonl` and new LLM cache
  entries reset on every restart or redeploy.

Hugging Face Docker Spaces were considered, but they now need a paid plan.

## Layout and owners

| Path | What | Owner | Status |
|---|---|---|---|
| `desk/schemas.py` | **The contracts**: ParsedRequest, Candidate, Decision, Objective. Changing one means telling the team | all | done |
| `desk/data.py` | Loads the CSVs and reuses the harness's eligibility rule | [name] | done |
| `desk/tools.py` | The tool layer, with the spec table in its docstring | [name] | done (v1) |
| `desk/allocator.py` | Simulator policy built on the same `allocate()`; the earliest-finish rule to beat | [name] | done (v1) |
| `config/objectives.json` | Objective weights: lateness (primary), fair, defects, robust, hybrid | [name] | done |
| `agent/parse.py` | `parse_llm`: Haiku 5.5 extracts, code validates. `parse_baseline`: regex, no LLM | [name] | done: dev set 30/30, see `agent/CHANGELOG.md` |
| `agent/llm.py`, `config/llm.json` | API client: structured JSON output, retries, response cache in `eval/llm_cache/` (commit it) | [name] | built |
| `agent/desk_agent.py` | Routes a request to allocate / clarify / refuse / impossible / decline, with templated explanations | [name] | done (v1) |
| `desk/explain.py` | `untraced_numbers()`, the faithfulness check | [name] | done |
| `desk/audit.py` | Append-only JSONL decision log (`logs/decisions.jsonl`) | [name] | done |
| `ui/server.py`, `ui/static/` | Dispatcher desk web app + JSON API | [name] | done (v1) |
| `render.yaml` | Free Render deployment | [name] | deployed 25 Oct: https://qr-subcontracting-desk.onrender.com |
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
- **Audit log on Render** is wiped on restart (free tier has no persistent disk).
- **R14** refuses QuickStitch correctly, but the alternative it offers is late too
  (ORD-103 is also an impossible order). The reply should say both.

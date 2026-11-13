# Intake agent (Claude Haiku 5.5): change log

Owner: A. Every change to the LLM parser, with the reason and the effect measured on the
30 development requests (`data/dispatch_requests.txt`). Reports are in `eval/results/`;
Claude's raw answers are in `eval/llm_cache/` (committed, so runs are reproducible).

**Every score here is on the development set.** These are the 30 requests the prompt
was adjusted against. They show the parser works on messages we looked at, not that it
works on new wording. The held-out set (task A4, written by B) is the real test.

## Runs

| Run | Date | Change before the run | Claude (behaviour / decision / faithful) | Regex baseline | Report |
|---|---|---|---|---|---|
| dev | 21 Oct | first live run | 26 / 26 / 30 of 30 | 30 / 30 / 30 | `eval/results/compare_dev.md` |
| dev_v2 | 21 Oct | C2 below | **30 / 30 / 30 of 30** | 30 / 30 / 30 | `eval/results/compare_dev_v2.md` |
| **heldout** | 5 Nov | none: parser frozen at dev_v2 | **30 / 28 / 30 of 30** | 30 / 30 / 30 | `eval/results/compare_heldout.md` |

Cost of one 30-request run (dev_v2): 67,219 input + 2,824 output tokens, about 2,200 input
tokens per message, mostly the system prompt. The single-message check (`eval.check_llm`)
took 5.2 s.

## Changes

**C1. The API rejected the schema** (first live call, `eval.check_llm`).
- Error: 400, `Enum value 'history' does not match declared type ['string','null']`.
- Fix (Copilot): `question_type` is a plain nullable string in the schema. The code keeps
  only `history` or `price` and drops anything else with a warning.
- Test: `test_unsupported_question_type_is_dropped`.

**C2. Claude over-flagged "missing" values** (run `dev`).
- Symptom: for messages naming an order but not its quantity or date (R08, R11, R14, R24),
  Claude listed `pieces` and `due_date` as missing.
- Effect: the desk asked for them instead of refusing the suggested workshop, so 4 of 4
  ineligible-suggestion requests were wrong. Ambiguous requests (R03, R15, R19, R29) had
  the same extra flags but still passed, because asking was right there anyway.
- Cause: the prompt defined missing as "what the sender says is still unknown **or what
  is needed but absent**", and the model took the second half literally.
- Fix: "missing" now means only what the sender says is unknown or to be confirmed; a
  value the message does not mention comes from the order record. Added one invented
  example ("send ORD-210 to SteadyHands"). No inbox line was copied into the prompt;
  `test_prompt_has_no_inbox_lines` checks this.
- Result: 26 → 30 of 30 on the development set.

## Observations kept, not tuned

**R23** "Split it across two shops if that gets it back faster".
- Claude extracts `split_allowed` and also `fastest`; regex extracts only `split_allowed`.
- The decision is the same (the split is chosen either way), and speed is arguably a real
  instruction here.
- Left as is, so as not to tune the prompt to a single development message.
- Watch for it on the held-out set.

## A4: held-out run (5 Nov), the parser's real test

One run on B's 30 reworded requests (`eval/heldout.txt`, frozen 26 Oct), with the parser
frozen at dev_v2: no prompt or code change before or after. All 30 Claude answers are in
`eval/llm_cache/` (the files dated 5 Nov).

- **Behaviour 30/30, faithful 30/30, decision 28/30.** Regex: 30/30/30.
- **R53, R54 (ambiguous) failed on decision.** "The beanies are waiting — which shops can
  take them?" / "The hoodies — get them outside, please." Claude extracted the product
  correctly (`"product": "Beanie"`) but also put `order` in `missing`. `resolve_order()`
  reads `order` in `missing` as "a new order, nothing to match" (needed for R10), so it
  skipped the lookup. The desk still asked which order (right behaviour) but could not
  list the 6 and 5 matching orders, as regex does. Logged as F10 in `eval/failures.md`.
  The prompt already says not to do this when a product is named; the model ignored it
  for product-only references with no customer.
- **R46 (ineligible) passed, with an extra constraint.** "Would Little Loom take ORD-107?"
  Claude also added `prefer_workshop: W4`, the same as the suggestion. No effect on the
  decision; kept as an observation.
- **Not tuned.** Fixing F10 and re-running on this set would turn it into a second
  development set. Any fix is measured on the development set plus new, unseen wording,
  and this held-out score is reported as it is.

Cost of the run: 67,089 input + 2,775 output tokens.

## C3. Order lookup no longer skipped for product-only references (11 Nov)

- **Fix for F10** (`resolve_order`, shared by both parsers): the lookup runs whenever a
  customer or product is named, unless the message itself says the order is new
  ("new rush / order / batch / one / job", "details to follow"). We chose a check on the
  message over a new schema field: a schema change would change every cache key and
  force all 60 Claude answers to be fetched again.
- **No prompt or schema change**, so Claude's cached answers are reused as they are.
- **Re-scored:** dev 30/30/30 (`eval/results/compare_dev_v3.md`); held-out 30/30/30
  (`eval/results/compare_heldout_after_fixes.md`).
- **The held-out headline stays 30/28/30.** This fix was written after seeing R53 and R54
  fail, so the post-fix held-out score is not an unseen test and is reported only as a
  check that the fix works.

## C4. Answers to the desk's own questions (13 Nov)

Every message used to be read on its own, so a short answer to a question ("the
cardigans one" after "6 TrendCart orders match") lost the first message and the desk
asked again. `agent/followup.py` now reads an answer against the question it answers:
an order id, an ordinal ("the second one") or a product/customer that narrows the list
picks the order; a stated date or quantity fills the gap; anything not stated is kept
from the question, and anything still unknown is asked again. The parser (Claude or
regex) only reads the answer line; merging and lookup are plain code. The web app shows
an answer box under every question; the API takes `answers: <question id>`.

- 9 tests in `tests/test_followup.py` + a server round trip; 47 tests in all.
- No prompt or schema change: the inbox scores are unchanged (dev and held-out,
  Claude and regex, 30/30/30). Two-message exchanges are not in either evaluation set;
  scoring them is listed as further work.

## Next

- Score Claude on the failure-log probes R91-R99 (new wording, never used for tuning).

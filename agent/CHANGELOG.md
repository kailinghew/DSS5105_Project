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

## Next

- **A4:** one run on B's held-out set, after which the parser is frozen:
  `python -m eval.compare_parsers --file eval/heldout.txt --labels eval/heldout_labels.json --name heldout`

# Failure log — Quick-Response Subcontracting Desk

Owner: B (Evaluation lead) · started 2026-10-26 for B4 · feeds the final report
(10 cases required; 9 open + 2 resolved below).

For every case: the **input**, the **expected result**, **what the system did**, **why**,
and a **possible fix**. All current cases were reproduced with the deterministic pipeline
(`agent.desk_agent.handle_line` with the regex baseline parser) on 2026-10-26.
"Parser" says which intake parser is affected; Claude's behaviour on the same wording
should be checked at A4.

---

## F1 · "Steer clear of QuickStitch" sends the batch *to* QuickStitch

- **Input** `R91 [12:00] Mei: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. Steer clear of QuickStitch, they're overloaded.`
- **Expected** Exclude QuickStitch (W1); allocate to the next best, GiantWeave (W5, ready about Apr 11).
- **What the system did** Allocated **to QuickStitch**: `Send ORD-010 ... to QuickStitch: ready about Apr 10 ... defect rate 12%.`
- **Why** The regex parser only recognises `away from`, `nothing new to`, `not to`, `avoid`, `except` as exclusion
  cues. "Steer clear of" is not one of them, so the workshop name is read as a *suggestion* and honoured.
- **Possible fix** Broaden the exclusion-cue list (e.g. `steer clear of`, `skip`, `stay away from`, `anything but`,
  `not X`) and add a regression test per cue; confirm Claude already classifies these as `exclude_workshop` at A4.

## F2 · "Skip Nimble Needle" sends the batch *to* Nimble Needle

- **Input** `R92 [12:01] Chen: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. Skip Nimble Needle on this one.`
- **Expected** Exclude Nimble Needle (W6); allocate to QuickStitch (W1, ready about Apr 10).
- **What the system did** Allocated **to Nimble Needle**: `... to Nimble Needle: ready about Apr 11 ... defect rate 5%.`
- **Why** Same as F1: "skip" is not an exclusion cue, so W6 is treated as the sender's suggestion.
- **Possible fix** Same as F1 (one cue list, one test batch).

## F3 · "Anything but BudgetWorks" sends the batch *to* BudgetWorks

- **Input** `R93 [12:02] Ravi: ORD-010 — 1000 cardigans for Cotton Club, due Apr 25. Anything but BudgetWorks.`
- **Expected** Exclude BudgetWorks (W3); allocate to QuickStitch (W1).
- **What the system did** Allocated **to BudgetWorks**: `... to BudgetWorks: ready about Apr 14 ... defect rate 9%.`
- **Why** Same root cause: "anything but" is unrecognised, so W3 becomes the suggestion.
- **Possible fix** Same as F1.

## F4 · "Fewest defects possible" picks the *worst* defect rate

- **Input** `R94 [12:03] Priya: ORD-095 — 800 hoodies for Bright Basics, due Apr 26. Fewest defects possible.`
- **Expected** `lowest_defect_on_time` constraint; choose SteadyHands (W2, defect rate 3%, on time).
- **What the system did** No constraint extracted; earliest ETA won: QuickStitch (W1, **12%** defect).
- **Why** The constraint regexes only match `lowest defect` (and `cheapest`, `fastest`, `split`).
  "Fewest defects" does not match, so the objective (lateness) decides and W1 is earliest.
- **Possible fix** Add `fewest defect` to the lowest-defect pattern; check Claude's reading of the same words at A4.

## F5 · "The new deadline is still to be confirmed" allocates anyway

- **Input** `R95 [12:04] Boss: ORD-066 — the new deadline is still to be confirmed, but line it up.`
- **Expected** `clarify`, flagging `missing: due_date` (the date is explicitly unsettled).
- **What the system did** Allocated against the *old* record date: `... to QuickStitch: ready about Apr 10 vs due Apr 26.`
- **Why** The missing-date regexes only match `confirm the new date`, `date tbc`, `new date after`.
  "Still to be confirmed" is not matched, so the due date is filled silently from `orders.csv`.
- **Possible fix** Broaden the missing-date patterns (`still to be confirmed`, `not set yet`, `date TBD`);
  a wrong silent allocation is worse than an unnecessary question.

## F6 · "The quantity is TBC" allocates the record quantity

- **Input** `R96 [12:05] Mei: ORD-096 — the quantity is TBC, ship Apr 17.`
- **Expected** `clarify`, flagging `missing: pieces`.
- **What the system did** Allocated 1,000 pieces (the record value): `... (1000 pcs, beanie) to Nimble Needle ...`
- **Why** The missing-quantity regex only matches `usual quantit...`; "TBC" is not recognised.
- **Possible fix** Add `qty tbc` / `quantity tbc` to the missing-pieces patterns. (The LLM prompt already lists
  "qty TBC" as an example, so Claude should pass this one.)

## F7 · "Who handled the batch in February?" asks which order instead of declining

- **Input** `R97 [12:06] Chen: Who handled the Maple & Co batch in February?`
- **Expected** `decline` (`question_type: history`): the desk holds no record of past allocations.
- **What the system did** Treated it as an order lookup and asked: `2 open orders match (ORD-083, ORD-093): which one do you mean?`
- **Why** The history regexes only match `which workshop did we` / `did we use`; "Who handled" is unmatched,
  so the customer name resolves to two open orders.
- **Possible fix** Add `who handled` / `who did we use` / `last time` to the history pattern.

## F8 · "Apr 8th" is dropped; the desk uses the record date and misses that the order is impossible

- **Input** `R98 [12:07] Ravi: ORD-017 — 800 cardigans for TrendCart, back by Apr 8th.`
- **Expected** Due Apr 8: the earliest shop finishes Apr 9, so `impossible` with options (1 day late).
- **What the system did** Allocated as if due Apr 10 (the record): `... to QuickStitch: ready about Apr 9 vs due Apr 10.`
- **Why** The date regex stops at the ordinal: `Apr 8th` fails the `(\d{1,2})\b` capture, so no date is parsed
  and `orders.csv`'s due date (Apr 10) is used. The reply then cites the wrong deadline *and* the wrong behaviour.
- **Possible fix** Allow ordinal suffixes in the date regex (`\d{1,2}(?:st|nd|rd|th)?`). Claude extracts Apr 8
  correctly (the digit 8 is in the message), so this is a regex-baseline-only bug — but a dangerous one.

## F9 · "Same quantity as always" asks which order but never asks for the quantity

- **Input** `R99 [12:08] Priya: The TrendCart beanies — same quantity as always, ship by Apr 17.`
- **Expected** `clarify` for **both** the ambiguous order (ORD-096 / ORD-082) *and* the missing quantity.
- **What the system did** Asked only `which one do you mean?` — `missing` contained `order` but not `pieces`.
- **Why** The missing-quantity regex only matches the literal phrase `usual quantit...`; "same quantity as always"
  is the same meaning, different words.
- **Possible fix** Add `same quantity` / `qty as (usual|always|before)` to the missing-pieces patterns.

---

## Resolved

### R1 · Trace check let "Apr 8" pass via the workshop count — **fixed in B3**

- **Input** A reply `ready about Apr 8.` whose facts contain no ETA/due date on the 8th, but do contain
  `n_workshops: 8`.
- **What the system did** `untraced_numbers()` flattened every fact into one number bag, so the 8 from the
  workshop count "traced" the date.
- **Fix** `desk/explain.py` now matches each number to the kind of fact it describes (dates against dates,
  `$` against costs, `%` against defect rates, ...). Test: `tests/test_explain.py::test_a_date_only_traces_to_a_date`.

### R2 · R14 refused QuickStitch but hid that the alternative was late too — **fixed in A3**

- **Input** `R14 [08:59] Boss: QuickStitch for the scarves on ORD-103?`
- **What the system did** Refused W1 (makes TOPS only) and offered an alternative without saying the date was
  unreachable by anyone.
- **Fix** The refusal now says both: "No other workshop can make Apr 4 either" plus the earliest/options block.
  Test: `tests/test_agent_replies.py::test_r14_refuses_and_says_the_date_is_impossible_too`.

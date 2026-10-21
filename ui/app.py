"""
app.py — starter dispatcher screen (UI owner: make it good; UX is 15% of the grade).

    streamlit run ui/app.py

Layout goal: under time pressure the dispatcher sees, in one glance,
the recommendation, the candidates with ETA/cost/defects, and a Confirm button.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT), str(ROOT / "harness")]

import streamlit as st  # noqa: E402

from agent.desk_agent import handle_line  # noqa: E402
from agent.parse import parse_baseline, parse_llm  # noqa: E402
from desk import audit  # noqa: E402
from desk.allocator import load_objective  # noqa: E402

st.set_page_config(page_title="Subcontracting Desk", layout="wide")
st.title("Quick-Response Subcontracting Desk")

inbox = [l for l in (ROOT / "data" / "dispatch_requests.txt").read_text(encoding="utf-8").splitlines()
         if l.strip() and not l.startswith("#")]

with st.sidebar:
    objective = st.selectbox("Objective", ["lateness", "fair", "hybrid", "defects", "robust"])
    use_llm = st.toggle("Parse with Claude Haiku 5.5", value=True)
    picked = st.selectbox("Load from this morning's inbox", ["—"] + inbox)
    st.caption("Today is 2026-04-01. Queues are the 1 April profile cards.")

default = "" if picked == "—" else picked
line = st.text_input("Chat message (format: R31 [10:30] Name: message)", value=default)

if line:
    try:
        dec = handle_line(line, parse_llm if use_llm else parse_baseline,
                          objective=load_objective(objective))
    except ValueError as e:
        st.error(str(e))
        st.stop()

    badge = {"allocate": "✅ Allocate", "clarify": "❓ Need more info", "refuse": "⛔ Refuse",
             "impossible": "⚠️ Can't make the date", "decline": "🚫 Can't answer"}[dec.behaviour.value]
    st.subheader(badge)
    for warn in dec.request.warnings:
        st.warning(warn)
    st.write(dec.explanation)

    if dec.candidates:
        rows = [{"workshop": c.name, "eligible": "yes" if c.eligible else "no: " + "; ".join(c.ineligible_reasons),
                 "excluded by": c.excluded_by or "", "ETA": c.eta_date if c.eligible else "",
                 "on time": ("yes" if c.meets_due else "no") if c.eligible else "",
                 "cost $": c.cost if c.eligible else "", "defect %": round(100 * c.defect_rate),
                 "queue days": c.queue_days, "pick": "◀" if c.workshop_id == dec.chosen else ""}
                for c in sorted(dec.candidates, key=lambda c: (not c.eligible, c.eta_days))]
        st.dataframe(rows, use_container_width=True, hide_index=True)

    if dec.behaviour.value == "allocate":
        who = st.text_input("Confirmed by", value="")
        if st.button("Confirm allocation", disabled=not who):
            audit.confirm(dec, who)
            st.success(f"Logged to {audit.LOG.relative_to(ROOT)}")
    elif st.session_state.get("logged") != line:     # log once per message, not per rerun
        audit.record(dec)
        st.session_state["logged"] = line

    with st.expander("Audit record (JSON)"):
        st.json(dec.to_dict())

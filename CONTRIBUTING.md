# Contributing to agentic-clinic

This is a proof-of-concept repository. Contributions that keep the code illustrative and the architecture intentional are welcome. The goal is always clarity over cleverness.

---

## Before You Start

Read [`implementation_plan.md`](implementation_plan.md) for the workflow design and [`architecture.md`](architecture.md) for the decisions behind it. Contributions that contradict an ADR should include a rationale for superseding it.

---

## Getting Started

```bash
git clone git@github.com:st185229/agentic-clinic.git
cd agentic-clinic

python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python seed_db.py
streamlit run app.py
```

AWS credentials must be active with Bedrock access to `anthropic.claude-3-haiku-20240307-v1:0` in `us-east-1`. See the README for details.

---

## Project Structure

```
graph.py          ← LangGraph workflow — the core; change carefully
tools.py          ← @tool wrappers — isolated from the graph
seed_db.py        ← DB schema + seed data — source of truth for data model
app.py            ← Streamlit UI — three screens: login, patient, doctor
```

**The boundary that matters:** `graph.py` must not import from `app.py`. The graph is UI-agnostic. Tools in `tools.py` must not import from `graph.py`. This separation is what makes the MCP migration in the roadmap mechanical rather than architectural.

---

## Types of Contribution

### Bug fixes
Open an issue first if the bug affects core graph behaviour or data integrity. Small UI fixes can go straight to a PR.

### New features
Check the [`roadmap.md`](roadmap.md) first. If your feature is a roadmap phase, implement it as described (don't skip phases — each phase validates the previous one). If it's a new idea, open an issue to discuss before coding.

### Documentation
All docs live alongside the code. If you change behaviour in `graph.py`, update `CLAUDE.md`, `README.md`, and the relevant section of `architecture.md` in the same PR.

### New ADRs
If you make a non-obvious architectural decision, add an ADR to `architecture.md`. Use the existing format: Status · Context · Decision · Consequences (Positive / Negative / Mitigations).

---

## Code Conventions

**Python version:** 3.9+ (use `from __future__ import annotations` for union type hints)

**No comments explaining what code does** — use clear names instead. Comments are for *why*: a hidden constraint, a non-obvious invariant, a workaround.

**graph.py:** Each node function must return a dict of state updates only — no side effects except `_update_consultation()` (which syncs status to the DB for UI polling). If you add a node, add it to the topology diagram in `architecture.md`.

**tools.py:** Each tool must be stateless and idempotent where possible. Tool descriptions (the docstring) are what the LLM reads to decide when to call the tool — make them precise.

**app.py:** Keep the three screens (`show_login`, `show_patient_view`, `show_doctor_view`) as the top-level structure. Don't add business logic here — it belongs in `graph.py` or `tools.py`.

**seed_db.py:** Any schema change must be reflected in `implementation_plan.md` and the DB schema section of `architecture.md`. The seed data should include at least one case that exercises each edge (emergency, clarification, out-of-stock pharmacy).

---

## Commit Messages

One subject line (imperative, ≤72 chars) + blank line + body if needed.

```
Add check_pharmacy_inventory tool to prescription_agent

Verifies medication stock before finalising the prescription.
Suggests alternatives if the primary medication is out of stock.
The Amoxicillin seed entry is intentionally zero-stock to demo this path.
```

Avoid: "fix bug", "update code", "WIP". Be specific about what changed and why.

---

## Pull Requests

- One concern per PR — don't bundle a graph change with a UI change with a doc update
- Update docs in the same PR as the code change
- PRs that add a new roadmap phase should reference the phase number in the title: `[Phase 1] Move checkpointing to DynamoDB`
- The PR description should note which ADR the change relates to, or include a new ADR if the decision is non-obvious

---

## What Not to Contribute

- **Real patient data** of any kind — the repo is public
- **AWS credentials or secrets** — `.env` is gitignored; use `aws configure` or environment variables
- **Dependencies not in requirements.txt** — open an issue to discuss additions first
- **Features that couple `graph.py` to `app.py`** — the graph must remain UI-agnostic
- **Hardcoded model IDs outside `graph.py`** — model selection lives in `_get_model()`

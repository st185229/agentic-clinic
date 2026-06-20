# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A medical consultation prototype demonstrating a **person-in-the-loop agentic architecture** using LangGraph for orchestration and AWS Bedrock (Claude Haiku 4.5) as the intelligence engine. An AI intake agent collects patient symptoms and history, hands off to a human doctor for diagnosis, then an AI prescription agent closes the loop.

The goal is a proof-of-concept viable for charity hospitals: minimal cost (~$0.001/consultation), zero idle infrastructure, and a clear path to production (MCP, Cognito, DynamoDB checkpointing).

## Current status: POC complete, ready for Phase 1 → Phase 2

The POC is **working end-to-end**. See `demo.md` for a screenshot walkthrough. The next work is **Phase 2** of `roadmap.md` — replacing LangChain `@tool` wrappers with MCP servers. Phase 1 (shared infra) may be done first or skipped if going straight to Phase 2.

---

## Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python seed_db.py   # first time only
streamlit run app.py
```

AWS credentials must be active (`aws configure` or env vars).  
Model: `us.anthropic.claude-haiku-4-5-20251001-v1:0` (cross-region inference profile — the `us.` prefix is required; bare model IDs throw `ValidationException`).

---

## File Structure

| File | Purpose |
|------|---------|
| `graph.py` | LangGraph `StateGraph`: 5 nodes, 2 `interrupt()` calls, `MemorySaver` checkpointer |
| `tools.py` | LangChain `@tool` wrappers: `get_patient_record`, `get_medical_history`, `search_knowledge_base`, `check_pharmacy_inventory`, `record_prescription` |
| `app.py` | Streamlit frontend: login, patient chat, doctor desktop with triage queue |
| `seed_db.py` | Creates `patients.db` with dummy patients, medical history, knowledge base, pharmacy inventory |
| `demo.md` | Screenshot walkthrough of a complete consultation |
| `implementation_plan.md` | Full workflow design, state schema, tools, cost model |
| `architecture.md` | C4 diagrams, LangGraph flowchart, 6 ADRs, tradeoff tables |
| `roadmap.md` | POC-to-production phases with MCP migration detail |
| `CONTRIBUTING.md` | Code conventions, PR guidelines, architectural boundaries |

---

## LangGraph pattern

`ConsultationState` (TypedDict) flows through five nodes. `doctor_review` and `clarification_agent` both call `interrupt()` to pause execution; the graph resumes via `graph.invoke(Command(resume=...), config)`. Checkpointing uses `MemorySaver` (shared across browser tabs via `@st.cache_resource`).

```
intake_agent → [emergency_protocol → END]
             → doctor_review ↔ clarification_agent
             → prescription_agent → END
```

**Invariant:** `graph.py` must not import from `app.py`. `tools.py` must not import from `graph.py`. This separation is what makes the Phase 2 MCP migration mechanical.

---

## Known issues fixed (do not reintroduce)

| Issue | Fix |
|-------|-----|
| `ValidationException: on-demand throughput not supported` | Use `us.anthropic.claude-haiku-4-5-20251001-v1:0` (inference profile), not the bare model ID |
| `ResourceNotFoundException: Legacy model` | Same fix — use the `us.` prefixed inference profile ID |
| `_GeneratorContextManager has no attribute get_next_version` | Use `MemorySaver()`, not `SqliteSaver.from_conn_string()` |
| `TypeError: unsupported operand type for \|` | `from __future__ import annotations` is required at the top of `app.py` and `graph.py` for Python 3.9 |

---

## Phase 2 — What to build next

**Goal:** Replace the four `@tool` wrappers in `tools.py` with MCP server calls. `graph.py` does not change at all.

### What Phase 2 involves

1. **Build MCP servers** — one per data domain:
   - `mcp-patient-records` — serves `get_patient_record`, `get_medical_history`
   - `mcp-knowledge-base` — serves `search_knowledge_base`
   - `mcp-pharmacy` — serves `check_pharmacy_inventory`
   - `mcp-prescription-writer` — serves `record_prescription` (write access, separate IAM role)

2. **Swap tool implementations in `tools.py`** — function signatures stay identical; bodies change from `sqlite3` calls to MCP client calls. The LLM reads tool descriptions (docstrings) to decide when to call them — keep those unchanged.

3. **Add AWS IAM roles** — least-privilege per MCP server (read-only for patient/KB/pharmacy; write for prescription).

4. **Add AWS Verified Permissions (Cedar)** — enforce that the intake agent can only call `get_patient_record` for the `patient_id` in the current session state.

5. **Deploy MCP servers** — Lambda (zero idle cost) or ECS Fargate. The POC can run MCP servers locally as separate processes first.

### MCP server skeleton (Python, `mcp` SDK)

```python
from mcp.server import Server
from mcp.server.stdio import stdio_server
import sqlite3

server = Server("patient-records")

@server.tool()
async def get_patient_record(patient_id: str) -> dict:
    """Retrieve demographic and allergy information for a patient."""
    with sqlite3.connect("patients.db") as conn:
        ...
```

Replace `sqlite3.connect` with `psycopg2` / `boto3` for RDS/DynamoDB in Phase 1+.

### MCP client in tools.py (after Phase 2)

```python
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def get_patient_record(patient_id: str) -> dict:
    async with stdio_client(StdioServerParameters(command="python", args=["mcp_patient_records.py"])) as (r, w):
        async with ClientSession(r, w) as session:
            result = await session.call_tool("get_patient_record", {"patient_id": patient_id})
            return result
```

### What does NOT change in Phase 2

- `graph.py` — zero changes
- Tool names, descriptions, and argument schemas
- `ConsultationState` fields
- `app.py`
- `seed_db.py` schema (MCP servers read the same DB initially)

### References

- `roadmap.md` §Phase 2 — full rationale and security model
- `architecture.md` §ADR-003 — why `@tool` wrappers were chosen for POC and what the swap entails
- `architecture.md` §C4 Level 2 (Production) — target container diagram showing MCP servers in context

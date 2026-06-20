# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A medical consultation prototype demonstrating a **person-in-the-loop agentic architecture** using LangGraph for orchestration and AWS Bedrock (Claude 3 Haiku) as the intelligence engine. An AI intake agent collects patient symptoms and history, hands off to a human doctor for diagnosis, then an AI prescription agent closes the loop.

The goal is a proof-of-concept viable for charity hospitals: minimal cost (~$0.001/consultation), zero idle infrastructure, and a clear path to production (MCP, Cognito, DynamoDB checkpointing).

See `implementation_plan.md` for the full architectural blueprint.

## Setup

```bash
pip install langgraph langchain-aws langchain-core boto3 streamlit langgraph-checkpoint-sqlite
```

AWS credentials must be active (`aws configure` or env vars). Model: `anthropic.claude-3-haiku-20240307-v1:0` in `us-east-1`.

## Run

```bash
python seed_db.py   # first time only
streamlit run app.py
```

## Target File Structure

| File | Purpose |
|------|---------|
| `seed_db.py` | Creates `patients.db` with dummy patients, medical history, knowledge base, and pharmacy inventory |
| `tools.py` | LangChain `@tool` wrappers: `get_patient_record`, `get_medical_history`, `search_knowledge_base`, `check_pharmacy_inventory`, `record_prescription` |
| `graph.py` | LangGraph `StateGraph`: 5 nodes, emergency triage edge, clarification loop, `SqliteSaver` checkpointer |
| `app.py` | Streamlit app: dummy login screen, patient chat view, doctor desktop with triage-sorted alert queue |

## LangGraph Pattern

`ConsultationState` (TypedDict) flows through five nodes. `doctor_review` and `clarification_agent` both call `interrupt()` to pause execution; the graph resumes via `graph.invoke(Command(resume=...), config)`. Checkpointing uses `SqliteSaver` (`checkpoints.db`).

Flow: `intake_agent → [emergency_protocol → END] or [doctor_review ↔ clarification_agent] → prescription_agent → END`

# Roadmap: POC → Production
### agentic-clinic · AWS Bedrock · LangGraph · MCP

---

## Executive Summary

This roadmap describes the path from the current proof-of-concept to a production-grade medical consultation platform. The architecture is deliberately designed so that the core orchestration layer (LangGraph) does not change between phases. Each phase upgrades one infrastructure concern at a time, keeping risk low and the system demonstrable at every stage.

The single most significant architectural transition is **Phase 2: the move from LangChain `@tool` wrappers to Model Context Protocol (MCP) servers**. Everything before it is scaffolding; everything after it scales.

---

## Current State — POC

| Concern | Implementation | Limitation |
|---------|---------------|------------|
| LLM | Claude Haiku 4.5 via Bedrock (`us.anthropic.claude-haiku-4-5-20251001-v1:0`) | ✅ Production-ready as-is |
| Orchestration | LangGraph + `interrupt()` | ✅ Production-ready as-is |
| Checkpointing | `MemorySaver` (in-process) | Lost on restart, single process only |
| Patient data | SQLite (`patients.db`) | Local only, no access control |
| Tool access | LangChain `@tool` wrappers (Python functions) | Tightly coupled, no security boundary |
| Auth | Hardcoded PIN | Placeholder only |
| Frontend | Streamlit (local) | No concurrent users |
| Notifications | Streamlit polling | Not real-time, not mobile |
| Infra | Developer laptop | Cannot be shared or deployed |

**Cost: $0/month** (Bedrock charges only apply when the app is actually running and invoking the model)

---

## North Star — Production Vision

A multi-tenant, HIPAA-eligible consultation platform where:
- Patients connect from any device via a web or mobile interface
- AI agents access patient records, EHRs, and knowledge bases through secured, audited MCP servers
- Doctors receive real-time mobile push notifications and respond via any device
- Every agent action is logged for clinical audit and compliance
- The platform runs 24/7 with zero idle cost (serverless + on-demand Bedrock)

---

## Phases

### Phase 1 — Shared Infrastructure
*Goal: Make the POC accessible to more than one person simultaneously.*

**What changes:**
- Deploy Streamlit on a single small instance (AWS EC2 `t3.micro` or App Runner)
- Move `patients.db` to **Amazon RDS** (PostgreSQL, `db.t3.micro` — ~$15/month)
- Move checkpointing from `MemorySaver` to **`langgraph-checkpoint-aws`** (DynamoDB on-demand — pay per request)
- Add a `.env` file pattern and AWS Secrets Manager reference for credentials

**What stays the same:**
- LangGraph graph topology (all nodes, edges, and interrupts unchanged)
- LangChain `@tool` wrappers (now pointing at RDS instead of SQLite — one line change per tool)
- Streamlit frontend

**Cost estimate:** ~$20–30/month  
**Key milestone:** Doctor and patient can be on different devices

---

### Phase 2 — MCP Server Transition *(the critical inflection point)*
*Goal: Replace tightly coupled `@tool` wrappers with independently deployable, secured MCP servers.*

#### Why this transition matters

In the POC, tools are Python functions that run **inside the agent process**:

```
[LangGraph agent process]
    └── get_patient_record()  ← direct SQLite/RDS call, same process, same credentials
    └── get_medical_history() ← no access control, no audit log
    └── search_knowledge_base()
```

In production, this creates three problems:
1. **Security:** The agent has unrestricted database access. There is no way to enforce that an intake agent can only read records for the current patient, not all patients.
2. **Reuse:** If a second agent type (e.g., a specialist referral agent) needs the same tools, the functions must be duplicated or tightly shared.
3. **Auditability:** There is no independent record of which agent accessed which data and when — a compliance requirement in clinical settings.

**MCP (Model Context Protocol)** solves all three. Each tool becomes a standalone server process with its own identity, access policy, and audit log:

```
[LangGraph agent process]
    └── MCP Client ──► [Patient Records MCP Server]  ← dedicated process
                            └── enforces: agent can only read current patient_id
                            └── logs: every access to CloudWatch
                            └── IAM role: read-only on patients table
    └── MCP Client ──► [Knowledge Base MCP Server]
    └── MCP Client ──► [Prescription MCP Server]     ← write access, separate role
```

**What changes in the LangGraph code:** Nothing in `graph.py`. The node functions remain identical. Only the tool *implementations* in `tools.py` change — from direct DB calls to MCP client calls. This is the architectural payoff of keeping tool definitions separate from the graph.

**What is built:**
- 3 MCP server processes (Patient Records, Knowledge Base, Prescription Writer)
- AWS IAM roles per server (least-privilege)
- **AWS Verified Permissions** (Cedar policies) — rules like: *"intake_agent may call get_patient_record only for the patient_id present in the current session"*
- MCP server deployment on AWS Lambda (event-driven, zero idle cost) or ECS Fargate

**Cost estimate:** ~$5–10/month additional (Lambda invocations are near-zero cost at consultation volumes)  
**Key milestone:** Each tool access is independently authorized and audited

---

### Phase 3 — Authentication & Multi-Tenancy
*Goal: Replace the hardcoded dummy login with real identity management.*

**What changes:**
- **Amazon Cognito** — two user pools: Patients and Doctors
- Cognito JWT tokens replace the hardcoded PIN check in `app.py`
- `patient_id` is derived from the authenticated Cognito identity (not user input)
- Doctor accounts tied to a verified medical license attribute in Cognito
- MCP servers validate the Cognito token on every call, enforcing that a doctor can only see consultations assigned to them
- Multi-tenancy: add `clinic_id` to all tables to support multiple hospital deployments

**Frontend:** Streamlit is replaced with a React or Next.js app, or the Streamlit login screen is proxied behind an AWS Application Load Balancer with Cognito integration.

**Cost estimate:** Cognito is free up to 50,000 MAU; ALB ~$20/month  
**Key milestone:** System is safe to put real patient data into

---

### Phase 4 — Real-Time Notifications
*Goal: Replace the polling refresh button with push notifications to the doctor.*

**What changes:**
- **Amazon SNS + AWS Pinpoint** — when the graph reaches `doctor_review`, publish an SNS message
- Doctor's device (mobile app or browser) receives a push notification: *"New consultation from Patient P001 awaiting review"*
- Patient's browser receives a WebSocket event when prescription is ready (AWS API Gateway WebSocket API)
- The Streamlit polling loop is removed

**Cost estimate:** SNS is near-zero at consultation volumes; API Gateway WebSocket ~$1–2/month  
**Key milestone:** Doctor does not need to keep a browser tab open

---

### Phase 5 — Production Hardening
*Goal: Meet the operational and compliance bar for a clinical deployment.*

| Concern | Solution |
|---------|---------|
| HIPAA eligibility | RDS encryption at rest + in transit; S3 server-side encryption; VPC isolation |
| Audit trail | Every agent action (tool call, interrupt, resume) logged to CloudWatch with session ID |
| State offloading | LangGraph S3 offload for state payloads > 400KB (DynamoDB limit) |
| Parallel sub-agents | Fan-out to specialist agents (cardiology KB, pharmacy interaction checker) before doctor review |
| Observability | LangSmith or CloudWatch dashboards for agent latency, tool call counts, error rates |
| Disaster recovery | Multi-AZ RDS; DynamoDB point-in-time recovery |
| Cost controls | AWS Budgets alert at $50/month; Bedrock model invocation limits per session |

---

## Transition Summary

```
POC (now)
  │  Phase 1: shared infra (RDS + DynamoDB checkpointing)
  │  Phase 2: @tool → MCP servers + Cedar access policies   ← architectural pivot
  │  Phase 3: Cognito auth + multi-tenancy
  │  Phase 4: SNS push + WebSocket real-time
  │  Phase 5: HIPAA hardening + observability
  ▼
Production
```

**What never changes across all phases:** The LangGraph graph topology in `graph.py` — the nodes, edges, conditional routing, and `interrupt()` calls remain identical from POC to production. This is the core architectural bet: invest in getting the workflow right once, and let infrastructure evolve independently.

---

## Cost Projection

| Phase | Monthly AWS Cost | Notes |
|-------|-----------------|-------|
| POC | < $1 | Bedrock tokens only |
| Phase 1 | ~$25 | RDS t3.micro + DynamoDB on-demand |
| Phase 2 | ~$30 | + Lambda MCP servers (near-zero at volume) |
| Phase 3 | ~$50 | + ALB + Cognito (free tier covers most) |
| Phase 4 | ~$55 | + SNS + API Gateway WebSocket |
| Phase 5 | ~$80–120 | + Multi-AZ, S3, CloudWatch, backups |

At 50 consultations/day in full production: **< $120/month total**, or roughly **$0.08 per consultation** — viable for charity hospital deployment with minimal donor subsidy.

---

---

## Beyond Production — Low-Resource Environment Extensions

These are not phases with dependencies on Phase 1–5. They are additive capabilities targeting the specific constraints of charity hospitals in developing regions.

### WhatsApp / SMS Patient Interface

In many low-income communities, patients may not have reliable data connections or the digital literacy for a web app, but they universally use WhatsApp or basic SMS. The Streamlit patient view can be replaced entirely with a **Twilio webhook** — the agent workflow is unchanged because LangGraph's `interrupt()` is agnostic to the channel: the state simply sits in DynamoDB waiting for the next SMS reply, however long that takes.

```
Patient SMS → Twilio webhook → resume graph with Command(resume=message)
                              ← graph responds → Twilio sends reply SMS
```

This also eliminates the need for a frontend deployment entirely for the patient-facing side, dropping infrastructure costs further.

### Voice Note / Audio Intake

Typing complex medical symptoms is difficult for elderly or low-literacy patients. A voice note preprocessing step before the text reaches the intake agent removes this friction with no cost increase at low volumes:

- **AWS Transcribe** — pay-per-second, near-zero cost at consultation volumes; HIPAA-eligible
- **OpenAI Whisper (self-hosted)** — open-source alternative, zero marginal cost, runs on a small EC2 instance

The transcribed text drops into the same `symptoms` field and the rest of the graph runs identically. No graph changes required.

### Native Multilingual Intake *(already implemented in POC)*

Claude Haiku 4.5's native multilingual capability is used in the current POC: the intake agent detects the patient's language and responds in kind while always producing the `intake_summary` in English for the doctor. This bridges communication gaps at zero additional cost — no translation service or separate model is required.

---

## What This Is Not

This roadmap does not cover:
- **EHR integration** (Epic, FHIR) — MCP servers in Phase 2 are the integration point; connectors are additive
- **Video consultation** — out of scope for the agentic workflow; handled by separate WebRTC infrastructure
- **Regulatory approval** (FDA, MHRA for clinical decision support) — legal and compliance process, not an engineering phase
- **Training the foundation model** — Bedrock is used as-is; domain fine-tuning is a separate initiative if needed

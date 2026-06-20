# Implementation Plan: Medical Consultation POC
### AWS Bedrock · LangChain · LangGraph · Human-in-the-Loop

---

## 1. Purpose

This project demonstrates a **person-in-the-loop agentic architecture** for remote medical consultation, targeted at charity hospitals where cost and simplicity are critical.

The premise: AI handles everything that doesn't require a clinician's judgment — patient intake, history retrieval, and prescription recording — while the doctor focuses solely on diagnosis. This reduces the time a patient spends waiting for a doctor and the time a doctor spends on administrative work.

```
Patient ──► AI Intake Agent ──► [Doctor Reviews & Diagnoses] ──► AI Prescription Agent ──► Patient
               (Haiku)              ← human-in-the-loop →              (Haiku)
```

---

## 2. Why LangGraph Instead of Lambda + Bedrock

A Lambda-based approach invokes a model, returns a response, and discards all context. Each call is stateless. This forces the application layer to manually manage conversation history, routing logic, and retry state — rebuilding orchestration that LangGraph provides natively.

| Concern | Lambda + Bedrock | LangGraph + Bedrock |
|---------|-----------------|---------------------|
| State between steps | Application must manage | Built-in typed state (TypedDict) |
| Cyclic workflows | Manual loop logic | First-class graph edges |
| Human handoff | Custom webhook + polling | `interrupt()` primitive |
| Pause & resume | Rebuild from scratch | Checkpoint + resume built-in |
| Multi-agent routing | Custom routing code | Conditional edges |

LangGraph models the workflow as a **directed graph** where nodes are agents or tools and edges encode routing logic. State flows through the graph, is checkpointed at each step, and can be paused mid-execution for human input.

---

## 3. Three-Layer Stack

```
┌─────────────────────────────────────────────────┐
│  LangGraph                                      │  Orchestration
│  StateGraph · nodes · edges · interrupt()       │  (workflow logic, state, routing)
├─────────────────────────────────────────────────┤
│  LangChain AWS  (langchain-aws)                 │  Integration
│  ChatBedrock · @tool wrappers                   │  (model wrappers, tool schemas)
├─────────────────────────────────────────────────┤
│  AWS Bedrock  (claude-haiku-4-5)                 │  Intelligence
│  Foundation model · pay-per-token               │  (reasoning, generation)
└─────────────────────────────────────────────────┘
```

---

## 4. Workflow

### Nodes

| Node | Type | Model | Responsibility |
|------|------|-------|----------------|
| `intake_agent` | AI agent | Haiku | Greet patient, collect symptoms, fetch patient history via tools, produce structured intake summary |
| `doctor_review` | Human interrupt | — | Pause graph; present summary to doctor; resume when doctor submits diagnosis or logs an out-of-band call |
| `prescription_agent` | AI agent | Haiku | Generate prescription from doctor's notes, record it to database, produce patient-facing summary |

### Routing

```
START
  │
  ▼
[intake_agent]  ─── tools: get_patient_record, get_medical_history, search_knowledge_base
  │
  ├─(is_emergency = True)──► [emergency_protocol] ──► END
  │                           immediate red-banner alert, no queue entry
  │
  └─(normal)──► [doctor_review] ◄───────────────────────────────────┐
                      │  interrupt(): graph pauses; doctor queue alert │
                      │                                               │
                      ├─(clarify)──► [clarification_agent] ──────────┘
                      │              interrupt(): waits for patient answer
                      │              patient responds → loops back to doctor_review
                      │
                      └─(diagnose)──► [prescription_agent] ─── tools: record_prescription
                                            │
                                            ▼
                                           END
```

**Conditional edges:**

| From | Condition | Routes to |
|------|-----------|-----------|
| `intake_agent` | `should_escalate()` — checks `is_emergency` | `emergency_protocol` or `doctor_review` |
| `doctor_review` | `should_clarify()` — checks `doctor_clarification_req` | `clarification_agent` or `prescription_agent` |
| `clarification_agent` | fixed edge | `doctor_review` (always loops back) |

### Human-in-the-Loop Detail

LangGraph's `interrupt()` function pauses graph execution at `doctor_review` and serialises the current state to the checkpoint store (`MemorySaver` in POC, DynamoDB in production). The doctor's Streamlit view polls for pending consultations. When the doctor submits, the graph is resumed via `graph.invoke(Command(resume=doctor_notes), config)` — no webhooks, no queues, no custom state management needed.

---

## 5. Graph State

```python
class ConsultationState(TypedDict):
    session_id: str
    patient_id: str
    symptoms: str
    patient_history: dict           # fetched from DB by intake_agent

    intake_summary: str             # structured summary produced for doctor
    is_emergency: bool              # set by intake_agent; triggers emergency triage edge

    doctor_clarification_req: str   # question the doctor wants to ask the patient
    patient_clarification_ans: str  # patient's response; fed back into doctor_review

    doctor_notes: str               # doctor's diagnosis (typed or out-of-band flag)
    prescription: str               # final prescription text

    # "intake" | "emergency" | "awaiting_doctor" | "clarifying" | "prescribing" | "complete"
    status: str
    messages: list[dict]            # full chat history for patient UI
```

---

## 6. Tool Access: LangChain Wrappers (POC) vs. MCP (Production)

### In this POC

Tools are implemented as LangChain `@tool`-decorated Python functions that query a local SQLite database directly:

```python
@tool
def get_patient_record(patient_id: str) -> dict: ...

@tool
def get_medical_history(patient_id: str) -> list[dict]: ...

@tool
def search_knowledge_base(query: str) -> list[dict]: ...

@tool
def record_prescription(session_id: str, prescription: str) -> str: ...
```

These are bound to the Haiku model via `llm.bind_tools([...])`.

### In Production (MCP Path)

The **Model Context Protocol (MCP)** standardises how agents access external systems. Instead of each agent having bespoke API clients, they connect to MCP servers that expose tools over a standard interface.

In production, each `@tool` function above would be replaced by a call to an MCP server:
- A **Patient Records MCP server** wrapping an RDS or DynamoDB patient database
- A **Knowledge Base MCP server** wrapping a vector store (e.g. OpenSearch or Bedrock Knowledge Base)
- Cedar policies (AWS Verified Permissions) ensuring agents only access data the requesting user is authorised to see

The LangGraph nodes would not change — only the tool implementations swap from local SQLite to MCP clients.

---

## 7. Data Model (SQLite — POC)

```sql
patients (
    id TEXT PRIMARY KEY,
    name TEXT, dob TEXT, blood_type TEXT, allergies TEXT
)

medical_history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id TEXT, date TEXT, condition TEXT, treatment TEXT, notes TEXT
)

knowledge_base (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT, content TEXT, category TEXT   -- common conditions, drug interactions
)

consultations (
    session_id TEXT PRIMARY KEY,
    patient_id TEXT, symptoms TEXT,
    intake_summary TEXT, doctor_notes TEXT, prescription TEXT,
    status TEXT, created_at TEXT
)
```

Seeded with 3 dummy patients and sample medical history / knowledge base entries.

---

## 8. Frontend (Streamlit)

Three screens, role-selected at login:

### Login (Dummy)
- Role selector: Patient / Doctor
- Hardcoded PIN entry (illustrates where Cognito / IAM Identity Center would integrate)
- No real authentication — this is a data-protection placeholder only

### Patient View
- Chat bubble interface (patient types symptoms, AI responds)
- Status banner: "Your case is being reviewed by the doctor…"
- Prescription card rendered when workflow completes

### Doctor Desktop
- Alert queue: list of consultations awaiting doctor input, sorted by wait time
- Each row expands to show: intake summary, patient history, AI tool calls made
- Response panel: text area for typed diagnosis + "Submit" button
- "Called patient directly" checkbox — doctor logs an out-of-band call and notes outcome; graph resumes without typed chat
- Queue updates via Streamlit `st.rerun()` polling (no WebSockets needed for POC)

---

## 9. Technology Choices

| Concern | POC Choice | Why | Production Path |
|---------|-----------|-----|-----------------|
| LLM | Claude Haiku 4.5 (Bedrock, `us.` inference profile) | Cheapest capable model; ~$0.001/consultation | Same; upgrade to Sonnet 4 for complex reasoning if needed |
| Orchestration | LangGraph `interrupt()` | Native human-in-the-loop | Same |
| Checkpointing | `MemorySaver` | Zero config; shared across tabs via `@st.cache_resource` | `langgraph-checkpoint-aws` (DynamoDB) |
| Database | SQLite | Zero cost, zero infra | RDS / DynamoDB on-demand |
| Tool access | LangChain `@tool` | Fast to build | MCP servers + Cedar policies |
| Frontend | Streamlit | No JS, Python-native | React or Next.js |
| Auth | Hardcoded dummy | Illustrates the pattern | Amazon Cognito |
| Doctor notification | Streamlit polling | Simple, zero infra | SNS push notification |
| AWS infra | None | Local only | Fargate (app) + DynamoDB + S3 |

---

## 10. Cost Model

| Item | POC | Production (50 consults/day) |
|------|-----|------------------------------|
| Claude Haiku 4.5 | ~$0.001/consult | ~$1.50/month |
| SQLite / DynamoDB | $0 | ~$1–2/month (on-demand) |
| Streamlit / Fargate | $0 (local) | ~$10–15/month (t3.micro) |
| S3 (state offload) | $0 | ~$0.50/month |
| **Total** | **$0** | **< $20/month** |

Bedrock is pay-per-token with no provisioned throughput — there are no idle costs. The stack can be stood up and torn down without any sunk infrastructure cost.

---

## 11. File Structure (Target)

```
bedrocks-with-lang/
├── README.md               ← setup and run instructions
├── implementation_plan.md  ← this document
├── CLAUDE.md               ← Claude Code guidance
├── requirements.txt
├── seed_db.py              ← creates patients.db with dummy data
├── tools.py                ← @tool functions: patient record, history, KB, prescription
├── graph.py                ← LangGraph StateGraph: nodes, edges, interrupt, MemorySaver
└── app.py                  ← Streamlit: login, patient chat, doctor desktop
```

---

## 12. Production Path (Beyond POC)

1. **Auth**: Replace dummy login with Amazon Cognito user pools (separate patient and doctor pools)
2. **Checkpointing**: Swap `MemorySaver` for `langgraph-checkpoint-aws` (DynamoDB-backed)
3. **Database**: Migrate SQLite to RDS (HIPAA-eligible with encryption at rest)
4. **Tools → MCP**: Replace `@tool` wrappers with MCP server processes; add Cedar access policies
5. **Notifications**: Replace Streamlit polling with SNS push → doctor mobile app
6. **Parallel sub-agents**: Fan out to specialist agents (cardiology KB, pharmacy checker) before doctor review
7. **Audit trail**: Every agent action logged to CloudWatch with session IDs for compliance

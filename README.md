# Medical Consultation POC
### AWS Bedrock · LangChain · LangGraph · Human-in-the-Loop

A prototype illustrating a person-in-the-loop agentic architecture for remote medical consultation. An AI agent handles patient intake and prescription recording; a doctor steps in for diagnosis. Built to demonstrate how LangChain, LangGraph, and AWS Bedrock compose into a stateful, interruptible agentic workflow — at a cost viable for charity hospitals.

See [`implementation_plan.md`](implementation_plan.md) for the full architectural blueprint, technology rationale, and production path.

---

## How It Works

```
Patient → AI Intake Agent → [Doctor Reviews] → AI Prescription Agent → Patient
```

1. Patient opens the app, describes symptoms via chat
2. The intake agent fetches patient history from the database and produces a structured summary
3. The graph pauses (`interrupt()`) and queues the case on the doctor's desktop
4. The doctor reviews, types a diagnosis (or logs an out-of-band call), and submits
5. The prescription agent generates and records the prescription; the patient sees it in chat

---

## Setup

### 1. Install dependencies

```bash
pip install langgraph langchain-aws langchain-core boto3 streamlit \
            langgraph-checkpoint-sqlite
```

### 2. Configure AWS credentials

```bash
aws configure
```

Or export environment variables:

```bash
export AWS_ACCESS_KEY_ID=...
export AWS_SECRET_ACCESS_KEY=...
export AWS_DEFAULT_REGION=us-east-1
```

### 3. Enable Bedrock model access

In the [AWS Bedrock console](https://console.aws.amazon.com/bedrock/) → **Model access** → request access to:
- `anthropic.claude-3-haiku-20240307-v1:0` (region: `us-east-1`)

### 4. Seed the database

```bash
python seed_db.py
```

Creates `patients.db` with dummy patients, medical history, and knowledge base entries.

---

## Run

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser.

**Screens:**
- **Login** — select role (Patient / Doctor) and enter a dummy PIN
- **Patient view** — chat with the intake agent, see status updates, receive prescription
- **Doctor desktop** — alert queue of pending consultations, intake summaries, diagnosis submission

---

## File Structure

```
├── README.md               ← this file
├── implementation_plan.md  ← architecture, workflow, cost model, production path
├── CLAUDE.md               ← guidance for Claude Code
├── requirements.txt
├── seed_db.py              ← creates and seeds patients.db
├── tools.py                ← LangChain @tool wrappers (patient record, history, KB, Rx)
├── graph.py                ← LangGraph workflow (nodes, edges, interrupt, checkpointing)
├── app.py                  ← Streamlit frontend (login, patient chat, doctor desktop)
```

---

## Tool Access and MCP

In this POC, tools are LangChain `@tool` functions that query a local SQLite database. This is the fastest path to a working prototype.

In production, each tool would be replaced by a call to an **MCP (Model Context Protocol) server** — a standardised interface that lets agents securely access enterprise systems (patient databases, EHRs, pharmacy systems) without bespoke API integrations per model. AWS Verified Permissions (Cedar policies) would enforce that agents only access data the requesting user is authorised to see.

The LangGraph graph nodes would not change; only the tool implementations swap.

---

## Cost

| Item | Cost |
|------|------|
| Claude 3 Haiku (~2,500 tokens/consultation) | ~$0.001 |
| SQLite (POC) | $0 |
| Streamlit (local) | $0 |
| **Per consultation** | **< $0.01** |

50 consultations/day → **< $20/month** total in production (including DynamoDB + Fargate).

---

## AWS Credentials Note

This project uses AWS Bedrock (pay-per-token). No provisioned throughput is required — there are no idle costs. The stack can be stood up and torn down without any sunk infrastructure cost.

A `.env` file is gitignored. Never commit credentials.

"""
LangGraph medical consultation workflow.

Topology:
    intake_agent
        │
        ├─(emergency)──► emergency_protocol ──► END
        │
        └─(normal)──► doctor_review  ◄──────────────────┐
                           │  [interrupt: waits for doctor]  │
                           ├─(clarify)──► clarification_agent ──┘
                           │              [interrupt: waits for patient]
                           └─(diagnose)──► prescription_agent ──► END
"""

import json
import os
import re
import sqlite3
from typing import Literal, TypedDict

from langchain_aws import ChatBedrock
from langchain_core.messages import HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, StateGraph
from langgraph.types import interrupt

from tools import get_medical_history, get_patient_record, record_prescription, search_knowledge_base

DB_PATH = "patients.db"
CHECKPOINT_DB = "checkpoints.db"


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class ConsultationState(TypedDict):
    session_id: str
    patient_id: str
    symptoms: str
    patient_history: dict

    intake_summary: str
    is_emergency: bool

    doctor_clarification_req: str
    patient_clarification_ans: str

    doctor_notes: str
    prescription: str

    status: str          # intake | emergency | awaiting_doctor | clarifying | prescribing | complete
    messages: list       # rendered in patient chat UI


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

def _get_model():
    return ChatBedrock(
        model_id="anthropic.claude-3-haiku-20240307-v1:0",
        model_kwargs={"temperature": 0.3},
        region_name=os.getenv("AWS_DEFAULT_REGION", "us-east-1"),
    )


# ---------------------------------------------------------------------------
# DB helpers (status sync for the Streamlit polling UI)
# ---------------------------------------------------------------------------

def _update_consultation(session_id: str, **kwargs):
    """Write status/summary fields to the consultations table so the UI can poll."""
    if not kwargs:
        return
    cols = ", ".join(f"{k} = ?" for k in kwargs)
    vals = list(kwargs.values()) + [session_id]
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(f"UPDATE consultations SET {cols} WHERE session_id = ?", vals)


# ---------------------------------------------------------------------------
# Node 1: intake_agent
# ---------------------------------------------------------------------------

INTAKE_SYSTEM = """You are a compassionate AI medical intake assistant.

Your job:
1. Review the patient's reported symptoms.
2. Use the available tools to fetch their patient record and medical history.
3. Search the knowledge base for relevant clinical context.
4. Produce a concise, structured intake summary for the doctor.

Respond ONLY with valid JSON in this exact format (no markdown, no prose):
{
  "intake_summary": "<structured clinical summary for the doctor, 3-6 sentences>",
  "is_emergency": <true if any symptom matches known emergency indicators, otherwise false>,
  "patient_message": "<brief, reassuring message to show the patient while they wait>"
}

Emergency indicators: chest pain with shortness of breath or radiation, stroke symptoms (FAST),
severe bleeding, loss of consciousness, severe allergic reaction, difficulty breathing."""


def intake_agent_node(state: ConsultationState) -> dict:
    llm = _get_model()
    intake_tools = [get_patient_record, get_medical_history, search_knowledge_base]
    llm_with_tools = llm.bind_tools(intake_tools)
    tool_map = {t.name: t for t in intake_tools}

    messages = [
        SystemMessage(content=INTAKE_SYSTEM),
        HumanMessage(content=f"Patient ID: {state['patient_id']}\nSymptoms: {state['symptoms']}"),
    ]

    patient_history = {}
    for _ in range(6):  # cap tool-calling iterations
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not getattr(response, "tool_calls", None):
            break

        for tc in response.tool_calls:
            fn = tool_map.get(tc["name"])
            if fn:
                result = fn.invoke(tc["args"])
                # Cache patient history for state
                if tc["name"] == "get_patient_record" and isinstance(result, dict) and "error" not in result:
                    patient_history.update(result)
                elif tc["name"] == "get_medical_history" and isinstance(result, list):
                    patient_history["history"] = result
                messages.append(ToolMessage(content=json.dumps(result), tool_call_id=tc["id"]))

    # Parse structured JSON response
    content = response.content if hasattr(response, "content") else str(response)
    try:
        json_match = re.search(r"\{.*\}", content, re.DOTALL)
        parsed = json.loads(json_match.group()) if json_match else {}
    except (json.JSONDecodeError, AttributeError):
        parsed = {}

    intake_summary = parsed.get("intake_summary", content)
    is_emergency = bool(parsed.get("is_emergency", False))
    patient_msg = parsed.get(
        "patient_message",
        "Thank you. Your intake is complete. A doctor will review your case shortly."
        if not is_emergency
        else "⚠️ Based on your symptoms, this may require urgent attention."
    )

    new_messages = list(state.get("messages", [])) + [
        {"role": "assistant", "content": patient_msg}
    ]

    status = "emergency" if is_emergency else "awaiting_doctor"
    _update_consultation(
        state["session_id"],
        intake_summary=intake_summary,
        is_emergency=int(is_emergency),
        status=status,
    )

    return {
        "patient_history": patient_history,
        "intake_summary": intake_summary,
        "is_emergency": is_emergency,
        "status": status,
        "messages": new_messages,
    }


# ---------------------------------------------------------------------------
# Node 2: emergency_protocol
# ---------------------------------------------------------------------------

def emergency_protocol_node(state: ConsultationState) -> dict:
    emergency_msg = (
        "🚨 MEDICAL EMERGENCY DETECTED\n\n"
        "Based on your symptoms, this could be a serious medical emergency. "
        "Please call emergency services (999 / 911) immediately. "
        "Do not wait — every minute matters."
    )
    new_messages = list(state.get("messages", [])) + [
        {"role": "emergency", "content": emergency_msg}
    ]
    _update_consultation(state["session_id"], status="emergency")
    return {"status": "emergency", "messages": new_messages}


def should_escalate(state: ConsultationState) -> Literal["emergency_protocol", "doctor_review"]:
    return "emergency_protocol" if state.get("is_emergency") else "doctor_review"


# ---------------------------------------------------------------------------
# Node 3: doctor_review  (human interrupt)
# ---------------------------------------------------------------------------

def doctor_review_node(state: ConsultationState) -> dict:
    context = {
        "session_id": state["session_id"],
        "patient_id": state["patient_id"],
        "intake_summary": state["intake_summary"],
        "patient_history": state["patient_history"],
    }
    if state.get("patient_clarification_ans"):
        context["clarification"] = {
            "question": state["doctor_clarification_req"],
            "answer": state["patient_clarification_ans"],
        }

    # Graph pauses here until Streamlit calls graph.invoke(Command(resume=doctor_input), config)
    doctor_input = interrupt(context)

    if doctor_input.get("action") == "clarify":
        clarification_req = doctor_input["question"]
        _update_consultation(
            state["session_id"],
            doctor_clarification_req=clarification_req,
            status="clarifying",
        )
        return {
            "doctor_clarification_req": clarification_req,
            "patient_clarification_ans": "",
            "status": "clarifying",
        }

    doctor_notes = doctor_input.get("notes", "")
    _update_consultation(
        state["session_id"],
        doctor_notes=doctor_notes,
        doctor_clarification_req="",
        status="prescribing",
    )
    return {
        "doctor_notes": doctor_notes,
        "doctor_clarification_req": "",
        "status": "prescribing",
    }


def should_clarify(state: ConsultationState) -> Literal["clarification_agent", "prescription_agent"]:
    return "clarification_agent" if state.get("doctor_clarification_req") else "prescription_agent"


# ---------------------------------------------------------------------------
# Node 4: clarification_agent  (second human interrupt — waits for patient)
# ---------------------------------------------------------------------------

def clarification_agent_node(state: ConsultationState) -> dict:
    question_msg = f"💬 Your doctor has a question: {state['doctor_clarification_req']}"
    new_messages = list(state.get("messages", [])) + [
        {"role": "doctor_question", "content": question_msg}
    ]

    # Graph pauses here until Streamlit calls graph.invoke(Command(resume=patient_answer), config)
    patient_answer = interrupt({
        "question": state["doctor_clarification_req"],
        "for_patient": True,
    })

    new_messages.append({"role": "patient", "content": patient_answer})
    _update_consultation(
        state["session_id"],
        patient_clarification_ans=patient_answer,
        status="awaiting_doctor",
    )
    return {
        "patient_clarification_ans": patient_answer,
        "status": "awaiting_doctor",
        "messages": new_messages,
    }


# ---------------------------------------------------------------------------
# Node 5: prescription_agent
# ---------------------------------------------------------------------------

PRESCRIPTION_SYSTEM = """You are a medical prescription assistant. Based on the doctor's notes,
generate a clear and professional prescription. Include:
- Medication name, strength, and dosage
- Frequency and duration
- Special instructions (take with food, avoid alcohol, etc.)
- Follow-up recommendation

Output the prescription text only — no JSON, no commentary. Be precise and clinically accurate."""


def prescription_agent_node(state: ConsultationState) -> dict:
    llm = _get_model()
    prescription_tools = [record_prescription]
    llm_with_tools = llm.bind_tools(prescription_tools)
    tool_map = {t.name: t for t in prescription_tools}

    clarification_context = ""
    if state.get("patient_clarification_ans"):
        clarification_context = (
            f"\nDoctor asked: {state['doctor_clarification_req']}"
            f"\nPatient answered: {state['patient_clarification_ans']}"
        )

    messages = [
        SystemMessage(content=PRESCRIPTION_SYSTEM),
        HumanMessage(
            content=(
                f"Doctor's notes: {state['doctor_notes']}{clarification_context}\n"
                f"Patient symptoms: {state['symptoms']}\n"
                f"Patient history: {json.dumps(state['patient_history'])}\n\n"
                f"Generate the prescription and record it using the tool with "
                f"session_id='{state['session_id']}'."
            )
        ),
    ]

    prescription_text = ""
    for _ in range(4):
        response = llm_with_tools.invoke(messages)
        messages.append(response)

        if not getattr(response, "tool_calls", None):
            prescription_text = response.content
            break

        for tc in response.tool_calls:
            fn = tool_map.get(tc["name"])
            if fn:
                args = {**tc["args"], "session_id": state["session_id"]}
                result = fn.invoke(args)
                messages.append(ToolMessage(content=str(result), tool_call_id=tc["id"]))

    if not prescription_text:
        prescription_text = response.content

    new_messages = list(state.get("messages", [])) + [
        {"role": "prescription", "content": prescription_text}
    ]

    _update_consultation(state["session_id"], prescription=prescription_text, status="complete")

    return {
        "prescription": prescription_text,
        "status": "complete",
        "messages": new_messages,
    }


# ---------------------------------------------------------------------------
# Graph assembly
# ---------------------------------------------------------------------------

def build_graph():
    workflow = StateGraph(ConsultationState)

    workflow.add_node("intake_agent",       intake_agent_node)
    workflow.add_node("emergency_protocol", emergency_protocol_node)
    workflow.add_node("doctor_review",      doctor_review_node)
    workflow.add_node("clarification_agent", clarification_agent_node)
    workflow.add_node("prescription_agent", prescription_agent_node)

    workflow.set_entry_point("intake_agent")

    workflow.add_conditional_edges(
        "intake_agent",
        should_escalate,
        {"emergency_protocol": "emergency_protocol", "doctor_review": "doctor_review"},
    )
    workflow.add_edge("emergency_protocol", END)

    workflow.add_conditional_edges(
        "doctor_review",
        should_clarify,
        {"clarification_agent": "clarification_agent", "prescription_agent": "prescription_agent"},
    )
    workflow.add_edge("clarification_agent", "doctor_review")
    workflow.add_edge("prescription_agent", END)

    checkpointer = SqliteSaver.from_conn_string(CHECKPOINT_DB)
    return workflow.compile(checkpointer=checkpointer)

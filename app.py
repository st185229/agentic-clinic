"""
Medical Consultation POC — Streamlit frontend.

Screens:
  1. Login      — dummy role/PIN selector (illustrates where Cognito would plug in)
  2. Patient    — chat interface + status banners + clarification input
  3. Doctor     — alert queue + intake summary + diagnosis / ask-patient actions

Run:  streamlit run app.py
"""

import sqlite3
import uuid
from datetime import datetime

import streamlit as st

from graph import build_graph, DB_PATH
from langgraph.types import Command

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

PATIENT_PIN = "1234"
DOCTOR_PIN  = "doctor"

st.set_page_config(page_title="MediAssist POC", page_icon="🏥", layout="wide")


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

@st.cache_resource
def get_graph():
    return build_graph()


def get_consultation(session_id: str) -> dict | None:
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM consultations WHERE session_id = ?", (session_id,)
        ).fetchone()
    return dict(row) if row else None


def get_pending_consultations() -> list[dict]:
    """Consultations waiting for doctor input."""
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM consultations WHERE status IN ('awaiting_doctor', 'clarifying') ORDER BY created_at ASC"
        ).fetchall()
    return [dict(r) for r in rows]


def create_consultation(session_id: str, patient_id: str, symptoms: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO consultations (session_id, patient_id, symptoms, status, created_at) VALUES (?,?,?,?,?)",
            (session_id, patient_id, symptoms, "intake", datetime.now().isoformat()),
        )


def minutes_waiting(created_at: str) -> str:
    try:
        delta = datetime.now() - datetime.fromisoformat(created_at)
        mins = int(delta.total_seconds() // 60)
        return f"{mins}m" if mins < 60 else f"{mins // 60}h {mins % 60}m"
    except Exception:
        return "—"


# ---------------------------------------------------------------------------
# Screen 1: Login
# ---------------------------------------------------------------------------

def show_login():
    st.title("🏥 MediAssist")
    st.caption("Medical Consultation — Proof of Concept")
    st.divider()

    col, _ = st.columns([1, 2])
    with col:
        st.subheader("Sign in")
        role = st.radio("I am a", ["Patient", "Doctor"], horizontal=True)
        pin = st.text_input("PIN", type="password", placeholder="Enter PIN")

        if role == "Patient":
            patient_id = st.text_input("Patient ID", placeholder="e.g. P001, P002, P003")
        else:
            patient_id = None

        if st.button("Continue", type="primary", use_container_width=True):
            expected_pin = PATIENT_PIN if role == "Patient" else DOCTOR_PIN
            if pin != expected_pin:
                st.error("Incorrect PIN.")
                return
            if role == "Patient" and not patient_id:
                st.error("Please enter your Patient ID.")
                return

            st.session_state["role"] = role.lower()
            st.session_state["patient_id"] = patient_id
            st.rerun()

        st.caption(
            "**Demo credentials** — Patient PIN: `1234` · Doctor PIN: `doctor`  \n"
            "*(This screen is a placeholder for Amazon Cognito authentication.)*"
        )


# ---------------------------------------------------------------------------
# Screen 2: Patient view
# ---------------------------------------------------------------------------

def show_patient_view():
    graph = get_graph()

    st.sidebar.title("🏥 MediAssist")
    st.sidebar.write(f"Patient: **{st.session_state['patient_id']}**")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()

    st.title("My Consultation")

    # ── No active session yet: symptom intake form ──
    if "session_id" not in st.session_state:
        with st.form("start_consultation"):
            st.subheader("Describe your symptoms")
            symptoms = st.text_area(
                "What brings you in today?",
                placeholder="e.g. I have had a headache and fever for two days...",
                height=120,
            )
            submitted = st.form_submit_button("Start Consultation", type="primary")

        if submitted and symptoms.strip():
            session_id = str(uuid.uuid4())
            st.session_state["session_id"] = session_id
            st.session_state["symptoms"] = symptoms.strip()

            create_consultation(session_id, st.session_state["patient_id"], symptoms.strip())

            config = {"configurable": {"thread_id": session_id}}
            initial_state = {
                "session_id": session_id,
                "patient_id": st.session_state["patient_id"],
                "symptoms": symptoms.strip(),
                "patient_history": {},
                "intake_summary": "",
                "is_emergency": False,
                "doctor_clarification_req": "",
                "patient_clarification_ans": "",
                "doctor_notes": "",
                "prescription": "",
                "status": "intake",
                "messages": [{"role": "patient", "content": symptoms.strip()}],
            }
            with st.spinner("AI is reviewing your case and fetching your records…"):
                graph.invoke(initial_state, config)

            st.rerun()
        return

    # ── Active session: read status from DB ──
    session_id = st.session_state["session_id"]
    consultation = get_consultation(session_id)

    if not consultation:
        st.error("Could not find your consultation. Please start a new one.")
        del st.session_state["session_id"]
        st.rerun()
        return

    status = consultation["status"]

    # ── Emergency ──
    if status == "emergency":
        st.error(
            "🚨 **Medical Emergency Detected**\n\n"
            "Based on your symptoms, this could be a serious emergency. "
            "**Please call emergency services (999 / 911) immediately.**\n\n"
            "Do not wait for this consultation — every minute matters."
        )
        st.write(f"**Your symptoms:** {consultation['symptoms']}")
        if st.button("Start a new consultation"):
            del st.session_state["session_id"]
            st.rerun()
        return

    # ── Chat messages so far ──
    _render_messages(consultation)

    # ── Status banners and active inputs ──
    if status == "awaiting_doctor":
        st.info("⏳ Your case is with the doctor. Please wait — they will review shortly.")
        if st.button("🔄 Refresh"):
            st.rerun()

    elif status == "clarifying":
        question = consultation.get("doctor_clarification_req", "")
        if question:
            st.warning(f"💬 **Your doctor has a question:** {question}")
            with st.form("clarification_form"):
                answer = st.text_area("Your answer", height=80)
                if st.form_submit_button("Send Answer", type="primary") and answer.strip():
                    config = {"configurable": {"thread_id": session_id}}
                    with st.spinner("Sending your answer…"):
                        graph.invoke(Command(resume=answer.strip()), config)
                    st.rerun()

    elif status == "prescribing":
        st.info("⏳ The doctor has reviewed your case. Generating your prescription…")
        if st.button("🔄 Refresh"):
            st.rerun()

    elif status == "complete":
        prescription = consultation.get("prescription", "")
        if prescription:
            st.success("✅ Your consultation is complete.")
            with st.container(border=True):
                st.subheader("📋 Prescription")
                st.write(prescription)
        if st.button("Start a new consultation"):
            del st.session_state["session_id"]
            st.rerun()


def _render_messages(consultation: dict):
    """Render patient-facing chat bubbles from the consultations row."""
    st.write(f"**Symptoms you reported:** {consultation['symptoms']}")
    st.divider()

    intake_summary_for_patient = consultation.get("intake_summary", "")
    if intake_summary_for_patient and consultation["status"] != "intake":
        with st.chat_message("assistant"):
            st.write(
                "Thank you. I've reviewed your symptoms and medical history. "
                "Your case has been passed to the doctor for review."
            )


# ---------------------------------------------------------------------------
# Screen 3: Doctor desktop
# ---------------------------------------------------------------------------

def show_doctor_view():
    graph = get_graph()

    st.sidebar.title("🏥 MediAssist")
    st.sidebar.write("**Doctor Portal**")
    if st.sidebar.button("Sign out"):
        st.session_state.clear()
        st.rerun()
    if st.sidebar.button("🔄 Refresh Queue"):
        st.rerun()

    st.title("Doctor Desktop")

    pending = get_pending_consultations()

    if not pending:
        st.success("✅ No pending consultations.")
        st.caption("The queue will update when a patient submits their intake.")
        return

    st.write(f"**{len(pending)} consultation(s) awaiting review:**")

    for c in pending:
        urgency = "🟡"  # standard
        label = f"{urgency} Patient **{c['patient_id']}** · waiting {minutes_waiting(c['created_at'])}"
        with st.expander(label, expanded=(len(pending) == 1)):
            _render_doctor_panel(c, graph)


def _render_doctor_panel(consultation: dict, graph):
    session_id = consultation["session_id"]
    config = {"configurable": {"thread_id": session_id}}
    status = consultation["status"]

    col_left, col_right = st.columns([1, 1])

    # ── Left: patient context ──
    with col_left:
        st.subheader("Intake Summary")
        st.write(consultation.get("intake_summary") or "_Not yet available._")

        if consultation.get("patient_clarification_ans"):
            st.divider()
            st.write("**Follow-up Q&A**")
            st.write(f"**Q:** {consultation['doctor_clarification_req']}")
            st.write(f"**A:** {consultation['patient_clarification_ans']}")

    # ── Right: action panel ──
    with col_right:
        st.subheader("Your Response")

        if status == "clarifying":
            st.info("⏳ Waiting for patient to answer your question…")
            st.write(f"**Question sent:** {consultation.get('doctor_clarification_req', '')}")
            return

        # Submit diagnosis
        with st.form(f"diagnosis_{session_id}"):
            notes = st.text_area(
                "Diagnosis & notes",
                placeholder="e.g. Viral upper respiratory tract infection. No bacterial involvement suspected.",
                height=120,
            )
            out_of_band = st.checkbox("I called the patient directly")
            submit_diagnosis = st.form_submit_button("✅ Submit Diagnosis", type="primary", use_container_width=True)

        if submit_diagnosis:
            if not notes.strip() and not out_of_band:
                st.error("Please enter your diagnosis notes or check the out-of-band box.")
            else:
                final_notes = notes.strip()
                if out_of_band:
                    final_notes = (final_notes + "\n[Doctor called patient directly.]").strip()
                with st.spinner("Submitting diagnosis and generating prescription…"):
                    graph.invoke(
                        Command(resume={"action": "diagnose", "notes": final_notes}),
                        config,
                    )
                st.success("Diagnosis submitted. Prescription is being generated.")
                st.rerun()

        st.divider()

        # Ask patient a clarifying question
        with st.form(f"clarify_{session_id}"):
            question = st.text_input(
                "Ask the patient a question",
                placeholder="e.g. How many days have you had the fever?",
            )
            ask = st.form_submit_button("💬 Ask Patient", use_container_width=True)

        if ask and question.strip():
            with st.spinner("Sending question to patient…"):
                graph.invoke(
                    Command(resume={"action": "clarify", "question": question.strip()}),
                    config,
                )
            st.info("Question sent. Waiting for patient's response.")
            st.rerun()


# ---------------------------------------------------------------------------
# Router
# ---------------------------------------------------------------------------

def main():
    role = st.session_state.get("role")

    if role is None:
        show_login()
    elif role == "patient":
        show_patient_view()
    elif role == "doctor":
        show_doctor_view()


if __name__ == "__main__":
    main()

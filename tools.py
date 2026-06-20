"""
LangChain @tool wrappers over the SQLite patient database.

In production these would be replaced by MCP server calls — the LangGraph
nodes are unchanged; only the tool implementations swap.
"""

import sqlite3
from langchain_core.tools import tool

DB_PATH = "patients.db"


def _db():
    return sqlite3.connect(DB_PATH)


@tool
def get_patient_record(patient_id: str) -> dict:
    """Fetch a patient's basic record: name, date of birth, blood type, and known allergies."""
    with _db() as conn:
        row = conn.execute(
            "SELECT id, name, dob, blood_type, allergies FROM patients WHERE id = ?",
            (patient_id,),
        ).fetchone()
    if not row:
        return {"error": f"No patient found with ID '{patient_id}'"}
    return {"id": row[0], "name": row[1], "dob": row[2], "blood_type": row[3], "allergies": row[4]}


@tool
def get_medical_history(patient_id: str) -> list:
    """Fetch a patient's full medical history, including past conditions and treatments, newest first."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT date, condition, treatment, notes FROM medical_history "
            "WHERE patient_id = ? ORDER BY date DESC",
            (patient_id,),
        ).fetchall()
    return [{"date": r[0], "condition": r[1], "treatment": r[2], "notes": r[3]} for r in rows]


@tool
def search_knowledge_base(query: str) -> list:
    """Search the medical knowledge base for information about conditions, treatments, or drug interactions."""
    with _db() as conn:
        rows = conn.execute(
            "SELECT topic, content, category FROM knowledge_base "
            "WHERE topic LIKE ? OR content LIKE ? LIMIT 5",
            (f"%{query}%", f"%{query}%"),
        ).fetchall()
    if not rows:
        return [{"note": f"No knowledge base entries found for '{query}'"}]
    return [{"topic": r[0], "content": r[1], "category": r[2]} for r in rows]


@tool
def record_prescription(session_id: str, prescription: str) -> str:
    """Record the final prescription for a consultation and mark it as complete."""
    with _db() as conn:
        conn.execute(
            "UPDATE consultations SET prescription = ?, status = 'complete' WHERE session_id = ?",
            (prescription, session_id),
        )
    return f"Prescription recorded for session {session_id}."

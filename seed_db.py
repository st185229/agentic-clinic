"""Creates and seeds patients.db with dummy data for the medical consultation POC."""

import sqlite3

DB_PATH = "patients.db"

SCHEMA = """
DROP TABLE IF EXISTS consultations;
DROP TABLE IF EXISTS knowledge_base;
DROP TABLE IF EXISTS medical_history;
DROP TABLE IF EXISTS patients;

CREATE TABLE patients (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    dob         TEXT,
    blood_type  TEXT,
    allergies   TEXT
);

CREATE TABLE medical_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    patient_id  TEXT NOT NULL,
    date        TEXT,
    condition   TEXT,
    treatment   TEXT,
    notes       TEXT
);

CREATE TABLE knowledge_base (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    topic       TEXT,
    content     TEXT,
    category    TEXT
);

CREATE TABLE consultations (
    session_id                  TEXT PRIMARY KEY,
    patient_id                  TEXT,
    symptoms                    TEXT,
    intake_summary              TEXT DEFAULT '',
    is_emergency                INTEGER DEFAULT 0,
    doctor_clarification_req    TEXT DEFAULT '',
    patient_clarification_ans   TEXT DEFAULT '',
    doctor_notes                TEXT DEFAULT '',
    prescription                TEXT DEFAULT '',
    status                      TEXT DEFAULT 'intake',
    created_at                  TEXT
);
"""

PATIENTS = [
    ("P001", "Alice Thompson", "1985-03-12", "A+", "Penicillin"),
    ("P002", "Bob Patel",      "1972-07-28", "O-", "None"),
    ("P003", "Carol Nguyen",   "1990-11-05", "B+", "Sulfonamides, Aspirin"),
]

MEDICAL_HISTORY = [
    ("P001", "2024-01-15", "Hypertension",       "Lisinopril 10mg daily",             "Well controlled. Monitor BP monthly."),
    ("P001", "2023-06-10", "Seasonal Allergies",  "Cetirizine 10mg as needed",          "Onset spring/autumn."),
    ("P002", "2024-03-20", "Type 2 Diabetes",     "Metformin 500mg twice daily",        "HbA1c 7.1%. Diet and exercise counselled."),
    ("P002", "2023-11-01", "Lower Back Pain",     "Ibuprofen 400mg PRN, Physiotherapy", "Resolved after 6 weeks PT."),
    ("P003", "2024-05-05", "Asthma",              "Salbutamol inhaler PRN, Beclometasone daily", "Mild persistent. Avoid known triggers."),
    ("P003", "2022-09-18", "Appendectomy",        "Surgical removal",                   "Uncomplicated recovery."),
]

KNOWLEDGE_BASE = [
    ("Hypertension",
     "First-line: ACE inhibitors (Lisinopril), ARBs, calcium channel blockers, thiazide diuretics. "
     "Target BP < 130/80 mmHg. Avoid NSAIDs — they raise BP and blunt antihypertensive effect.",
     "Cardiovascular"),

    ("Type 2 Diabetes",
     "First-line: Metformin. Contraindicated if eGFR < 30. Monitor HbA1c every 3 months initially. "
     "Lifestyle modification essential alongside pharmacotherapy.",
     "Endocrinology"),

    ("Penicillin Allergy",
     "Use macrolides (Azithromycin) or fluoroquinolones for respiratory infections. "
     "Cross-reactivity with cephalosporins is ~1-2% — use with caution.",
     "Drug Safety"),

    ("Asthma",
     "Acute: Salbutamol 2.5mg nebulised. Maintenance: inhaled corticosteroids (ICS). "
     "Step up therapy if rescue inhaler used > 2×/week. Avoid beta-blockers.",
     "Respiratory"),

    ("NSAIDs + Hypertension Interaction",
     "NSAIDs can raise blood pressure and reduce efficacy of antihypertensives. "
     "Prefer paracetamol (acetaminophen) as analgesic in hypertensive patients.",
     "Drug Safety"),

    ("Chest Pain — Emergency",
     "Cardiac indicators: pressure/tightness, radiation to left arm or jaw, diaphoresis, nausea, dyspnoea. "
     "Call 999/911 immediately. ECG within 10 minutes. Aspirin 300mg (chewed) if no contraindication.",
     "Emergency"),

    ("Stroke — FAST Protocol",
     "Face drooping, Arm weakness, Speech difficulty → Time to call 999/911. "
     "Thrombolysis within 4.5h of onset (ischaemic only). Do NOT give aspirin before CT confirms no haemorrhage.",
     "Emergency"),

    ("Fever",
     "Antipyretics: Paracetamol 500mg–1g every 4–6h (max 4g/day). Ibuprofen 400mg every 8h with food "
     "(avoid if renal impairment or hypertension). Ensure adequate hydration. Investigate source if > 38.5°C persists beyond 3 days.",
     "General"),

    ("Sulfonamide Allergy",
     "Avoid sulfonamide antibiotics (Trimethoprim-sulfamethoxazole). Cross-reactivity with thiazide diuretics "
     "and sulphonylureas is possible but low risk. Confirm with patient history before prescribing.",
     "Drug Safety"),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    conn.executescript(SCHEMA)
    conn.executemany("INSERT INTO patients VALUES (?,?,?,?,?)", PATIENTS)
    conn.executemany(
        "INSERT INTO medical_history (patient_id, date, condition, treatment, notes) VALUES (?,?,?,?,?)",
        MEDICAL_HISTORY
    )
    conn.executemany(
        "INSERT INTO knowledge_base (topic, content, category) VALUES (?,?,?)",
        KNOWLEDGE_BASE
    )
    conn.commit()
    conn.close()

    print(f"✓ {DB_PATH} created and seeded.")
    print("  Patients: P001 Alice Thompson | P002 Bob Patel | P003 Carol Nguyen")
    print("  Use any of these IDs in the patient login screen.")


if __name__ == "__main__":
    seed()

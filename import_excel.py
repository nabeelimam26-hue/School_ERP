import pandas as pd
import sqlite3

EXCEL_FILE = "students.xlsx"
SHEET_NAME = "section B (2)"   # <<< YOUR REAL SHEET NAME

# LOAD EXCEL
df = pd.read_excel(EXCEL_FILE, sheet_name=SHEET_NAME)
print("Loaded columns:", list(df.columns))

# CONNECT DB
con = sqlite3.connect("students.db")
cur = con.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS students(
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    school_id TEXT,
    sl_no TEXT,
    student_name TEXT,
    father_name TEXT,
    mother_name TEXT,
    sex TEXT,
    dob TEXT,
    aadhaar TEXT,
    mobile TEXT,
    admission_class TEXT,
    admission_no TEXT,
    remarks TEXT
)
""")

# SAFE COLUMN PICK HELPER
def get(row, colname):
    return row[colname] if colname in df.columns else None

for idx, row in df.iterrows():
    cur.execute("""
    INSERT INTO students
    (school_id, sl_no, student_name, father_name, mother_name, sex, dob,
     aadhaar, mobile, admission_class, admission_no, remarks)
    VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (
        get(row, "School_ID"),
        get(row, "SL. NO."),
        get(row, "CANDIDATE_NAME"),
        get(row, "FATHER_NAME"),
        get(row, "MOTHER_NAME"),
        get(row, "SEX / CAST"),
        get(row, "DOB"),
        get(row, "AADHAAR NO."),
        get(row, "MOBILE NO."),
        get(row, "ADMISSION IN CLASS"),
        get(row, "ADMISSION NO."),
        ""
    ))

con.commit()
con.close()

print("IMPORT SUCCESSFUL ✓")

# app.py - Clean, ASCII-only, ready to run
import os
import sqlite3
from datetime import datetime, date, timezone
from flask import (
    Flask, render_template, request, redirect, url_for, flash,
    send_file, jsonify, abort
)
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user, UserMixin
import csv
import io
import hashlib
import pandas as pd
import traceback

# -------------------------
# Configuration
# -------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE_DIR, "students_erp.db")
UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
ALLOWED_EXT = {"png", "jpg", "jpeg"}
os.makedirs(UPLOAD_FOLDER, exist_ok=True)

app = Flask(__name__)
app.secret_key = "replace-with-secure-secret"  # change in production
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = 5 * 1024 * 1024  # 5MB

login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

# -------------------------
# Database helpers
# -------------------------
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def now_ts():
    return datetime.now(timezone.utc).isoformat()

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE,
        password_hash TEXT,
        role TEXT,
        full_name TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS students (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        stable_id TEXT UNIQUE,
        school_id TEXT,
        sl_no TEXT,
        student_name TEXT,
        father_name TEXT,
        mother_name TEXT,
        sex_cast TEXT,
        dob TEXT,
        aadhaar_no TEXT,
        mobile_no TEXT,
        admission_class TEXT,
        admission_no TEXT,
        blood_group TEXT,
        address TEXT,
        category TEXT,
        religion TEXT,
        prev_school TEXT,
        transport_required INTEGER DEFAULT 0,
        medical_issues TEXT,
        emergency_contact TEXT,
        photo TEXT,
        remarks TEXT,
        status TEXT DEFAULT 'active',
        created_at TEXT,
        updated_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        date TEXT,
        status TEXT,
        note TEXT,
        UNIQUE(student_id, date)
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS fees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        year INTEGER,
        month INTEGER,
        amount REAL,
        paid INTEGER DEFAULT 0,
        paid_on TEXT,
        note TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS remarks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        student_id INTEGER,
        author TEXT,
        role TEXT,
        text TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user TEXT,
        action TEXT,
        student_id INTEGER,
        change_summary TEXT,
        timestamp TEXT
    )
    """)

    conn.commit()

    # create default admin if none
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0] == 0:
        pw = hashlib.sha256("admin123".encode()).hexdigest()
        cur.execute(
            "INSERT INTO users (username,password_hash,role,full_name,created_at) VALUES (?,?,?,?,?)",
            ("admin", pw, "admin", "Administrator", now_ts())
        )
        conn.commit()

    conn.close()

init_db()

# -------------------------
# User
# -------------------------
class User(UserMixin):
    def __init__(self, id_, username, role):
        self.id = id_
        self.username = username
        self.role = role

@login_manager.user_loader
def load_user(user_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id,username,role FROM users WHERE id=?", (user_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return None
    return User(r["id"], r["username"], r["role"])

# -------------------------
# Utilities
# -------------------------
def hash_password(plain):
    return hashlib.sha256(plain.encode()).hexdigest()

def stable_id(school_id, admission_no):
    base = f"{(school_id or '').strip()}|{(admission_no or '').strip()}"
    return hashlib.sha1(base.encode()).hexdigest()[:12]

def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXT

def record_audit(user, action, student_id=None, change_summary=""):
    try:
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("INSERT INTO audit_log (user,action,student_id,change_summary,timestamp) VALUES (?,?,?,?,?)",
                    (user, action, student_id, change_summary, now_ts()))
        conn.commit()
    except Exception:
        pass
    finally:
        try:
            conn.close()
        except Exception:
            pass

# -------------------------
# Importer (reads the specific sheet with clean table)
# -------------------------
def import_from_excel(filename="students.xlsx", sheet_name=None):
    """
    Imports student rows from the specified sheet.
    By default uses sheet "section B (2)" which matches the clean table in the user's file.
    """
    path = os.path.join(BASE_DIR, filename)
    if not os.path.exists(path):
        print("Importer: no students.xlsx found, skipping import.")
        return False, "File not found"

    target_sheet = sheet_name or "section B (2)"

    try:
        # header=0 because the sheet tab 'section B (2)' contains header row as first row
        df = pd.read_excel(path, sheet_name=target_sheet, dtype=str, header=0)
    except Exception as e:
        print(f"Importer: failed to read sheet '{target_sheet}': {e}")
        return False, f"Error reading excel sheet '{target_sheet}': {e}"

    if df is None or df.shape[0] == 0:
        print("Importer: sheet empty or not found, nothing to import.")
        return False, "Empty sheet"

    # Normalize: fill NaN and strip whitespace
    df = df.fillna("").astype(str)
    df = df.applymap(lambda v: v.strip() if isinstance(v, str) else v)

    # Map expected headers that appear in your clean sheet
    # Adjust these names if your excel uses slightly different header text
    column_candidates = {
        "school": ["School_ID", "SCHOOL_ID", "School ID", "school_id"],
        "sl": ["SL. NO.", "SL NO", "SL_NO", "S. NO", "Serial", "SL. NO"],
        "name": ["CANDIDATE_NAME", "CANDIDATE NAME", "CANDIDATE_NAME ", "CANDIDATE" , "STUDENT_NAME", "Name"],
        "father": ["FATHER_NAME", "FATHER NAME", "Father"],
        "mother": ["MOTHER_NAME", "MOTHER NAME", "Mother"],
        "sex": ["SEX /  CAST", "SEX /  CAST ", "SEX", "GENDER"],
        "dob": ["DOB", "Date of Birth", "DATE OF BIRTH"],
        "aadhaar": ["AADHAAR NO.", "AADHAR NO", "AADHAAR", "Aadhaar"],
        "mobile": ["MOBILE NO.", "MOBILE NO", "Mobile", "PHONE", "MOBILE"],
        "cls": ["ADMISSION IN CLASS", "ADMISSION IN CLASS", "CLASS"],
        "admno": ["ADMISSION NO.", "ADMISSION NO", "ADMISSIONNO", "Admission No"]
    }

    # choose actual column name present in dataframe
    def choose(candidate_list):
        for c in candidate_list:
            if c in df.columns:
                return c
        return None

    col_map = {}
    for key, cand in column_candidates.items():
        col_map[key] = choose(cand)

    print("Importer: detected column mapping:", col_map)

    conn = get_conn()
    cur = conn.cursor()
    inserted = 0
    updated = 0

    try:
        for _, row in df.iterrows():
            sch = row[col_map["school"]] if col_map.get("school") else ""
            sl = row[col_map["sl"]] if col_map.get("sl") else ""
            name = row[col_map["name"]] if col_map.get("name") else ""
            father = row[col_map["father"]] if col_map.get("father") else ""
            mother = row[col_map["mother"]] if col_map.get("mother") else ""
            sex = row[col_map["sex"]] if col_map.get("sex") else ""
            dob = row[col_map["dob"]] if col_map.get("dob") else ""
            aadhaar = row[col_map["aadhaar"]] if col_map.get("aadhaar") else ""
            mobile = row[col_map["mobile"]] if col_map.get("mobile") else ""
            cls = row[col_map["cls"]] if col_map.get("cls") else ""
            admno = row[col_map["admno"]] if col_map.get("admno") else ""

            # Convert to strings and strip
            sch = str(sch).strip()
            sl = str(sl).strip()
            name = str(name).strip()
            father = str(father).strip()
            mother = str(mother).strip()
            sex = str(sex).strip()
            dob = str(dob).strip()
            aadhaar = str(aadhaar).strip()
            mobile = str(mobile).strip()
            cls = str(cls).strip()
            admno = str(admno).strip()

            sid = stable_id(sch, admno or sl)

            cur.execute("SELECT id FROM students WHERE stable_id=?", (sid,))
            existing = cur.fetchone()
            now = now_ts()

            if existing:
                cur.execute("""
                    UPDATE students SET
                        school_id=?, sl_no=?, student_name=?, father_name=?, mother_name=?,
                        sex_cast=?, dob=?, aadhaar_no=?, mobile_no=?, admission_class=?, admission_no=?, updated_at=?
                    WHERE stable_id=?
                """, (sch, sl, name, father, mother, sex, dob, aadhaar, mobile, cls, admno, now, sid))
                updated += 1
            else:
                cur.execute("""INSERT INTO students (
                    stable_id, school_id, sl_no, student_name, father_name, mother_name,
                    sex_cast, dob, aadhaar_no, mobile_no, admission_class, admission_no,
                    created_at, updated_at
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (sid, sch, sl, name, father, mother, sex, dob, aadhaar, mobile, cls, admno, now, now))
                inserted += 1

        conn.commit()
        print(f"Importer: finished. Inserted={inserted}, Updated={updated}")
        return True, f"Imported (Inserted={inserted}, Updated={updated})"
    except Exception as e:
        conn.rollback()
        print("Importer: fatal error:", e)
        traceback.print_exc()
        return False, f"Import failed: {e}"
    finally:
        conn.close()

# -------------------------
# Authentication routes
# -------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        conn = get_conn()
        cur = conn.cursor()
        cur.execute("SELECT id,password_hash,role FROM users WHERE username=?", (username,))
        r = cur.fetchone()
        conn.close()
        if not r or hashlib.sha256(password.encode()).hexdigest() != r["password_hash"]:
            flash("Invalid username/password", "danger")
            return redirect(url_for("login"))
        user = User(r["id"], username, r["role"])
        login_user(user)
        flash("Logged in", "success")
        return redirect(url_for("home"))
    return render_template("login.html")

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("Logged out", "info")
    return redirect(url_for("login"))

@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        uname = request.form.get("username", "").strip()
        pw = request.form.get("password", "").strip()
        role = request.form.get("role", "teacher")
        full = request.form.get("full_name", "")
        conn = get_conn()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username,password_hash,role,full_name,created_at) VALUES (?,?,?,?,?)",
                        (uname, hash_password(pw), role, full, now_ts()))
            conn.commit()
            flash("User created", "success")
        except Exception as e:
            flash("Could not create user: " + str(e), "danger")
        conn.close()
        return redirect(url_for("login"))
    return render_template("register.html")

# -------------------------
# Dashboard and search
# -------------------------
@app.route("/")
@login_required
def home():
    return redirect(url_for("dashboard"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM students WHERE status='active'")
    total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM students WHERE sex_cast LIKE 'M%' OR sex_cast LIKE 'Male%'")
    boys = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM students WHERE sex_cast LIKE 'F%' OR sex_cast LIKE 'Female%'")
    girls = cur.fetchone()[0]
    cur.execute("SELECT admission_class, COUNT(*) as c FROM students GROUP BY admission_class ORDER BY admission_class")
    per_class = cur.fetchall()
    conn.close()
    return render_template("dashboard.html", total=total, boys=boys, girls=girls, per_class=per_class)

@app.route("/search")
@login_required
def search():
    q = request.args.get("q", "").strip()
    filters = {
        "class": request.args.get("class", "").strip(),
        "gender": request.args.get("gender", "").strip(),
        "status": request.args.get("status", "").strip()
    }
    conn = get_conn()
    cur = conn.cursor()
    where = []
    params = []
    if q:
        qlike = f"%{q}%"
        where.append("(student_name LIKE ? OR father_name LIKE ? OR mother_name LIKE ? OR mobile_no LIKE ? OR admission_no LIKE ?)")
        params += [qlike] * 5
    if filters["class"]:
        where.append("admission_class = ?"); params.append(filters["class"])
    if filters["gender"]:
        where.append("sex_cast LIKE ?"); params.append(filters["gender"] + "%")
    if filters["status"]:
        where.append("status = ?"); params.append(filters["status"])
    sql = "SELECT id,student_name,father_name,admission_class,mobile_no FROM students"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY student_name COLLATE NOCASE LIMIT 500"
    cur.execute(sql, params)
    rows = cur.fetchall()
    conn.close()
    return render_template("search.html", results=rows, query=q, filters=filters)

# -------------------------
# Student CRUD
# -------------------------
@app.route("/student/add", methods=["GET", "POST"])
@login_required
def add_student():
    if request.method == "POST":
        form = request.form
        f = request.files.get("photo")
        photo = None
        if f and allowed_file(f.filename):
            fn = secure_filename(f.filename)
            fn = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{fn}"
            f.save(os.path.join(app.config["UPLOAD_FOLDER"], fn))
            photo = fn
        conn = get_conn()
        cur = conn.cursor()
        sid = stable_id(form.get("school_id", ""), form.get("admission_no", "") or form.get("sl_no", ""))
        now = now_ts()
        cur.execute("""INSERT INTO students (
            stable_id, school_id, sl_no, student_name, father_name, mother_name,
            sex_cast, dob, aadhaar_no, mobile_no, admission_class, admission_no,
            blood_group, address, category, religion, prev_school, transport_required,
            medical_issues, emergency_contact, photo, remarks, status, created_at, updated_at
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (sid, form.get("school_id", ""), form.get("sl_no", ""), form.get("student_name", ""), form.get("father_name", ""), form.get("mother_name", ""),
         form.get("sex_cast", ""), form.get("dob", ""), form.get("aadhaar_no", ""), form.get("mobile_no", ""), form.get("admission_class", ""), form.get("admission_no", ""),
         form.get("blood_group", ""), form.get("address", ""), form.get("category", ""), form.get("religion", ""), form.get("prev_school", ""), 1 if form.get("transport_required") == "on" else 0,
         form.get("medical_issues", ""), form.get("emergency_contact", ""), photo, "", form.get("status", "active"), now, now))
        conn.commit()
        new_id = cur.lastrowid
        conn.close()
        record_audit(current_user.username, "CREATE", new_id, f"Created student {form.get('student_name')}")
        flash("Student added", "success")
        return redirect(url_for("view_student", student_id=new_id))
    return render_template("add_edit.html", mode="add", student=None)

@app.route("/student/<int:student_id>")
@login_required
def view_student(student_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    s = cur.fetchone()
    cur.execute("SELECT * FROM remarks WHERE student_id=? ORDER BY created_at DESC", (student_id,))
    remarks = cur.fetchall()
    cur.execute("SELECT * FROM attendance WHERE student_id=? ORDER BY date DESC LIMIT 30", (student_id,))
    attendance = cur.fetchall()
    cur.execute("SELECT * FROM fees WHERE student_id=? ORDER BY year DESC,month DESC", (student_id,))
    fees = cur.fetchall()
    conn.close()
    return render_template("profile.html", student=s, remarks=remarks, attendance=attendance, fees=fees)

@app.route("/student/<int:student_id>/edit", methods=["GET", "POST"])
@login_required
def edit_student(student_id):
    conn = get_conn()
    cur = conn.cursor()
    if request.method == "POST":
        form = request.form
        f = request.files.get("photo")
        photo = None
        if f and allowed_file(f.filename):
            fn = secure_filename(f.filename)
            fn = f"{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}_{fn}"
            f.save(os.path.join(app.config["UPLOAD_FOLDER"], fn))
            photo = fn
        updates = []
        params = []
        fields = ["school_id","sl_no","student_name","father_name","mother_name","sex_cast","dob","aadhaar_no","mobile_no","admission_class","admission_no","blood_group","address","category","religion","prev_school","medical_issues","emergency_contact","status"]
        for fld in fields:
            updates.append(f"{fld}=?")
            params.append(form.get(fld, ""))
        updates.append("transport_required=?")
        params.append(1 if form.get("transport_required") == "on" else 0)
        updates.append("updated_at=?")
        params.append(now_ts())
        if photo:
            updates.insert(0, "photo=?"); params.insert(0, photo)
        params.append(student_id)
        sql = "UPDATE students SET " + ",".join(updates) + " WHERE id=?"
        cur.execute(sql, params)
        remark_text = form.get("new_remark", "").strip()
        if remark_text:
            cur.execute("INSERT INTO remarks (student_id,author,role,text,created_at) VALUES (?,?,?,?,?)",
                        (student_id, current_user.username, current_user.role, remark_text, now_ts()))
        conn.commit()
        conn.close()
        record_audit(current_user.username, "UPDATE", student_id, f"Edited student {student_id}")
        flash("Student updated", "success")
        return redirect(url_for("view_student", student_id=student_id))
    else:
        cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
        s = cur.fetchone()
        conn.close()
        return render_template("add_edit.html", mode="edit", student=s)

@app.route("/student/<int:student_id>/delete", methods=["POST"])
@login_required
def delete_student(student_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("DELETE FROM students WHERE id=?", (student_id,))
    conn.commit()
    conn.close()
    record_audit(current_user.username, "DELETE", student_id, f"Deleted student {student_id}")
    flash("Student deleted", "info")
    return redirect(url_for("search"))

# -------------------------
# Remarks API
# -------------------------
@app.route("/student/<int:student_id>/remark", methods=["POST"])
@login_required
def add_remark(student_id):
    text = request.form.get("remark", "").strip()
    if not text:
        flash("Empty remark", "warning")
        return redirect(url_for("view_student", student_id=student_id))
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("INSERT INTO remarks (student_id,author,role,text,created_at) VALUES (?,?,?,?,?)",
                (student_id, current_user.username, current_user.role, text, now_ts()))
    conn.commit()
    conn.close()
    record_audit(current_user.username, "REMARK", student_id, text)
    flash("Remark saved", "success")
    return redirect(url_for("view_student", student_id=student_id))

# -------------------------
# Attendance
# -------------------------
@app.route("/attendance/<string:cls>", methods=["GET", "POST"])
@login_required
def attendance_view(cls):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT id,student_name FROM students WHERE admission_class=? ORDER BY student_name", (cls,))
    studs = cur.fetchall()
    if request.method == "POST":
        d = request.form.get("date", date.today().isoformat())
        for sid in request.form.getlist("student_id"):
            status = request.form.get(f"status_{sid}", "absent")
            cur.execute("INSERT OR REPLACE INTO attendance (student_id,date,status,note) VALUES (?,?,?,?)",
                        (sid, d, status, request.form.get(f"note_{sid}", "")))
        conn.commit()
        flash("Attendance saved", "success")
        return redirect(url_for("attendance_view", cls=cls))
    cur.execute("SELECT date FROM attendance ORDER BY date DESC LIMIT 14")
    dates = [r["date"] for r in cur.fetchall()]
    conn.close()
    return render_template("attendance.html", students=studs, dates=dates, cls=cls)

# -------------------------
# Fees
# -------------------------
@app.route("/fees/<int:student_id>", methods=["GET", "POST"])
@login_required
def fees_view(student_id):
    conn = get_conn()
    cur = conn.cursor()
    if request.method == "POST":
        year = int(request.form.get("year", date.today().year))
        month = int(request.form.get("month", date.today().month))
        amount = float(request.form.get("amount", 0))
        cur.execute("INSERT INTO fees (student_id,year,month,amount,paid,note) VALUES (?,?,?,?,?,?)",
                    (student_id, year, month, amount, 0, request.form.get("note", "")))
        conn.commit()
        flash("Fee record added", "success")
        return redirect(url_for("fees_view", student_id=student_id))
    cur.execute("SELECT * FROM fees WHERE student_id=? ORDER BY year DESC,month DESC", (student_id,))
    rows = cur.fetchall()
    conn.close()
    return render_template("fees.html", fees=rows, student_id=student_id)

@app.route("/fees/<int:fee_id>/pay", methods=["POST"])
@login_required
def pay_fee(fee_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("UPDATE fees SET paid=1, paid_on=? WHERE id=?", (now_ts(), fee_id))
    conn.commit()
    conn.close()
    flash("Marked as paid", "success")
    return redirect(request.referrer or url_for("dashboard"))

# -------------------------
# Export / Backup
# -------------------------
@app.route("/export/csv")
@login_required
def export_csv():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students")
    rows = cur.fetchall()
    columns = [d[0] for d in cur.description]
    si = io.StringIO()
    cw = csv.writer(si)
    cw.writerow(columns)
    for r in rows:
        cw.writerow([r[c] for c in columns])
    output = io.BytesIO()
    output.write(si.getvalue().encode("utf-8"))
    output.seek(0)
    return send_file(output, as_attachment=True, download_name="students_export.csv", mimetype="text/csv")

@app.route("/backup")
@login_required
def backup_db():
    if not os.path.exists(DB_PATH):
        abort(404)
    return send_file(DB_PATH, as_attachment=True, download_name=f"students_backup_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}.db")

# -------------------------
# Duplicates
# -------------------------
@app.route("/duplicates")
@login_required
def find_duplicates():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("""
    SELECT a.id as id1, b.id as id2, a.student_name as name1, b.student_name as name2, a.aadhaar_no as aad1, b.aadhaar_no as aad2
    FROM students a JOIN students b ON a.id < b.id
    WHERE (a.aadhaar_no != '' AND a.aadhaar_no = b.aadhaar_no)
       OR (a.mobile_no != '' AND a.mobile_no = b.mobile_no)
       OR (lower(a.student_name) = lower(b.student_name) AND a.dob = b.dob)
    """)
    dup = cur.fetchall()
    conn.close()
    # if template missing, render simple JSON fallback
    try:
        return render_template("duplicates.html", dup=dup)
    except Exception:
        return jsonify([dict(r) for r in dup])

# -------------------------
# API
# -------------------------
@app.route("/api/student/<int:student_id>")
@login_required
def api_student(student_id):
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM students WHERE id=?", (student_id,))
    r = cur.fetchone()
    conn.close()
    if not r:
        return jsonify({"error": "not found"}), 404
    return jsonify(dict(r))

# -------------------------
# Run server
# -------------------------
if __name__ == "__main__":
    # auto-import if students.xlsx present
    try:
        students_xlsx = os.path.join(BASE_DIR, "students.xlsx")
        if os.path.exists(students_xlsx):
            print("Starting importer for students.xlsx ...")
            ok, msg = import_from_excel("students.xlsx", sheet_name="section B (2)")
            print("Importer result:", ok, msg)
    except Exception as e:
        print("Importer startup error:", e)
        traceback.print_exc()

    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))

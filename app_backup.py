import os
import re
import sqlite3
from datetime import datetime
from functools import wraps
from io import BytesIO

from flask import Flask, render_template, request, redirect, url_for, session, flash, send_file, abort
from werkzeug.security import generate_password_hash, check_password_hash
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "change-this-development-secret")
BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DB_PATH = os.path.join(BASE_DIR, "smartresume.db")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
os.makedirs(UPLOAD_DIR, exist_ok=True)
ALLOWED_EXTENSIONS = {"pdf", "docx", "txt", "png", "jpg", "jpeg"}
MAX_UPLOAD_MB = 5


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    with db() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS resumes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            full_name TEXT NOT NULL DEFAULT '',
            email TEXT NOT NULL DEFAULT '',
            phone TEXT NOT NULL DEFAULT '',
            location TEXT NOT NULL DEFAULT '',
            professional_title TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            education TEXT NOT NULL DEFAULT '',
            skills TEXT NOT NULL DEFAULT '',
            experience TEXT NOT NULL DEFAULT '',
            projects TEXT NOT NULL DEFAULT '',
            strength INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS analyses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            filename TEXT NOT NULL,
            strength INTEGER NOT NULL,
            findings TEXT NOT NULL,
            created_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """)


def login_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "info")
            return redirect(url_for("login"))
        return fn(*args, **kwargs)
    return wrapper


def allowed_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def extract_text(path, extension):
    try:
        if extension == "txt":
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        if extension == "pdf":
            from pypdf import PdfReader
            reader = PdfReader(path)
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        if extension == "docx":
            from docx import Document
            doc = Document(path)
            return "\n".join(p.text for p in doc.paragraphs)
        if extension in {"png", "jpg", "jpeg"}:
            from PIL import Image
            import pytesseract
            tesseract_cmd = os.environ.get("TESSERACT_CMD")
            if tesseract_cmd:
                pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
            return pytesseract.image_to_string(Image.open(path))
    except Exception:
        return ""
    return ""


def analyze_resume(text):
    """A transparent rule-based estimate, not an ATS guarantee or an AI assessment."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    low = clean.lower()
    checks = [
        ("Contact information", bool(re.search(r"[\w.+-]+@[\w.-]+\.[A-Za-z]{2,}", clean)) or bool(re.search(r"\b\d{10}\b", clean))),
        ("Professional summary", any(x in low for x in ["summary", "objective", "profile"])),
        ("Education section", "education" in low or "academic" in low),
        ("Skills section", "skills" in low or "technical skills" in low),
        ("Experience or internship", any(x in low for x in ["experience", "internship", "employment"])),
        ("Projects section", "project" in low),
        ("Measurable achievements", bool(re.search(r"\b\d+%|\b\d+\+|\b\d+\s*(users|clients|hours|days|students|projects)\b", low))),
        ("Action-oriented language", any(x in low for x in ["developed", "built", "created", "led", "improved", "implemented", "designed", "managed"])),
        ("Useful length", len(clean.split()) >= 120),
        ("Keyword variety", len(set(re.findall(r"\b[a-zA-Z]{4,}\b", low))) >= 45),
    ]
    score = round(sum(ok for _, ok in checks) / len(checks) * 100)
    findings = []
    for label, ok in checks:
        findings.append({"label": label, "ok": ok})
    suggestions = []
    if not checks[0][1]: suggestions.append(("Add contact details", "Include a professional email address and phone number near the top."))
    if not checks[1][1]: suggestions.append(("Add a short summary", "Write 2–4 lines describing your target role, strengths, and goals."))
    if not checks[2][1]: suggestions.append(("Include education", "Add your degree, institution, graduation year, and relevant coursework."))
    if not checks[3][1]: suggestions.append(("List relevant skills", "Include role-specific technical and soft skills that you can demonstrate."))
    if not checks[4][1]: suggestions.append(("Show experience", "Add internships, volunteering, training, or practical experience where relevant."))
    if not checks[5][1]: suggestions.append(("Add projects", "Describe projects with your contribution, tools used, and outcome."))
    if not checks[6][1]: suggestions.append(("Quantify achievements", "Use numbers where accurate, such as time saved, users served, or accuracy improved."))
    if not checks[7][1]: suggestions.append(("Use strong action verbs", "Start bullet points with verbs such as built, tested, automated, or improved."))
    if not checks[8][1]: suggestions.append(("Add meaningful detail", "A very short resume may need more relevant detail; avoid filler."))
    if not suggestions: suggestions.append(("Keep refining", "Your resume covers these basic checks. Tailor it to each job description."))
    return score, findings, suggestions


def current_user():
    if "user_id" not in session:
        return None
    with db() as con:
        return con.execute("SELECT id, name, email FROM users WHERE id = ?", (session["user_id"],)).fetchone()


@app.context_processor
def inject_user():
    return {"current_user": current_user(), "year": datetime.now().year}


@app.route("/")
def index():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    return render_template("landing.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        if not name or not email or len(password) < 8:
            flash("Enter your name and email, and use a password with at least 8 characters.", "error")
            return render_template("auth.html", mode="register")
        try:
            with db() as con:
                con.execute("INSERT INTO users (name,email,password_hash,created_at) VALUES (?,?,?,?)",
                            (name, email, generate_password_hash(password), datetime.now().isoformat(timespec="seconds")))
            flash("Account created. You can now log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("That email is already registered. Please log in.", "error")
    return render_template("auth.html", mode="register")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        with db() as con:
            user = con.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if user and check_password_hash(user["password_hash"], password):
            session.clear()
            session["user_id"] = user["id"]
            flash("Welcome back!", "success")
            return redirect(url_for("dashboard"))
        flash("Email or password is incorrect.", "error")
    return render_template("auth.html", mode="login")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.route("/dashboard")
@login_required
def dashboard():
    with db() as con:
        resumes = con.execute("SELECT * FROM resumes WHERE user_id=? ORDER BY updated_at DESC LIMIT 5", (session["user_id"],)).fetchall()
        total = con.execute("SELECT COUNT(*) FROM resumes WHERE user_id=?", (session["user_id"],)).fetchone()[0]
        analyzed = con.execute("SELECT COUNT(*) FROM analyses WHERE user_id=?", (session["user_id"],)).fetchone()[0]
        avg = con.execute("SELECT AVG(strength) FROM resumes WHERE user_id=? AND strength > 0", (session["user_id"],)).fetchone()[0]
    return render_template("dashboard.html", resumes=resumes, total=total, analyzed=analyzed,
                           avg=round(avg) if avg else 0)

@app.route("/resume/new", methods=["GET", "POST"])
@app.route("/resume/<int:resume_id>/edit", methods=["GET", "POST"])
@login_required
def resume_form(resume_id=None):
    item = None

    if resume_id:
        with db() as con:
            item = con.execute(
                "SELECT * FROM resumes WHERE id=? AND user_id=?",
                (resume_id, session["user_id"])
            ).fetchone()

        if not item:
            abort(404)

    if request.method == "POST":
        fields = {
            k: request.form.get(k, "").strip()
            for k in [
                "title", "full_name", "email", "phone", "location",
                "professional_title", "summary", "education", "skills",
                "technical_skills", "soft_skills",
                "experience", "projects"
            ]
        }

        if not fields["title"] or not fields["full_name"]:
            flash("Resume title and full name are required.", "error")
            return render_template(
                "resume_form.html", item=item, form=request.form
            )

        combined = " ".join(fields.values())
        strength, _, _ = analyze_resume(combined)
        now = datetime.now().isoformat(timespec="seconds")

        values = (
            fields["title"],
            fields["full_name"],
            fields["email"],
            fields["phone"],
            fields["location"],
            fields["professional_title"],
            fields["summary"],
            fields["education"],
            fields["skills"],
            fields["experience"],
            fields["projects"],
            strength,
            now,
            fields["technical_skills"],
            fields["soft_skills"]
        )

        with db() as con:
            if item:
                con.execute("""
                    UPDATE resumes SET
                    title=?, full_name=?, email=?, phone=?, location=?,
                    professional_title=?, summary=?, education=?, skills=?,
                    experience=?, projects=?, strength=?, updated_at=?,
                    technical_skills=?, soft_skills=?
                    WHERE id=? AND user_id=?
                """, values + (resume_id, session["user_id"]))

                saved_id = resume_id

            else:
                cur = con.execute("""
                    INSERT INTO resumes (
                        title, full_name, email, phone, location,
                        professional_title, summary, education, skills,
                        experience, projects, strength, created_at,
                        updated_at, user_id, technical_skills, soft_skills
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, values[:12] + (
                    now, now, session["user_id"],
                    fields["technical_skills"],
                    fields["soft_skills"]
                ))

                saved_id = cur.lastrowid

        flash("Your resume has been saved.", "success")
        return redirect(url_for("resume_detail", resume_id=saved_id))

    return render_template("resume_form.html", item=item, form=None)

@app.route("/resumes")
@login_required
def resumes():
    with db() as con:
        items = con.execute("SELECT * FROM resumes WHERE user_id=? ORDER BY updated_at DESC", (session["user_id"],)).fetchall()
    return render_template("resumes.html", resumes=items)


@app.route("/resume/<int:resume_id>")
@login_required
def resume_detail(resume_id):
    with db() as con:
        item = con.execute("SELECT * FROM resumes WHERE id=? AND user_id=?", (resume_id, session["user_id"])).fetchone()
    if not item:
        abort(404)
    combined = " ".join(str(item[k] or "") for k in ["title","full_name","email","phone","location","professional_title","summary","education","skills","experience","projects"])
    score, findings, suggestions = analyze_resume(combined)
    return render_template("resume_detail.html", item=item, score=score, findings=findings, suggestions=suggestions)


@app.route("/resume/<int:resume_id>/delete", methods=["POST"])
@login_required
def delete_resume(resume_id):
    with db() as con:
        con.execute("DELETE FROM resumes WHERE id=? AND user_id=?", (resume_id, session["user_id"]))
    flash("Resume deleted.", "info")
    return redirect(url_for("resumes"))


@app.route("/analyze", methods=["GET", "POST"])
@login_required
def analyze():
    result = None
    if request.method == "POST":
        file = request.files.get("resume_file")
        if not file or not file.filename:
            flash("Choose a PDF, DOCX, or TXT resume to upload.", "error")
        elif not allowed_file(file.filename):
            flash("Supported file types are PDF, DOCX, and TXT.", "error")
        else:
            file.stream.seek(0, os.SEEK_END)
            size = file.stream.tell()
            file.stream.seek(0)
            if size > MAX_UPLOAD_MB * 1024 * 1024:
                flash("Please upload a file smaller than 5 MB.", "error")
            else:
                filename = secure_filename(file.filename)
                stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
                path = os.path.join(UPLOAD_DIR, f"{session['user_id']}_{stamp}_{filename}")
                file.save(path)
                ext = filename.rsplit(".", 1)[1].lower()
                text_content = extract_text(path, ext)
                if not text_content.strip():
                    flash("We couldn't read text from that file. Try a text-based PDF, DOCX, or TXT file.", "error")
                else:
                    score, findings, suggestions = analyze_resume(text_content)
                    with db() as con:
                        con.execute("INSERT INTO analyses (user_id,filename,strength,findings,created_at) VALUES (?,?,?,?,?)",
                                    (session["user_id"], filename, score, str([x["label"] for x in findings if x["ok"]]),
                                     datetime.now().isoformat(timespec="seconds")))
                    result = {"filename": filename, "score": score, "findings": findings, "suggestions": suggestions}
    return render_template("analyze.html", result=result)


@app.route("/resume/<int:resume_id>/pdf")
@login_required
def export_pdf(resume_id):
    with db() as con:
        item = con.execute("SELECT * FROM resumes WHERE id=? AND user_id=?", (resume_id, session["user_id"])).fetchone()
    if not item:
        abort(404)
    try:
        from reportlab.lib.pagesizes import letter
        from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib import colors
        from xml.sax.saxutils import escape
    except ImportError:
        flash("PDF export needs reportlab. Run: pip install reportlab", "error")
        return redirect(url_for("resume_detail", resume_id=resume_id))
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=letter, rightMargin=48, leftMargin=48, topMargin=42, bottomMargin=42)
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="NameTitle", parent=styles["Title"], textColor=colors.HexColor("#243b80"), fontSize=21, spaceAfter=6))
    styles.add(ParagraphStyle(name="Section", parent=styles["Heading2"], textColor=colors.HexColor("#4f46e5"), spaceBefore=12, spaceAfter=5))
    story = [Paragraph(escape(item["full_name"]), styles["NameTitle"])]
    contact = " • ".join(x for x in [item["email"], item["phone"], item["location"]] if x)
    if contact: story.append(Paragraph(escape(contact), styles["Normal"]))
    if item["professional_title"]: story.append(Paragraph(escape(item["professional_title"]), styles["Heading3"]))
    sections = [("Professional Summary","summary"),("Education","education"),("Skills","skills"),("Experience","experience"),("Projects","projects")]
    for heading, key in sections:
        value = item[key] or ""
        if value.strip():
            story.append(Paragraph(heading, styles["Section"]))
            for line in value.splitlines():
                if line.strip():
                    story.append(Paragraph(escape(line.strip()), styles["BodyText"]))
                    story.append(Spacer(1, 3))
    doc.build(story)
    buffer.seek(0)
    safe_title = re.sub(r"[^A-Za-z0-9_-]+", "_", item["title"]).strip("_") or "resume"
    return send_file(buffer, as_attachment=True, download_name=f"{safe_title}.pdf", mimetype="application/pdf")



JOB_STOPWORDS = {
    "with","from","that","this","will","your","have","has","are","and","the","for","you","our",
    "their","they","who","what","when","where","which","while","into","over","under","using","use",
    "used","work","working","role","job","team","ability","skills","skill","experience","years",
    "required","preferred","candidate","responsibilities","responsibility","requirements","requirement",
    "including","such","must","should","good","strong","excellent","knowledge","familiarity","plus",
    "about","across","within","more","than","least","other","all","any","both","can","able","degree",
    "related","relevant","based","support","company","position","looking","seeking","join"
}


def keyword_tokens(text):
    words = re.findall(r"[A-Za-z][A-Za-z0-9+#.-]{1,}", (text or "").lower())
    return {w.strip(".-") for w in words if len(w.strip(".-")) > 2 and w.strip(".-") not in JOB_STOPWORDS}


@app.route("/tailor", methods=["GET", "POST"])
@login_required
def tailor_resume():
    with db() as con:
        saved_resumes = con.execute(
            "SELECT id, title, full_name, professional_title, summary, education, skills, experience, projects, email, phone, location "
            "FROM resumes WHERE user_id=? ORDER BY updated_at DESC",
            (session["user_id"],)
        ).fetchall()

    result = None
    if request.method == "POST":
        action = request.form.get("action", "analyze")
        if action == "save":
            try:
                resume_id = int(request.form.get("resume_id", "0"))
            except ValueError:
                resume_id = 0
            with db() as con:
                original = con.execute("SELECT * FROM resumes WHERE id=? AND user_id=?",
                                       (resume_id, session["user_id"])).fetchone()
                if not original:
                    flash("Please select one of your saved resumes.", "error")
                    return redirect(url_for("tailor_resume"))
                title = request.form.get("tailored_title", "").strip() or f"Tailored - {original['title']}"
                summary = request.form.get("tailored_summary", "").strip()
                skills = request.form.get("tailored_skills", "").strip()
                now = datetime.now().isoformat(timespec="seconds")
                con.execute("""INSERT INTO resumes
                    (user_id,title,full_name,email,phone,location,professional_title,summary,education,skills,experience,projects,strength,created_at,updated_at)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (session["user_id"], title, original["full_name"], original["email"], original["phone"],
                     original["location"], original["professional_title"], summary, original["education"], skills,
                     original["experience"], original["projects"], original["strength"], now, now))
                new_id = con.execute("SELECT last_insert_rowid()").fetchone()[0]
            flash("A tailored copy was saved. Review it carefully before applying.", "success")
            return redirect(url_for("resume_detail", resume_id=new_id))

        try:
            resume_id = int(request.form.get("resume_id", "0"))
        except ValueError:
            resume_id = 0
        selected = next((r for r in saved_resumes if r["id"] == resume_id), None)
        if not selected:
            flash("First create and save a resume, then select it here.", "error")
        else:
            req_text = request.form.get("requirements_text", "").strip()
            uploaded = request.files.get("requirements_file")
            if uploaded and uploaded.filename:
                if not allowed_file(uploaded.filename):
                    flash("Upload a PDF, DOCX, TXT, PNG, JPG, or JPEG requirement file.", "error")
                    return render_template("tailor.html", resumes=saved_resumes, result=None, selected_id=resume_id)
                uploaded.stream.seek(0, os.SEEK_END)
                size = uploaded.stream.tell()
                uploaded.stream.seek(0)
                if size > MAX_UPLOAD_MB * 1024 * 1024:
                    flash("Please upload a requirement file smaller than 5 MB.", "error")
                    return render_template("tailor.html", resumes=saved_resumes, result=None, selected_id=resume_id)
                safe_name = secure_filename(uploaded.filename)
                ext = safe_name.rsplit(".", 1)[1].lower()
                stamp = datetime.now().strftime("%Y%m%d%H%M%S%f")
                temp_path = os.path.join(UPLOAD_DIR, f"req_{session['user_id']}_{stamp}_{safe_name}")
                uploaded.save(temp_path)
                req_text = extract_text(temp_path, ext)
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
                if not req_text.strip() and ext in {"png", "jpg", "jpeg"}:
                    flash("Image text could not be read. Install Tesseract OCR and try a clear image.", "error")
                elif not req_text.strip():
                    flash("We couldn't extract text from that file. Try a text-based PDF, DOCX, or TXT file.", "error")
            if req_text:
                resume_text = " ".join(str(selected[k] or "") for k in
                                       ["professional_title","summary","education","skills","experience","projects"])
                req_words = keyword_tokens(req_text)
                resume_words = keyword_tokens(resume_text)
                matched = sorted(req_words & resume_words)
                missing = sorted(req_words - resume_words, key=lambda x: (-len(x), x))[:18]
                score = round((len(req_words & resume_words) / max(1, len(req_words))) * 100)
                summary = (selected["summary"] or "").strip()
                if not summary:
                    summary = f"{selected['professional_title'] or 'Professional'} with relevant strengths for the target role."
                emphasis = ", ".join(matched[:6])
                if emphasis:
                    addition = f" Relevant strengths for this role include: {emphasis}."
                    if addition.lower() not in summary.lower():
                        summary = summary.rstrip(". ") + "." + addition
                tips = []
                if missing:
                    tips.append("Review the missing terms and add only those that truthfully match your skills or experience.")
                if not selected["projects"]:
                    tips.append("Consider adding a relevant project with your contribution, tools, and outcome.")
                if not selected["experience"]:
                    tips.append("If you are a student or fresher, relevant coursework, internships, volunteering, and academic projects can show practical ability.")
                tips.append("Use the company's wording naturally where accurate; never add skills you do not have.")
                result = {
                    "resume_id": selected["id"], "resume_title": selected["title"],
                    "score": score, "matched": matched[:18], "missing": missing,
                    "tailored_summary": summary, "tailored_skills": selected["skills"] or "",
                    "tailored_title": f"{selected['title']} - Tailored", "tips": tips
                }
            elif not (uploaded and uploaded.filename):
                flash("Paste the company's requirements or upload a requirement file/image.", "error")

    selected_id = result["resume_id"] if result else request.form.get("resume_id", "")
    return render_template("tailor.html", resumes=saved_resumes, result=result, selected_id=selected_id)



@app.errorhandler(404)
def not_found(_):
    return render_template("404.html"), 404


if __name__ == "__main__":
    init_db()
    app.run(debug=True)

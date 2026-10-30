# SmartResume — Flask + SQLite3

A student-friendly resume builder inspired by the supplied SmartResume UI reference. It includes registration/login, a personal dashboard, resume creation/editing, SQLite persistence, resume strength checks, upload analysis, and PDF export.

## Run on Windows

1. Install Python 3.10 or newer.
2. Open PowerShell in this folder.
3. Create and activate a virtual environment:

   ```powershell
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   ```

4. Install dependencies:

   ```powershell
   pip install -r requirements.txt
   ```

5. Start the app:

   ```powershell
   python app.py
   ```

6. Open http://127.0.0.1:5000 in your browser and create an account.

The SQLite database (`smartresume.db`) is created automatically on first run. Uploaded resume files are saved in `uploads/`.

## Features
- Registration and login with password hashing.
- User-specific dashboard and saved resumes.
- Create/edit/delete resume records in SQLite3.
- Upload PDF, DOCX, or TXT resumes for a basic resume checklist.
- Match a saved resume against company job requirements pasted as text or uploaded as PDF, DOCX, TXT, PNG, JPG, or JPEG.
- Review keyword overlap, matching/missing terms, edit a suggested summary, and save a separate tailored resume copy.
- Download a saved resume as a PDF.
- Site-wide Resume Atelier visual system with navy workspace navigation, clean white panels, refined purple accents, and a live resume preview with five selectable themes.

## Important notes
- The strength score is a transparent rule-based checklist, not a real AI model, official ATS score, or guarantee of hiring outcomes.
- Text-based PDFs work best; scanned/image-only PDFs may not have extractable text.
- This is a local learning/demo project. Before deployment, set a strong `SECRET_KEY`, disable Flask debug mode, add CSRF protection, validate uploads more strictly, and configure secure storage and deletion policies.
- Uploaded files can contain private information. Do not commit `smartresume.db`, `uploads/`, or secrets to a public Git repository.


## Company requirement file/image matching
Open **Match Job Requirements** from the left sidebar, select a saved resume, then paste a job description or upload a requirement file. The app compares words in the job requirements with your resume and shows matching terms, missing terms, and a suggested summary. You can edit the suggestion and save a separate tailored copy; your original resume remains unchanged.

For image uploads (PNG/JPG/JPEG), install the Tesseract OCR application in Windows as well as the Python packages. If Tesseract is not on PATH, set the `TESSERACT_CMD` environment variable to the full path of `tesseract.exe`, for example:

```powershell
$env:TESSERACT_CMD = "C:\Program Files\Tesseract-OCR\tesseract.exe"
```

Image OCR requires a clear image. PDF/DOCX/TXT are generally more reliable. The keyword match is a basic heuristic, not an AI model or official ATS score, and it must not be used to invent skills or experience.


## Resume Atelier update
The Create/Edit Resume page now includes a live A4-style preview, Modern/Classic/Minimal/Technical/Executive themes, and responsive styling. The existing Flask POST route saves resume fields to SQLite, so existing resume records, resume-strength analysis, PDF export, job matching, login, and dashboard remain part of the same application.

## Resume Atelier updates
- Compact landing page and dashboard copy for a cleaner experience.
- Live resume preview updates while you type in the editor.
- Five preview themes: Modern, Classic, Minimal, Technical, and Executive.
- Use **Save as PDF** in the live preview to print or save the current draft as a PDF from your browser.
- The existing Flask routes and SQLite resume storage remain in place.

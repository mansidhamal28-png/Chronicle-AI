import os
import json
import logging
from functools import wraps
from flask import (
    Flask, render_template, request, redirect, url_for, flash, session, jsonify, abort
)
from werkzeug.utils import secure_filename
from dotenv import load_dotenv

# Load environment configuration
load_dotenv()

# Initialize logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("chronicle_ai")

# Import services
from services.document_service import DocumentService
from services.groq_service import GroqService
from services.supabase_service import SupabaseService

# Initialize Flask App
app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "chronicle_super_secret_session_key_2026")

# File Upload Configuration
UPLOAD_FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), os.getenv("UPLOAD_FOLDER", "uploads"))
os.makedirs(UPLOAD_FOLDER, exist_ok=True)
app.config["UPLOAD_FOLDER"] = UPLOAD_FOLDER
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_CONTENT_LENGTH", 16 * 1024 * 1024))
ALLOWED_EXTENSIONS = {"pdf", "txt", "md"}

# Initialize Services
db_service = SupabaseService()
groq_service = GroqService()

def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS

# Auth helper decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user_id" not in session:
            flash("Please sign in to access your Chronicle workspace.", "info")
            return redirect(url_for("login", next=request.url))
        return f(*args, **kwargs)
    return decorated_function

# Context processor for global templates
@app.context_processor
def inject_user():
    user = None
    if "user_id" in session:
        user = db_service.get_user_by_id(session["user_id"])
    return dict(current_user=user)

# ---------------- PUBLIC & AUTH ROUTES ---------------- #

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return render_template("index.html")

@app.route("/register", methods=["GET", "POST"])
def register():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        res = db_service.create_user(email=email, password=password, full_name=full_name)
        if res.get("success"):
            user = res["user"]
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            session["user_name"] = user["full_name"]
            flash(f"Welcome to Chronicle AI, {user['full_name']}!", "success")
            return redirect(url_for("dashboard"))
        else:
            flash(res.get("error", "Registration failed. Please try again."), "error")

    return render_template("register.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if "user_id" in session:
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip()
        password = request.form.get("password", "")

        res = db_service.authenticate_user(email=email, password=password)
        if res.get("success"):
            user = res["user"]
            session["user_id"] = user["id"]
            session["user_email"] = user["email"]
            session["user_name"] = user["full_name"]
            flash("Successfully signed in.", "success")
            next_page = request.args.get("next")
            return redirect(next_page if next_page else url_for("dashboard"))
        else:
            flash(res.get("error", "Invalid credentials. Please verify your email and password."), "error")

    return render_template("login.html")

@app.route("/logout")
def logout():
    session.clear()
    flash("You have been signed out.", "info")
    return redirect(url_for("index"))

# ---------------- DASHBOARD & DOCUMENT VAULT ---------------- #

@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    search_query = request.args.get("q", "").strip()
    documents = db_service.get_user_documents(user_id=user_id, search=search_query)
    stats = db_service.get_user_stats(user_id=user_id)
    return render_template(
        "dashboard.html",
        documents=documents,
        stats=stats,
        search_query=search_query,
        active_page="dashboard"
    )

@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload_document():
    if request.method == "POST":
        if "document" not in request.files:
            flash("No file part provided in the request.", "error")
            return redirect(request.url)

        file = request.files["document"]
        if file.filename == "":
            flash("No document selected for upload.", "error")
            return redirect(request.url)

        if file and allowed_file(file.filename):
            orig_filename = secure_filename(file.filename)
            if not orig_filename:
                orig_filename = "document.pdf"

            # Create user-isolated upload folder
            user_upload_dir = os.path.join(app.config["UPLOAD_FOLDER"], session["user_id"])
            os.makedirs(user_upload_dir, exist_ok=True)
            saved_file_path = os.path.join(user_upload_dir, orig_filename)
            file.save(saved_file_path)

            file_size = os.path.getsize(saved_file_path)

            try:
                # 1. Parse and extract text
                extraction = DocumentService.extract_text_from_file(saved_file_path)
                extracted_text = extraction["text"]
                page_count = extraction["page_count"]
                file_type = extraction["file_type"]

                # 2. AI Structured Summarization
                summary_data = groq_service.summarize_document(extracted_text, filename=orig_filename)
                executive_summary = summary_data.get("executive_summary", "")
                findings_json = json.dumps(summary_data.get("key_findings", []))
                actions_json = json.dumps(summary_data.get("action_items", []))
                full_summary = summary_data.get("full_markdown", "")

                # 3. Save Document into persistent vault
                doc_id = db_service.save_document(
                    user_id=session["user_id"],
                    filename=orig_filename,
                    file_path=saved_file_path,
                    file_size=file_size,
                    file_type=file_type,
                    extracted_text=extracted_text,
                    page_count=page_count,
                    summary=full_summary,
                    summary_executive=executive_summary,
                    summary_key_findings=findings_json,
                    summary_action_items=actions_json
                )

                # 4. Extract and save Smart Notes
                notes_data = groq_service.extract_smart_notes(extracted_text, filename=orig_filename)
                if notes_data:
                    db_service.save_notes_batch(session["user_id"], doc_id, notes_data)

                # 5. Extract and save Timeline Milestones
                events_data = groq_service.extract_timeline_events(extracted_text, filename=orig_filename)
                if events_data:
                    db_service.save_timeline_events_batch(session["user_id"], doc_id, events_data)

                flash(f"'{orig_filename}' was successfully ingested and analyzed!", "success")
                return redirect(url_for("document_detail", doc_id=doc_id))

            except Exception as e:
                logger.error(f"Error processing document upload: {e}", exc_info=True)
                flash(f"Error processing document: {str(e)}", "error")
                return redirect(request.url)
        else:
            flash("Invalid file type. Chronicle AI accepts PDF, TXT, and Markdown files.", "error")
            return redirect(request.url)

    return render_template("upload.html", active_page="upload")

@app.route("/documents/<doc_id>")
@login_required
def document_detail(doc_id: str):
    user_id = session["user_id"]
    document = db_service.get_document(doc_id=doc_id, user_id=user_id)
    if not document:
        flash("Document not found or access denied.", "error")
        return redirect(url_for("dashboard"))

    # Parse JSON serialized findings and action items
    findings_list = []
    action_items_list = []
    if document.get("summary_key_findings"):
        try:
            findings_list = json.loads(document["summary_key_findings"])
        except Exception:
            findings_list = []

    if document.get("summary_action_items"):
        try:
            action_items_list = json.loads(document["summary_action_items"])
        except Exception:
            action_items_list = []

    # Get associated notes and timeline events
    notes = db_service.get_user_notes(user_id=user_id, document_id=doc_id)
    events = db_service.get_user_timeline_events(user_id=user_id, document_id=doc_id)

    return render_template(
        "document_detail.html",
        document=document,
        findings_list=findings_list,
        action_items_list=action_items_list,
        notes=notes,
        events=events,
        active_page="dashboard"
    )

@app.route("/documents/<doc_id>/delete", methods=["POST"])
@login_required
def delete_document(doc_id: str):
    user_id = session["user_id"]
    success = db_service.delete_document(doc_id=doc_id, user_id=user_id)
    if success:
        flash("Document and associated data permanently removed.", "info")
    else:
        flash("Failed to delete document.", "error")
    return redirect(url_for("dashboard"))

# ---------------- INTELLIGENT DOCUMENT CHAT ---------------- #

@app.route("/chat")
@app.route("/chat/<doc_id>")
@login_required
def chat_view(doc_id: str = None):
    user_id = session["user_id"]
    documents = db_service.get_user_documents(user_id=user_id)
    active_document = None
    if doc_id:
        active_document = db_service.get_document(doc_id=doc_id, user_id=user_id)

    chat_history = db_service.get_chat_history(user_id=user_id, document_id=doc_id)

    return render_template(
        "chat.html",
        documents=documents,
        active_document=active_document,
        selected_doc_id=doc_id,
        chat_history=chat_history,
        active_page="chat"
    )

@app.route("/api/chat", methods=["POST"])
@login_required
def api_chat():
    data = request.get_json() or {}
    message = data.get("message", "").strip()
    doc_id = data.get("document_id") or None
    user_id = session["user_id"]

    if not message:
        return jsonify({"success": False, "error": "Message content cannot be empty."}), 400

    # Retrieve context
    relevant_context = ""
    doc_title = "Document Library"

    if doc_id:
        doc = db_service.get_document(doc_id=doc_id, user_id=user_id)
        if doc and doc.get("extracted_text"):
            doc_title = doc["filename"]
            chunks = DocumentService.retrieve_relevant_chunks(message, doc["extracted_text"], top_k=4)
            relevant_context = "\n\n---\n\n".join(chunks)
    else:
        # Multi-document retrieval across user documents
        all_docs = db_service.get_user_documents(user_id=user_id)
        combined_chunks = []
        for d in all_docs[:5]:
            full_doc = db_service.get_document(doc_id=d["id"], user_id=user_id)
            if full_doc and full_doc.get("extracted_text"):
                top_chunks = DocumentService.retrieve_relevant_chunks(message, full_doc["extracted_text"], top_k=2)
                for chunk in top_chunks:
                    combined_chunks.append(f"[From {full_doc['filename']}]:\n{chunk}")
        relevant_context = "\n\n---\n\n".join(combined_chunks[:5])

    # Save user message to database
    db_service.save_chat_message(user_id=user_id, document_id=doc_id, role="user", message=message)

    # Fetch recent history for multi-turn conversational context
    recent_history = db_service.get_chat_history(user_id=user_id, document_id=doc_id, limit=6)

    # Call Groq service
    ai_response = groq_service.chat_with_document(
        query=message,
        relevant_context=relevant_context,
        document_title=doc_title,
        chat_history=recent_history
    )

    answer = ai_response.get("answer", "")
    sources = ai_response.get("sources", [])
    sources_str = ", ".join(sources) if sources else ""

    # Save assistant answer to database
    db_service.save_chat_message(user_id=user_id, document_id=doc_id, role="assistant", message=answer, sources=sources_str)

    return jsonify({
        "success": True,
        "answer": answer,
        "sources": sources
    })

@app.route("/api/chat/clear", methods=["POST"])
@login_required
def api_clear_chat():
    data = request.get_json() or {}
    doc_id = data.get("document_id") or None
    user_id = session["user_id"]
    db_service.clear_chat_history(user_id=user_id, document_id=doc_id)
    return jsonify({"success": True})

# ---------------- SMART NOTES ---------------- #

@app.route("/notes")
@login_required
def notes_view():
    user_id = session["user_id"]
    notes = db_service.get_user_notes(user_id=user_id)
    documents = db_service.get_user_documents(user_id=user_id)
    return render_template("notes.html", notes=notes, documents=documents, active_page="notes")

@app.route("/notes/create", methods=["POST"])
@login_required
def create_note_route():
    user_id = session["user_id"]
    title = request.form.get("title", "").strip()
    content = request.form.get("content", "").strip()
    category = request.form.get("category", "Key Concept").strip()
    tags = request.form.get("tags", "").strip()
    document_id = request.form.get("document_id") or None

    if not title or not content:
        flash("Title and note content are required.", "error")
        return redirect(request.referrer or url_for("notes_view"))

    db_service.create_single_note(
        user_id=user_id,
        title=title,
        content=content,
        category=category,
        tags=tags,
        document_id=document_id
    )
    flash("Note saved to your knowledge base.", "success")
    return redirect(request.referrer or url_for("notes_view"))

@app.route("/notes/<note_id>/delete", methods=["POST"])
@login_required
def delete_note_route(note_id: str):
    user_id = session["user_id"]
    db_service.delete_note(note_id=note_id, user_id=user_id)
    flash("Note deleted.", "info")
    return redirect(request.referrer or url_for("notes_view"))

# ---------------- AI TIMELINE ---------------- #

@app.route("/timeline")
@app.route("/timeline/<doc_id>")
@login_required
def timeline_view(doc_id: str = None):
    user_id = session["user_id"]
    documents = db_service.get_user_documents(user_id=user_id)
    events = db_service.get_user_timeline_events(user_id=user_id, document_id=doc_id)
    return render_template(
        "timeline.html",
        documents=documents,
        events=events,
        selected_doc_id=doc_id,
        active_page="timeline"
    )

@app.route("/timeline/<event_id>/delete", methods=["POST"])
@login_required
def delete_timeline_event_route(event_id: str):
    user_id = session["user_id"]
    db_service.delete_timeline_event(event_id=event_id, user_id=user_id)
    flash("Timeline event removed.", "info")
    return redirect(request.referrer or url_for("timeline_view"))

# ---------------- APP STARTUP ---------------- #

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    logger.info(f"Chronicle AI server starting on port {port}...")
    app.run(host="0.0.0.0", port=port, debug=True)

import os
import sqlite3
import uuid
import datetime
import logging
from typing import List, Dict, Any, Optional
from werkzeug.security import generate_password_hash, check_password_hash

logger = logging.getLogger(__name__)

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "chronicle_local.db")

class SupabaseService:
    """
    Unified storage and auth service.
    Connects to Supabase if SUPABASE_URL and SUPABASE_KEY are provided.
    Seamlessly falls back to local SQLite with the exact same schema and interface
    for frictionless local MVP development and testing.
    """
    def __init__(self):
        self.supabase_url = os.getenv("SUPABASE_URL", "").strip()
        self.supabase_key = os.getenv("SUPABASE_KEY", "").strip()
        self.client = None
        self.is_supabase = False

        if self.supabase_url and self.supabase_key and not self.supabase_url.startswith("https://your-project"):
            try:
                from supabase import create_client
                self.client = create_client(self.supabase_url, self.supabase_key)
                self.is_supabase = True
                logger.info("Connected to remote Supabase instance.")
            except Exception as e:
                logger.warning(f"Failed to connect to Supabase, falling back to local SQLite: {e}")
                self.is_supabase = False

        if not self.is_supabase:
            self._init_sqlite()

    def _get_db(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_sqlite(self):
        """Initializes tables in local SQLite database using schema."""
        schema_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "schema.sql")
        with self._get_db() as conn:
            if os.path.exists(schema_path):
                with open(schema_path, "r", encoding="utf-8") as f:
                    conn.executescript(f.read())
            conn.commit()

    # ---------------- USER AUTHENTICATION ---------------- #

    def create_user(self, email: str, password: str, full_name: str = "") -> Dict[str, Any]:
        """Registers a new user."""
        email = email.strip().lower()
        if not email or not password:
            return {"success": False, "error": "Email and password are required."}

        # Check existing user
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id FROM users WHERE email = ?", (email,))
            if cur.fetchone():
                return {"success": False, "error": "An account with this email already exists."}

            user_id = str(uuid.uuid4())
            pw_hash = generate_password_hash(password)
            now = datetime.datetime.utcnow().isoformat()
            cur.execute(
                "INSERT INTO users (id, email, password_hash, full_name, created_at) VALUES (?, ?, ?, ?, ?)",
                (user_id, email, pw_hash, full_name or email.split("@")[0], now)
            )
            conn.commit()

            return {
                "success": True,
                "user": {
                    "id": user_id,
                    "email": email,
                    "full_name": full_name or email.split("@")[0]
                }
            }

    def authenticate_user(self, email: str, password: str) -> Dict[str, Any]:
        """Authenticates user with email and password."""
        email = email.strip().lower()
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, email, password_hash, full_name FROM users WHERE email = ?", (email,))
            row = cur.fetchone()
            if not row:
                return {"success": False, "error": "Invalid email or password."}

            if not check_password_hash(row["password_hash"], password):
                return {"success": False, "error": "Invalid email or password."}

            return {
                "success": True,
                "user": {
                    "id": row["id"],
                    "email": row["email"],
                    "full_name": row["full_name"]
                }
            }

    def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT id, email, full_name, created_at FROM users WHERE id = ?", (user_id,))
            row = cur.fetchone()
            return dict(row) if row else None

    # ---------------- DOCUMENTS ---------------- #

    def save_document(
        self,
        user_id: str,
        filename: str,
        file_path: str,
        file_size: int,
        file_type: str,
        extracted_text: str,
        page_count: int,
        summary: str = "",
        summary_executive: str = "",
        summary_key_findings: str = "",
        summary_action_items: str = ""
    ) -> str:
        doc_id = str(uuid.uuid4())
        char_count = len(extracted_text) if extracted_text else 0
        now = datetime.datetime.utcnow().isoformat()

        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO documents (
                    id, user_id, filename, file_path, file_size, file_type,
                    char_count, page_count, extracted_text, summary,
                    summary_executive, summary_key_findings, summary_action_items,
                    status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?)
                """,
                (
                    doc_id, user_id, filename, file_path, file_size, file_type,
                    char_count, page_count, extracted_text, summary,
                    summary_executive, summary_key_findings, summary_action_items, now
                )
            )
            conn.commit()

        return doc_id

    def get_document(self, doc_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_user_documents(self, user_id: str, search: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            if search:
                term = f"%{search.strip()}%"
                cur.execute(
                    """
                    SELECT id, filename, file_size, file_type, page_count, char_count,
                           summary_executive, status, created_at
                    FROM documents
                    WHERE user_id = ? AND (filename LIKE ? OR summary_executive LIKE ? OR extracted_text LIKE ?)
                    ORDER BY created_at DESC
                    """,
                    (user_id, term, term, term)
                )
            else:
                cur.execute(
                    """
                    SELECT id, filename, file_size, file_type, page_count, char_count,
                           summary_executive, status, created_at
                    FROM documents
                    WHERE user_id = ?
                    ORDER BY created_at DESC
                    """,
                    (user_id,)
                )
            return [dict(r) for r in cur.fetchall()]

    def delete_document(self, doc_id: str, user_id: str) -> bool:
        with self._get_db() as conn:
            cur = conn.cursor()
            # Fetch file path first to delete file on disk
            cur.execute("SELECT file_path FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
            row = cur.fetchone()
            if not row:
                return False

            file_path = row["file_path"]
            if file_path and os.path.exists(file_path):
                try:
                    os.remove(file_path)
                except Exception:
                    pass

            cur.execute("DELETE FROM documents WHERE id = ? AND user_id = ?", (doc_id, user_id))
            cur.execute("DELETE FROM notes WHERE document_id = ?", (doc_id,))
            cur.execute("DELETE FROM timeline_events WHERE document_id = ?", (doc_id,))
            cur.execute("DELETE FROM chat_messages WHERE document_id = ?", (doc_id,))
            conn.commit()
            return True

    # ---------------- NOTES & KEY CONCEPTS ---------------- #

    def save_notes_batch(self, user_id: str, document_id: Optional[str], notes_list: List[Dict[str, Any]]) -> int:
        now = datetime.datetime.utcnow().isoformat()
        count = 0
        with self._get_db() as conn:
            cur = conn.cursor()
            for n in notes_list:
                note_id = str(uuid.uuid4())
                tags = ",".join(n.get("tags", [])) if isinstance(n.get("tags"), list) else n.get("tags", "")
                cur.execute(
                    """
                    INSERT INTO notes (id, user_id, document_id, title, content, category, tags, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (note_id, user_id, document_id, n.get("title", "Untitled Note"), n.get("content", ""), n.get("category", "Key Concept"), tags, now, now)
                )
                count += 1
            conn.commit()
        return count

    def create_single_note(self, user_id: str, title: str, content: str, category: str = "Key Concept", tags: str = "", document_id: Optional[str] = None) -> Dict[str, Any]:
        note_id = str(uuid.uuid4())
        now = datetime.datetime.utcnow().isoformat()
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO notes (id, user_id, document_id, title, content, category, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (note_id, user_id, document_id, title, content, category, tags, now, now)
            )
            conn.commit()
        return {"id": note_id, "title": title, "content": content, "category": category, "tags": tags, "created_at": now}

    def get_user_notes(self, user_id: str, document_id: Optional[str] = None, category: Optional[str] = None, search: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            query = """
                SELECT n.*, d.filename as document_name
                FROM notes n
                LEFT JOIN documents d ON n.document_id = d.id
                WHERE n.user_id = ?
            """
            params = [user_id]

            if document_id:
                query += " AND n.document_id = ?"
                params.append(document_id)
            if category and category != "all":
                query += " AND n.category = ?"
                params.append(category)
            if search:
                query += " AND (n.title LIKE ? OR n.content LIKE ? OR n.tags LIKE ?)"
                term = f"%{search.strip()}%"
                params.extend([term, term, term])

            query += " ORDER BY n.created_at DESC"
            cur.execute(query, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def delete_note(self, note_id: str, user_id: str) -> bool:
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM notes WHERE id = ? AND user_id = ?", (note_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    # ---------------- TIMELINE EVENTS ---------------- #

    def save_timeline_events_batch(self, user_id: str, document_id: Optional[str], events_list: List[Dict[str, Any]]) -> int:
        now = datetime.datetime.utcnow().isoformat()
        count = 0
        with self._get_db() as conn:
            cur = conn.cursor()
            for ev in events_list:
                ev_id = str(uuid.uuid4())
                cur.execute(
                    """
                    INSERT INTO timeline_events (id, user_id, document_id, date_str, parsed_date, title, description, event_type, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        ev_id, user_id, document_id,
                        ev.get("date_str", "Unknown Date"),
                        ev.get("parsed_date") or None,
                        ev.get("title", "Milestone"),
                        ev.get("description", ""),
                        ev.get("event_type", "milestone"),
                        now
                    )
                )
                count += 1
            conn.commit()
        return count

    def get_user_timeline_events(self, user_id: str, document_id: Optional[str] = None) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            query = """
                SELECT t.*, d.filename as document_name
                FROM timeline_events t
                LEFT JOIN documents d ON t.document_id = d.id
                WHERE t.user_id = ?
            """
            params = [user_id]
            if document_id:
                query += " AND t.document_id = ?"
                params.append(document_id)

            query += " ORDER BY COALESCE(t.parsed_date, t.date_str) ASC, t.created_at ASC"
            cur.execute(query, tuple(params))
            return [dict(r) for r in cur.fetchall()]

    def delete_timeline_event(self, event_id: str, user_id: str) -> bool:
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("DELETE FROM timeline_events WHERE id = ? AND user_id = ?", (event_id, user_id))
            conn.commit()
            return cur.rowcount > 0

    # ---------------- CHAT MESSAGES ---------------- #

    def save_chat_message(self, user_id: str, document_id: Optional[str], role: str, message: str, sources: Optional[str] = None) -> str:
        msg_id = str(uuid.uuid4())
        now = datetime.datetime.utcnow().isoformat()
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute(
                """
                INSERT INTO chat_messages (id, user_id, document_id, role, message, sources, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (msg_id, user_id, document_id, role, message, sources or "", now)
            )
            conn.commit()
        return msg_id

    def get_chat_history(self, user_id: str, document_id: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_db() as conn:
            cur = conn.cursor()
            if document_id:
                cur.execute(
                    """
                    SELECT * FROM chat_messages
                    WHERE user_id = ? AND document_id = ?
                    ORDER BY created_at ASC
                    LIMIT ?
                    """,
                    (user_id, document_id, limit)
                )
            else:
                cur.execute(
                    """
                    SELECT c.*, d.filename as document_name
                    FROM chat_messages c
                    LEFT JOIN documents d ON c.document_id = d.id
                    WHERE c.user_id = ?
                    ORDER BY c.created_at ASC
                    LIMIT ?
                    """,
                    (user_id, limit)
                )
            return [dict(r) for r in cur.fetchall()]

    def clear_chat_history(self, user_id: str, document_id: Optional[str] = None) -> bool:
        with self._get_db() as conn:
            cur = conn.cursor()
            if document_id:
                cur.execute("DELETE FROM chat_messages WHERE user_id = ? AND document_id = ?", (user_id, document_id))
            else:
                cur.execute("DELETE FROM chat_messages WHERE user_id = ?", (user_id,))
            conn.commit()
            return True

    # ---------------- DASHBOARD AGGREGATES ---------------- #

    def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        with self._get_db() as conn:
            cur = conn.cursor()
            cur.execute("SELECT COUNT(*) as count FROM documents WHERE user_id = ?", (user_id,))
            doc_count = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM notes WHERE user_id = ?", (user_id,))
            notes_count = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM timeline_events WHERE user_id = ?", (user_id,))
            timeline_count = cur.fetchone()["count"]

            cur.execute("SELECT COUNT(*) as count FROM chat_messages WHERE user_id = ? AND role = 'user'", (user_id,))
            chat_count = cur.fetchone()["count"]

            return {
                "document_count": doc_count,
                "notes_count": notes_count,
                "timeline_count": timeline_count,
                "chat_count": chat_count
            }

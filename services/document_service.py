import os
import re
from typing import List, Dict, Any, Tuple

# Try importing fitz (PyMuPDF) and pypdf
try:
    import fitz  # PyMuPDF
    HAVE_PYMUPDF = True
except ImportError:
    HAVE_PYMUPDF = False

try:
    import pypdf
    HAVE_PYPDF = True
except ImportError:
    HAVE_PYPDF = False


class DocumentService:
    @staticmethod
    def extract_text_from_file(file_path: str) -> Dict[str, Any]:
        """
        Extracts clean text and metadata from PDF or TXT files.
        Returns a dict with 'text', 'page_count', 'char_count', 'file_type'.
        """
        if not os.path.exists(file_path):
            raise FileNotFoundError(f"File not found: {file_path}")

        ext = os.path.splitext(file_path)[1].lower().replace(".", "")
        if ext == "pdf":
            return DocumentService._extract_from_pdf(file_path)
        elif ext in ["txt", "md", "csv"]:
            return DocumentService._extract_from_text_file(file_path, ext)
        else:
            raise ValueError(f"Unsupported file type: .{ext}. Chronicle AI supports PDF and TXT files.")

    @staticmethod
    def _extract_from_pdf(file_path: str) -> Dict[str, Any]:
        """Extract text from PDF using PyMuPDF first, falling back to pypdf."""
        extracted_pages = []
        page_count = 0

        if HAVE_PYMUPDF:
            try:
                doc = fitz.open(file_path)
                page_count = len(doc)
                for page_idx in range(page_count):
                    page = doc[page_idx]
                    page_text = page.get_text("text") or ""
                    extracted_pages.append(page_text.strip())
                doc.close()
            except Exception as e:
                # If PyMuPDF fails, attempt pypdf fallback
                extracted_pages = []

        if not extracted_pages and HAVE_PYPDF:
            try:
                reader = pypdf.PdfReader(file_path)
                page_count = len(reader.pages)
                for page in reader.pages:
                    text = page.extract_text() or ""
                    extracted_pages.append(text.strip())
            except Exception as e:
                raise RuntimeError(f"Failed to read PDF file with PyMuPDF and pypdf: {str(e)}")

        if not extracted_pages and not HAVE_PYMUPDF and not HAVE_PYPDF:
            raise RuntimeError("Neither PyMuPDF nor pypdf is installed for PDF parsing.")

        full_text = "\n\n".join([f"--- Page {i+1} ---\n{p}" for i, p in enumerate(extracted_pages) if p])
        if not full_text.strip():
            full_text = "No extractable text found in this PDF (it may contain only scanned images or protected content)."

        clean_text = DocumentService._clean_text(full_text)
        return {
            "text": clean_text,
            "page_count": page_count or 1,
            "char_count": len(clean_text),
            "file_type": "pdf"
        }

    @staticmethod
    def _extract_from_text_file(file_path: str, ext: str) -> Dict[str, Any]:
        """Extract text from TXT/MD files with multiple encoding fallbacks."""
        encodings = ["utf-8", "utf-8-sig", "latin-1", "cp1252"]
        content = None
        for enc in encodings:
            try:
                with open(file_path, "r", encoding=enc) as f:
                    content = f.read()
                    break
            except (UnicodeDecodeError, UnicodeError):
                continue

        if content is None:
            with open(file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="ignore")

        clean_text = DocumentService._clean_text(content)
        return {
            "text": clean_text,
            "page_count": 1,
            "char_count": len(clean_text),
            "file_type": ext
        }

    @staticmethod
    def _clean_text(text: str) -> str:
        """Removes excessive whitespace while preserving paragraph structure."""
        if not text:
            return ""
        # Normalize multiple spaces, tabs, carriage returns
        text = text.replace("\r\n", "\n").replace("\r", "\n")
        # Collapse > 3 newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

    @staticmethod
    def chunk_text(text: str, chunk_size: int = 1200, overlap: int = 200) -> List[Dict[str, Any]]:
        """
        Splits text into chunks with context overlap for retrieval augmentation (RAG).
        """
        if not text:
            return []

        paragraphs = text.split("\n\n")
        chunks = []
        current_chunk = []
        current_length = 0
        chunk_idx = 0

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            para_len = len(para)
            if current_length + para_len > chunk_size and current_chunk:
                chunk_str = "\n\n".join(current_chunk)
                chunks.append({
                    "id": chunk_idx,
                    "text": chunk_str,
                    "start_char": 0,
                })
                chunk_idx += 1
                # Keep tail for overlap if possible
                overlap_text = current_chunk[-1] if len(current_chunk) > 1 else ""
                current_chunk = [overlap_text] if overlap_text and len(overlap_text) < overlap else []
                current_length = sum(len(p) for p in current_chunk)

            current_chunk.append(para)
            current_length += para_len

        if current_chunk:
            chunks.append({
                "id": chunk_idx,
                "text": "\n\n".join(current_chunk),
                "start_char": 0,
            })

        return chunks

    @staticmethod
    def retrieve_relevant_chunks(query: str, text: str, top_k: int = 4) -> List[str]:
        """
        Scores text chunks against user query using term-frequency and lexical relevance.
        Returns the top_k most relevant text chunks.
        """
        chunks = DocumentService.chunk_text(text, chunk_size=1200, overlap=200)
        if not chunks:
            return []
        if len(chunks) <= top_k:
            return [c["text"] for c in chunks]

        # Extract words from query
        query_words = set(re.findall(r"\w{3,}", query.lower()))
        if not query_words:
            return [c["text"] for c in chunks[:top_k]]

        scored_chunks = []
        for c in chunks:
            chunk_lower = c["text"].lower()
            score = 0
            # Term frequency match
            for word in query_words:
                count = chunk_lower.count(word)
                if count > 0:
                    score += 1.0 + min(count * 0.5, 3.0)
            # Exact phrase match boost
            if query.lower() in chunk_lower:
                score += 5.0

            scored_chunks.append((score, c["text"]))

        # Sort descending by score
        scored_chunks.sort(key=lambda x: x[0], reverse=True)
        return [chunk for score, chunk in scored_chunks[:top_k]]

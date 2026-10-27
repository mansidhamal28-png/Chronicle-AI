import os
import json
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)

class GroqService:
    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None):
        self.api_key = api_key or os.getenv("GROQ_API_KEY", "").strip()
        self.model = model or os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile").strip()
        self.client = None

        if self.api_key and not self.api_key.startswith("gsk_your_"):
            try:
                from groq import Groq
                self.client = Groq(api_key=self.api_key)
            except Exception as e:
                logger.warning(f"Could not initialize Groq client: {e}")

    def is_configured(self) -> bool:
        return self.client is not None

    def _truncate_context(self, text: str, max_chars: int = 18000) -> str:
        """Truncates text safely to avoid exceeding token windows while retaining substance."""
        if not text:
            return ""
        if len(text) <= max_chars:
            return text
        # Keep beginning and middle/end
        half = max_chars // 2
        return text[:half] + "\n\n[... content truncated for length ...]\n\n" + text[-half:]

    def summarize_document(self, text: str, filename: str = "Document") -> Dict[str, Any]:
        """
        Generates structured summary: Executive Summary, Key Findings, Action Items, and Full Summary.
        """
        if not self.is_configured():
            return self._mock_summary(filename, text)

        truncated_text = self._truncate_context(text, max_chars=20000)
        prompt = f"""You are Chronicle AI, an elite document intelligence analyst.
Analyze the following document titled "{filename}" and provide a structured summary in JSON format.

DOCUMENT CONTENT:
\"\"\"
{truncated_text}
\"\"\"

Respond with valid JSON only, using this exact schema:
{{
  "executive_summary": "2-3 comprehensive paragraphs summarizing the core thesis, purpose, and conclusions.",
  "key_findings": [
    "Key finding 1 with specific details",
    "Key finding 2 with specific details",
    "Key finding 3 with specific details",
    "Key finding 4 with specific details",
    "Key finding 5 with specific details"
  ],
  "action_items": [
    "Concrete action item or recommendation 1",
    "Concrete action item or recommendation 2",
    "Concrete action item or recommendation 3"
  ],
  "highlights": "A punchy 1-2 sentence takeaway of the document."
}}
Ensure the output is strictly valid JSON without preamble or markdown wraps if possible.
"""
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Chronicle AI. Always respond in valid JSON format."},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw_response = chat_completion.choices[0].message.content
            parsed = json.loads(raw_response)
            
            # Format combined markdown summary
            exec_sum = parsed.get("executive_summary", "")
            findings = "\n".join([f"- {f}" for f in parsed.get("key_findings", [])])
            actions = "\n".join([f"- {a}" for a in parsed.get("action_items", [])])
            
            markdown_full = f"### Executive Summary\n{exec_sum}\n\n### Key Findings\n{findings}\n\n### Action Items & Next Steps\n{actions}"

            return {
                "executive_summary": exec_sum,
                "key_findings": parsed.get("key_findings", []),
                "action_items": parsed.get("action_items", []),
                "highlights": parsed.get("highlights", ""),
                "full_markdown": markdown_full
            }
        except Exception as e:
            logger.error(f"Groq API error during summarization: {e}")
            return self._mock_summary(filename, text, error=str(e))

    def chat_with_document(
        self,
        query: str,
        relevant_context: str,
        document_title: str = "Document",
        chat_history: Optional[List[Dict[str, str]]] = None
    ) -> Dict[str, Any]:
        """
        Answers a user's question grounded in retrieved document context.
        """
        if not self.is_configured():
            return {
                "answer": f"[Groq API Key Not Configured] To unlock live AI chat with Llama 3.3, please add your free Groq API key in the `.env` file (`GROQ_API_KEY=gsk_...`).\n\nPreview Response for '{query}': Document '{document_title}' has been indexed and contains relevant sections matching your query.",
                "sources": ["Preview Mode: Set GROQ_API_KEY in .env"]
            }

        history_messages = []
        if chat_history:
            for item in chat_history[-6:]:
                role = "assistant" if item.get("role") == "assistant" else "user"
                history_messages.append({"role": role, "content": item.get("message", "")})

        system_prompt = f"""You are Chronicle AI, an intelligent document companion.
Your mission is to answer user inquiries accurately and insightfully based on the provided document context from "{document_title}".

Guidelines:
1. Ground your answers primarily in the provided document excerpts.
2. If the excerpts do not contain the answer, explicitly state that the document does not mention it, but offer helpful logical reasoning or general knowledge if appropriate (clarifying that it is beyond the document).
3. Use clear, formatted Markdown with bullet points, bold highlights, and code/math blocks where suitable.
4. When citing facts, mention which section or context was used.
"""

        user_content = f"""DOCUMENT CONTEXT EXCERPTS:
\"\"\"
{relevant_context}
\"\"\"

USER QUESTION:
{query}
"""

        messages = [{"role": "system", "content": system_prompt}] + history_messages + [{"role": "user", "content": user_content}]

        try:
            chat_completion = self.client.chat.completions.create(
                messages=messages,
                model=self.model,
                temperature=0.3,
                max_tokens=1500
            )
            answer = chat_completion.choices[0].message.content
            return {
                "answer": answer,
                "sources": [f"Source: {document_title}"]
            }
        except Exception as e:
            logger.error(f"Groq API error during chat: {e}")
            return {
                "answer": f"Chronicle AI encountered an error contacting Groq API: {str(e)}",
                "sources": []
            }

    def extract_smart_notes(self, text: str, filename: str = "Document") -> List[Dict[str, Any]]:
        """
        Extracts key concepts, definitions, important entities, and actionable notes from the document.
        """
        if not self.is_configured():
            return self._mock_notes(filename)

        truncated_text = self._truncate_context(text, max_chars=18000)
        prompt = f"""You are Chronicle AI Knowledge Extractor.
Extract the most valuable concepts, key definitions, important terms, decisions, and action points from "{filename}".

DOCUMENT:
\"\"\"
{truncated_text}
\"\"\"

Respond strictly with a JSON object containing a "notes" array.
Schema:
{{
  "notes": [
    {{
      "title": "Clear, concise concept title",
      "category": "Key Concept" | "Definition" | "Important Figure" | "Action Item" | "Decision",
      "content": "Detailed, highly valuable explanation of the concept or note extracted from the text.",
      "tags": ["tag1", "tag2"]
    }}
  ]
}}
Extract between 4 and 8 high-impact notes.
"""
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Chronicle AI. Respond in valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw_response = chat_completion.choices[0].message.content
            data = json.loads(raw_response)
            return data.get("notes", [])
        except Exception as e:
            logger.error(f"Groq API error during smart notes extraction: {e}")
            return self._mock_notes(filename, error=str(e))

    def extract_timeline_events(self, text: str, filename: str = "Document") -> List[Dict[str, Any]]:
        """
        Extracts milestones, dates, deadlines, historical markers, and chronological events.
        """
        if not self.is_configured():
            return self._mock_timeline(filename)

        truncated_text = self._truncate_context(text, max_chars=18000)
        prompt = f"""You are Chronicle AI Chronological Intelligence Engine.
Extract all timeline events, dates, deadlines, milestones, historical events, and scheduled phases mentioned in "{filename}".

DOCUMENT:
\"\"\"
{truncated_text}
\"\"\"

Respond strictly with a JSON object containing an "events" array sorted chronologically if possible.
Schema:
{{
  "events": [
    {{
      "date_str": "Original date representation (e.g., 'October 2024', 'Q3 2025', 'Phase 1 - Week 2', '2023-05-12')",
      "parsed_date": "ISO format YYYY-MM-DD or YYYY if identifiable, otherwise null",
      "title": "Concise event or milestone title",
      "description": "Details about what occurred, what is planned, or the deadline requirement.",
      "event_type": "milestone" | "deadline" | "meeting" | "historical" | "launch" | "review"
    }}
  ]
}}
Extract between 3 and 10 chronological events.
"""
        try:
            chat_completion = self.client.chat.completions.create(
                messages=[
                    {"role": "system", "content": "You are Chronicle AI. Respond in valid JSON only."},
                    {"role": "user", "content": prompt}
                ],
                model=self.model,
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            raw_response = chat_completion.choices[0].message.content
            data = json.loads(raw_response)
            return data.get("events", [])
        except Exception as e:
            logger.error(f"Groq API error during timeline extraction: {e}")
            return self._mock_timeline(filename, error=str(e))

    def _mock_summary(self, filename: str, text: str, error: Optional[str] = None) -> Dict[str, Any]:
        first_p = text[:400].strip() if text else "Document content uploaded."
        return {
            "executive_summary": f"Chronicle AI successfully ingested '{filename}'. Note: Add your Groq API key (GROQ_API_KEY in .env) to enable full high-speed LLM processing with Llama 3.3. Preliminary excerpt: {first_p}...",
            "key_findings": [
                f"Document '{filename}' was parsed and indexed.",
                f"Content volume: ~{len(text)} characters extracted.",
                "Ready for AI semantic query and smart extraction upon Groq key activation."
            ],
            "action_items": [
                "Configure your GROQ_API_KEY in .env to enable real-time Llama 3.3 70B inferences.",
                "Review uploaded documents from the Chronicle AI Dashboard.",
                "Query document contents using Intelligent Chat."
            ],
            "highlights": f"Parsed {filename} into Chronicle AI document knowledge base.",
            "full_markdown": f"### Executive Summary\nDocument '{filename}' is ready. {first_p}\n\n### Key Findings\n- Total characters: {len(text)}\n- Status: Ingested"
        }

    def _mock_notes(self, filename: str, error: Optional[str] = None) -> List[Dict[str, Any]]:
        return [
            {
                "title": f"Document Overview: {filename}",
                "category": "Key Concept",
                "content": "Chronicle AI auto-extracted note template. Add GROQ_API_KEY in .env for automated deep conceptual extraction.",
                "tags": ["Overview", "Chronicle-AI"]
            },
            {
                "title": "Actionable Next Step",
                "category": "Action Item",
                "content": "Verify document details and begin exploration via Document Chat.",
                "tags": ["NextSteps", "Workflow"]
            }
        ]

    def _mock_timeline(self, filename: str, error: Optional[str] = None) -> List[Dict[str, Any]]:
        import datetime
        today = datetime.date.today().isoformat()
        return [
            {
                "date_str": "Document Upload Date",
                "parsed_date": today,
                "title": f"Ingestion of {filename}",
                "description": "Document was uploaded and indexed in the Chronicle AI Knowledge base.",
                "event_type": "milestone"
            }
        ]

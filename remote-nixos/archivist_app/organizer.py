from app.embeddings import chat_text
from app.utils import safe_relative_folder


def suggest_folder_for_file(name: str, ext: str, text: str, summary: str, category: str) -> str:
    prompt = f"""
You are a local file archivist.
Return ONLY a relative folder path, no explanation.

Typical top-level folders:
Documents/
Photos/
Videos/
Audio/
Software/
ROMs/
Projects/
Personal/
Family/
Legal/
Finance/
Scans/

Filename: {name}
Extension: {ext}
Category: {category}
Summary: {summary[:2000]}
Extracted text: {text[:3000]}
"""
    try:
        raw_folder = chat_text(
            prompt,
            system="Return only a concise relative folder path.",
            task="organizer",
        ).strip().replace("\\", "/")
        return safe_relative_folder(raw_folder).as_posix()
    except Exception:
        return "Review/Uncertain"

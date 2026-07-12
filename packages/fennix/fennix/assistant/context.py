from __future__ import annotations

from fennix.recall.__init__ import recall as _recall
from fennix.context.__init__ import gather_context, format_context_for_prompt


def build_context_block(user_query: str) -> str:
    parts: list[str] = []

    os_context = gather_context(include_system=True, include_clipboard=True, include_filesystem=True)
    formatted_os = format_context_for_prompt(os_context)
    if formatted_os:
        parts.append(formatted_os)

    recall_results = _recall(user_query)
    if recall_results:
        parts.append(_format_recall_results(recall_results))

    return "\n\n".join(parts)


def _format_recall_results(results: list[dict]) -> str:
    lines: list[str] = ["### Relevant Recall Results"]

    for i, r in enumerate(results, 1):
        source = r.get("source", "unknown")
        content = (r.get("content") or "")[:400]
        score = r.get("score", 0)

        label = f"[{source}]"
        if source == "file":
            title = r.get("file_title") or r.get("file_path") or ""
            if title:
                label += f" {title}"
        elif source == "conversation":
            title = r.get("conversation_title") or ""
            if title:
                label += f" {title}"
        elif source == "memory":
            label += f" memory"

        lines.append(f"{i}. {label} (score: {score:.2f})\n   {content}")

    return "\n".join(lines)

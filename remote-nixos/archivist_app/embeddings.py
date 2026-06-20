from typing import List
import ollama
from app.model_router import fallback_chain, model_for_task, normalize_task, personality_for_task


def embed_text(text: str, task: str = "embedding") -> List[float]:
    text = (text or "")[:6000]
    res = ollama.embeddings(model=model_for_task(task), prompt=text)
    return res["embedding"]


def chat_text(
    prompt: str,
    system: str | None = None,
    *,
    task: str = "archivist_chat",
    fallback_task: str | None = None,
) -> str:
    messages = []
    if system:
        messages.append({"role": "system", "content": system})
    messages.append({"role": "user", "content": prompt})
    return chat_messages(messages, task=task, fallback_task=fallback_task)


def _chat_once(model: str, messages: list[dict[str, str]]) -> str:
    res = ollama.chat(model=model, messages=messages)
    return res["message"]["content"]


def routed_messages(messages: list[dict[str, str]], task: str) -> list[dict[str, str]]:
    overlay = personality_for_task(task)
    out = [dict(message) for message in messages]
    if not overlay:
        return out
    if out and out[0].get("role") == "system":
        out[0]["content"] = "\n\n".join([out[0].get("content") or "", overlay]).strip()
    else:
        out.insert(0, {"role": "system", "content": overlay})
    return out


def chat_messages(
    messages: list[dict[str, str]],
    *,
    task: str = "archivist_chat",
    fallback_task: str | None = None,
    apply_personality: bool = True,
) -> str:
    primary_task = normalize_task(task)
    tasks = [primary_task]
    if fallback_task is not None:
        tasks.extend(fallback_chain(fallback_task))
    else:
        tasks.extend(fallback_chain(primary_task)[1:])

    prepared_messages = routed_messages(messages, primary_task) if apply_personality else [dict(message) for message in messages]
    errors = []
    used_models = set()
    for candidate_task in tasks:
        model = model_for_task(candidate_task)
        if model in used_models:
            continue
        used_models.add(model)
        try:
            return _chat_once(model, prepared_messages)
        except Exception as error:
            errors.append(f"{candidate_task} ({model}): {error}")

    raise RuntimeError("Ollama failed for route chain: " + " | ".join(errors))

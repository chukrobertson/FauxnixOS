from __future__ import annotations

from fauxnix_tools.config import config

_ollama = None

MODEL_ROUTES = {
    "chat": config.ollama_chat_model,
    "code": config.ollama_chat_model,
    "reasoning": config.ollama_reason_model,
    "summary": config.ollama_summary_model,
    "vision": config.ollama_vision_model,
    "embedding": config.ollama_embed_model,
}

FALLBACK_CHAINS = {
    "vision": [config.ollama_vision_model, config.ollama_vision_fallback],
    "reasoning": [config.ollama_reason_model, config.ollama_chat_model],
    "summary": [config.ollama_summary_model, config.ollama_chat_model],
    "chat": [config.ollama_chat_model, config.ollama_reason_model],
}

TASK_ALIASES = {
    "default": "chat",
    "coding": "code",
    "code_agent": "code",
    "summarize": "summary",
    "reason": "reasoning",
    "embed": "embedding",
    "describe_image": "vision",
    "vision": "vision",
}

_installed_cache = None


def _get_installed() -> set[str]:
    global _installed_cache
    if _installed_cache is None:
        try:
            import ollama
            response = ollama.list()
            models = getattr(response, "models", []) or response.get("models", [])
            _installed_cache = set()
            for m in models:
                if isinstance(m, dict):
                    name = m.get("model") or m.get("name", "")
                else:
                    name = getattr(m, "model", None) or getattr(m, "name", None) or ""
                if name:
                    _installed_cache.add(str(name))
        except Exception:
            _installed_cache = set()
    return _installed_cache


def refresh_installed():
    global _installed_cache
    _installed_cache = None
    return _get_installed()


def normalize_task(task: str) -> str:
    t = (task or "chat").strip().lower()
    return TASK_ALIASES.get(t, t)


def model_for_task(task: str) -> str:
    task = normalize_task(task)
    model = MODEL_ROUTES.get(task, config.ollama_chat_model)
    installed = _get_installed()
    if model in installed:
        return model
    chain = FALLBACK_CHAINS.get(task, [])
    for fb in chain:
        if fb in installed:
            return fb
    return model


def fallback_chain(task: str) -> list[str]:
    task = normalize_task(task)
    primary = MODEL_ROUTES.get(task, config.ollama_chat_model)
    chain = FALLBACK_CHAINS.get(task, [])
    seen = set()
    result = []
    for m in [primary] + chain + [config.ollama_chat_model]:
        if m not in seen:
            seen.add(m)
            result.append(m)
    return result


def route_for_task(task: str) -> dict:
    task = normalize_task(task)
    chain = fallback_chain(task)
    return {"task": task, "model": chain[0] if chain else config.ollama_chat_model, "fallback_chain": chain}

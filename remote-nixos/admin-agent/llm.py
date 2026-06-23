from __future__ import annotations

import json
import os
import subprocess
import urllib.request
from dataclasses import dataclass, field
from typing import Literal


@dataclass
class LLMConfig:
    backend: Literal["ollama", "openai"] = "ollama"
    model: str = "llama3.2"
    ollama_url: str = "http://127.0.0.1:11434"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_model: str = "gpt-4o"
    temperature: float = 0.3
    max_tokens: int = 4096


def config_from_env() -> LLMConfig:
    backend = os.environ.get("FAUXNIX_LLM_BACKEND", "ollama")
    return LLMConfig(
        backend=backend,  # type: ignore
        model=os.environ.get("FAUXNIX_LLM_MODEL", "qwen2.5:0.5b-instruct"),
        ollama_url=os.environ.get("FAUXNIX_OLLAMA_URL", "http://127.0.0.1:11434"),
        openai_api_key=os.environ.get("FAUXNIX_OPENAI_API_KEY", ""),
        openai_base_url=os.environ.get("FAUXNIX_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        openai_model=os.environ.get("FAUXNIX_OPENAI_MODEL", "gpt-4o"),
        temperature=float(os.environ.get("FAUXNIX_LLM_TEMPERATURE", "0.3")),
        max_tokens=int(os.environ.get("FAUXNIX_LLM_MAX_TOKENS", "4096")),
    )


def llm_completion(
    messages: list[dict[str, str]],
    cfg: LLMConfig | None = None,
) -> str:
    if cfg is None:
        cfg = config_from_env()
    if cfg.backend == "openai":
        return _openai_completion(messages, cfg)
    return _ollama_completion(messages, cfg)


def _ollama_completion(messages: list[dict[str, str]], cfg: LLMConfig) -> str:
    body = json.dumps({
        "model": cfg.model,
        "messages": messages,
        "stream": False,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg.ollama_url}/api/chat",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data.get("message", {}).get("content", "")


def _openai_completion(messages: list[dict[str, str]], cfg: LLMConfig) -> str:
    body = json.dumps({
        "model": cfg.openai_model,
        "messages": messages,
        "temperature": cfg.temperature,
        "max_tokens": cfg.max_tokens,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{cfg.openai_base_url}/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {cfg.openai_api_key}",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        data = json.loads(resp.read())
    return data.get("choices", [{}])[0].get("message", {}).get("content", "")


def list_ollama_models() -> list[str]:
    try:
        req = urllib.request.Request(f"{config_from_env().ollama_url}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
        return [m["name"] for m in data.get("models", [])]
    except Exception:
        return []

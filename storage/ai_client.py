"""Small provider-agnostic client for OpenAI-compatible chat-completions APIs.

No API secret is written to disk.  The caller supplies the key for each
request (the UI keeps it in process memory only).
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Iterable, Mapping

DEFAULT_TIMEOUT = 45
MAX_CONTEXT_CHARS = 24000


def normalize_chat_endpoint(base_url: str) -> str:
    url = (base_url or "").strip().rstrip("/")
    if not url:
        raise ValueError("Enter an AI API base URL or chat-completions URL.")
    if not (url.startswith("https://") or url.startswith("http://")):
        raise ValueError("AI API URL must start with http:// or https://")
    if url.endswith("/chat/completions"):
        return url
    if url.endswith("/v1"):
        return url + "/chat/completions"
    return url + "/v1/chat/completions"


def clamp_document_context(text: str, max_chars: int = MAX_CONTEXT_CHARS) -> str:
    text = (text or "").strip()
    if len(text) <= max_chars:
        return text
    # Keep both the beginning and end; totals/footers can matter in documents.
    half = max_chars // 2
    return text[:half] + "\n\n[...document context truncated...]\n\n" + text[-half:]


def build_messages(history: Iterable[Mapping[str, str]], question: str,
                   document_context: str = ""):
    system = (
        "You are a document assistant inside a scanner app. Answer from the "
        "provided document context when one exists. If the context does not "
        "contain the answer, say that clearly instead of inventing details. "
        "Keep extracted names, numbers and dates exact."
    )
    messages = [{"role": "system", "content": system}]
    context = clamp_document_context(document_context)
    if context:
        messages.append({
            "role": "user",
            "content": "DOCUMENT CONTEXT:\n---\n" + context + "\n---",
        })
    for item in list(history)[-12:]:
        role = str(item.get("role", "")).strip().lower()
        content = str(item.get("content", "")).strip()
        if role in {"user", "assistant"} and content:
            messages.append({"role": role, "content": content})
    question = (question or "").strip()
    if not question:
        raise ValueError("Type a question first.")
    messages.append({"role": "user", "content": question})
    return messages


def chat_completion(base_url: str, api_key: str, model: str, messages,
                    timeout: int = DEFAULT_TIMEOUT) -> str:
    endpoint = normalize_chat_endpoint(base_url)
    model = (model or "").strip()
    if not model:
        raise ValueError("Enter the model name required by your provider.")
    key = (api_key or "").strip()
    if not key:
        raise ValueError("Enter your API key. It is kept only for this app session.")

    payload = json.dumps({
        "model": model,
        "messages": list(messages),
        "temperature": 0.2,
    }).encode("utf-8")
    req = urllib.request.Request(
        endpoint,
        data=payload,
        headers={
            "Authorization": "Bearer " + key,
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"AI service returned HTTP {exc.code}. {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not reach AI service: {exc.reason}") from exc

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"]
    except Exception as exc:
        raise RuntimeError("AI service returned an unsupported response format.") from exc
    if isinstance(content, list):
        # A few compatible providers use typed content parts.
        content = "\n".join(
            str(part.get("text", "")) for part in content if isinstance(part, dict)
        )
    answer = str(content or "").strip()
    if not answer:
        raise RuntimeError("AI service returned an empty answer.")
    return answer

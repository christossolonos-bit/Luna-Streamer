"""Shared Ollama HTTP client helpers for Luna streamer."""

from __future__ import annotations

import base64
import os
import sys
from pathlib import Path

from ollama import Client


def ollama_keep_alive() -> float | str | None:
    """From LUNA_OLLAMA_KEEP_ALIVE: -1 (forever), seconds as float, or string like 5m."""
    raw = (os.environ.get("LUNA_OLLAMA_KEEP_ALIVE") or "").strip()
    if not raw:
        return None
    if raw == "-1":
        return -1
    try:
        return float(raw)
    except ValueError:
        return raw


def _ollama_num_gpu_layers() -> int:
    """Layer offload count for Ollama (num_gpu). Empty env = max offload for faster GPU inference."""
    raw = (os.environ.get("LUNA_OLLAMA_NUM_GPU") or "").strip().lower()
    if raw in ("", "auto", "max"):
        return 999_999
    if raw in ("cpu", "none", "off"):
        return 0
    try:
        return int(raw)
    except ValueError:
        return 999_999


def build_ollama_options(*, for_screen: bool) -> dict | None:
    """num_predict caps generation length; num_gpu caps layers on GPU (default: max offload)."""
    out: dict[str, int | float] = {}
    if for_screen:
        raw = (os.environ.get("LUNA_SCREEN_NUM_PREDICT", "240") or "240").strip() or "240"
    else:
        raw = (os.environ.get("LUNA_OLLAMA_NUM_PREDICT") or "").strip()
    if raw:
        try:
            out["num_predict"] = max(32, int(raw))
        except ValueError:
            pass
    temp = (os.environ.get("LUNA_OLLAMA_TEMPERATURE") or "").strip()
    if temp:
        try:
            out["temperature"] = float(temp)
        except ValueError:
            pass
    out["num_gpu"] = _ollama_num_gpu_layers()
    return out or None


def configure_stdio_utf8() -> None:
    if sys.platform == "win32":
        for stream in (sys.stdout, sys.stderr):
            if hasattr(stream, "reconfigure"):
                stream.reconfigure(encoding="utf-8", errors="replace")


def encode_image(path: Path) -> str:
    data = path.read_bytes()
    return base64.b64encode(data).decode("ascii")


def build_client() -> Client:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return Client(host=host)


def chat_request_kwargs(
    model: str,
    messages: list[dict],
    *,
    stream: bool,
) -> dict:
    """Shared kwargs for client.chat (options, keep_alive)."""
    ka = ollama_keep_alive()
    opts = build_ollama_options(for_screen=False)
    kwargs: dict = {"model": model, "messages": messages, "stream": stream}
    if opts is not None:
        kwargs["options"] = opts
    if ka is not None:
        kwargs["keep_alive"] = ka
    return kwargs


def summarize_viewer_screen(client: Client, model: str, image_b64: str) -> str:
    """Run a single vision chat turn on a base64 JPEG/PNG (no stream, no stdout)."""
    prompt = os.environ.get(
        "LUNA_SCREEN_SUMMARY_PROMPT",
        (
            "You are helping a stream assistant. Describe what is visible on this screen capture "
            "in 2-5 short sentences. Name open applications, games, prominent on-screen text, and the main activity. "
            "If unreadable or empty, say (screen unclear). No markdown, plain text only."
        ),
    ).strip()
    ka = ollama_keep_alive()
    opts = build_ollama_options(for_screen=True)
    kwargs: dict = {
        "model": model,
        "messages": [
            {
                "role": "user",
                "content": prompt,
                "images": [image_b64],
            }
        ],
        "stream": False,
    }
    if opts is not None:
        kwargs["options"] = opts
    if ka is not None:
        kwargs["keep_alive"] = ka
    response = client.chat(**kwargs)
    return (response.message.content or "").strip()


def chat_once(
    client: Client,
    model: str,
    messages: list[dict],
    *,
    stream: bool,
) -> str:
    if stream:
        kwargs = chat_request_kwargs(model, messages, stream=True)
        log = os.environ.get("LUNA_OLLAMA_PRINT_STREAM", "").strip().lower() in (
            "1",
            "true",
            "yes",
        )
        parts: list[str] = []
        for chunk in client.chat(**kwargs):
            if chunk.message and chunk.message.content:
                piece = chunk.message.content
                parts.append(piece)
                if log:
                    sys.stdout.write(piece)
                    sys.stdout.flush()
        if log:
            sys.stdout.write("\n")
        return "".join(parts)

    kwargs = chat_request_kwargs(model, messages, stream=False)
    response = client.chat(**kwargs)
    text = (response.message.content or "").strip()
    print(text)
    return text

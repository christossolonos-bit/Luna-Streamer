"""Shared Ollama HTTP client helpers for Luna streamer."""

from __future__ import annotations

import base64
import inspect
import os
import re
import sys
from pathlib import Path

from ollama import Client

# Older `ollama` Python SDKs reject unknown kwargs (TypeError on the `think`
# argument). Detect once so we can either pass the kwarg or fall back to a
# `/no_think` directive in the user message (qwen3 / deepseek-r1 family).
try:
    _CHAT_SIG_PARAMS = set(inspect.signature(Client.chat).parameters.keys())
except (TypeError, ValueError):
    _CHAT_SIG_PARAMS = set()
_THINK_KWARG_SUPPORTED = "think" in _CHAT_SIG_PARAMS or "kwargs" in _CHAT_SIG_PARAMS


_THINK_BLOCK_RE = re.compile(
    r"<\s*(think|thinking|reasoning)\s*>.*?<\s*/\s*\1\s*>",
    flags=re.IGNORECASE | re.DOTALL,
)
_THINK_OPEN_RE = re.compile(r"<\s*(think|thinking|reasoning)\s*>", flags=re.IGNORECASE)
_THINK_CLOSE_RE = re.compile(r"<\s*/\s*(think|thinking|reasoning)\s*>", flags=re.IGNORECASE)


def strip_think_blocks(text: str) -> str:
    """Remove any <think>...</think> / <thinking>...</thinking> reasoning blocks.

    Reasoning-tuned models (qwen3, deepseek-r1, etc.) emit a hidden chain-of-thought
    section that should never reach Twitch/Discord/viewer/TTS.
    """
    if not text:
        return text
    cleaned = _THINK_BLOCK_RE.sub("", text)
    # Defensive: drop any unmatched stray tag.
    cleaned = _THINK_OPEN_RE.sub("", cleaned)
    cleaned = _THINK_CLOSE_RE.sub("", cleaned)
    return cleaned.strip()


class ThinkStripper:
    """Streaming filter: hide tokens inside <think>...</think> from consumers.

    Feed it chunks via ``feed`` and it returns only the visible (post-thinking)
    portion. Use ``finalize`` at end of stream in case the model never closed the
    tag.
    """

    def __init__(self) -> None:
        self._buf = ""
        self._inside = False

    def feed(self, piece: str) -> str:
        if not piece:
            return ""
        self._buf += piece
        out: list[str] = []
        while self._buf:
            if self._inside:
                m = _THINK_CLOSE_RE.search(self._buf)
                if not m:
                    # Still inside the think block, drop everything we have so far.
                    self._buf = ""
                    break
                # Drop up to and including the closing tag.
                self._buf = self._buf[m.end():]
                self._inside = False
                continue
            m = _THINK_OPEN_RE.search(self._buf)
            if not m:
                # No open tag in sight. Keep a small tail in case a tag is split
                # across chunks (longest token here is "<thinking>" = 10 chars).
                if len(self._buf) > 16:
                    out.append(self._buf[:-16])
                    self._buf = self._buf[-16:]
                break
            # Emit anything before the open tag, then enter think mode.
            if m.start() > 0:
                out.append(self._buf[: m.start()])
            self._buf = self._buf[m.end():]
            self._inside = True
        return "".join(out)

    def finalize(self) -> str:
        # If the stream ended outside a think block, flush the remaining tail.
        if not self._inside:
            tail, self._buf = self._buf, ""
            return tail
        # Inside an unclosed think block: discard.
        self._buf = ""
        return ""


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
        # Default 400 so reasoning-tuned models can't ramble for 30s on a
        # one-line prompt. Override via LUNA_OLLAMA_NUM_PREDICT (use 0 / -1 for
        # unlimited if you really want it).
        raw = (os.environ.get("LUNA_OLLAMA_NUM_PREDICT") or "400").strip()
    if raw:
        try:
            n = int(raw)
        except ValueError:
            n = 400
        if n > 0:
            out["num_predict"] = max(32, n)
    temp = (os.environ.get("LUNA_OLLAMA_TEMPERATURE") or "").strip()
    if temp:
        try:
            out["temperature"] = float(temp)
        except ValueError:
            pass
    out["num_gpu"] = _ollama_num_gpu_layers()
    return out or None


def ollama_think_mode() -> bool | None:
    """Read LUNA_OLLAMA_THINK. Default False (reasoning models go straight to answer)."""
    raw = (os.environ.get("LUNA_OLLAMA_THINK") or "").strip().lower()
    if raw == "":
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    if raw in ("0", "false", "no", "off"):
        return False
    return None


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


def _apply_think_directive(messages: list[dict], think: bool) -> list[dict]:
    """Inject /no_think (or /think) at the end of the last user turn.

    Used when the installed Ollama SDK doesn't accept the ``think`` kwarg.
    Qwen3, DeepSeek-R1, and a few other reasoning models honour this prompt
    directive and skip / keep the chain-of-thought accordingly. For models
    that don't recognise it, the directive is just a trailing token and has
    no harmful effect.
    """
    if not messages:
        return messages
    directive = "/no_think" if not think else "/think"
    out = [dict(m) for m in messages]
    for i in range(len(out) - 1, -1, -1):
        if out[i].get("role") == "user":
            content = (out[i].get("content") or "").rstrip()
            if directive not in content:
                out[i]["content"] = f"{content}\n\n{directive}"
            return out
    return out


def chat_request_kwargs(
    model: str,
    messages: list[dict],
    *,
    stream: bool,
) -> dict:
    """Shared kwargs for client.chat (options, keep_alive, think)."""
    ka = ollama_keep_alive()
    opts = build_ollama_options(for_screen=False)
    think = ollama_think_mode()
    final_messages = messages
    if think is not None and not _THINK_KWARG_SUPPORTED:
        # SDK is too old to accept `think=...`; fall back to a prompt directive
        # so we still get the no-thinking speed gain on supporting models.
        final_messages = _apply_think_directive(messages, think)
    kwargs: dict = {"model": model, "messages": final_messages, "stream": stream}
    if opts is not None:
        kwargs["options"] = opts
    if ka is not None:
        kwargs["keep_alive"] = ka
    if think is not None and _THINK_KWARG_SUPPORTED:
        kwargs["think"] = think
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
    think = ollama_think_mode()
    base_messages = [
        {
            "role": "user",
            "content": prompt,
            "images": [image_b64],
        }
    ]
    final_messages = base_messages
    if think is not None and not _THINK_KWARG_SUPPORTED:
        final_messages = _apply_think_directive(base_messages, think)
    kwargs: dict = {
        "model": model,
        "messages": final_messages,
        "stream": False,
    }
    if opts is not None:
        kwargs["options"] = opts
    if ka is not None:
        kwargs["keep_alive"] = ka
    if think is not None and _THINK_KWARG_SUPPORTED:
        kwargs["think"] = think
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

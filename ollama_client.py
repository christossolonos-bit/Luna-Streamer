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


def llm_provider() -> str:
    """``ollama`` (default) or ``openrouter`` for cloud chat (see OPENROUTER_API_KEY)."""
    raw = (os.environ.get("LUNA_LLM_PROVIDER") or "ollama").strip().lower()
    if raw in ("openrouter", "or", "cloud"):
        return "openrouter"
    return "ollama"


def openrouter_configured() -> bool:
    return bool((os.environ.get("OPENROUTER_API_KEY") or "").strip())


def openrouter_streaming_enabled() -> bool:
    """SSE streaming to the viewer is off by default (more reliable on Windows + free tier)."""
    raw = (os.environ.get("LUNA_OPENROUTER_STREAM") or "").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _parse_model_list(raw: str) -> list[str]:
    out: list[str] = []
    for part in raw.replace(",", " ").split():
        m = part.strip()
        if m and m not in out:
            out.append(m)
    return out


def openrouter_model_candidates(primary: str, *, vision: bool = False) -> list[str]:
    """Primary model first, then fallbacks (used on HTTP 429)."""
    main = (primary or "").strip()
    if not main:
        main = resolve_vision_model() if vision else resolve_chat_model()
    fb_key = (
        "LUNA_OPENROUTER_VISION_MODEL_FALLBACKS"
        if vision
        else "LUNA_OPENROUTER_MODEL_FALLBACKS"
    )
    fb_default = (
        "openrouter/free,nvidia/nemotron-nano-12b-v2-vl:free,meta-llama/llama-3.2-3b-instruct:free"
        if vision
        else (
            "openrouter/free,meta-llama/llama-3.3-70b-instruct:free,"
            "qwen/qwen3-next-80b-a3b-instruct:free,meta-llama/llama-3.2-3b-instruct:free"
        )
    )
    fallbacks = _parse_model_list((os.environ.get(fb_key) or fb_default).strip())
    ordered: list[str] = []
    for m in [main, *fallbacks]:
        if m and m not in ordered:
            ordered.append(m)
    return ordered or ["openrouter/free"]


def _openrouter_is_rate_limited(exc: BaseException) -> bool:
    msg = str(exc).lower()
    return "429" in msg or "rate-limit" in msg or "rate limited" in msg


def _openrouter_should_try_fallback(exc: BaseException) -> bool:
    """Retry next model on provider throttle or missing/invalid model id."""
    if _openrouter_is_rate_limited(exc):
        return True
    msg = str(exc).lower()
    return (
        "404" in msg
        or "not found" in msg
        or "no endpoints" in msg
        or "invalid model" in msg
        or "does not exist" in msg
    )


def resolve_chat_model() -> str:
    if llm_provider() == "openrouter":
        return (
            (os.environ.get("LUNA_OPENROUTER_MODEL") or "").strip()
            or (os.environ.get("LUNA_CHAT_MODEL") or "").strip()
            or (os.environ.get("OPENROUTER_MODEL") or "").strip()
            or "openrouter/free"
        )
    return (
        (os.environ.get("LUNA_CHAT_MODEL") or "").strip()
        or (os.environ.get("OLLAMA_MODEL") or "").strip()
        or (os.environ.get("OLLAMA_CHAT_MODEL") or "").strip()
        or "gemma4:e4b"
    )


def vision_provider() -> str:
    """``ollama`` or ``openrouter``. Defaults to match chat when ``LUNA_LLM_PROVIDER=openrouter``."""
    raw = (os.environ.get("LUNA_VISION_PROVIDER") or "").strip().lower()
    if raw == "ollama":
        return "ollama"
    if raw in ("openrouter", "or", "cloud"):
        return "openrouter"
    if llm_provider() == "openrouter":
        return "openrouter"
    return "ollama"


def resolve_vision_model() -> str:
    if vision_provider() == "openrouter":
        return (
            (os.environ.get("LUNA_OPENROUTER_VISION_MODEL") or "").strip()
            or "nvidia/nemotron-nano-12b-v2-vl:free"
        )
    return (
        (os.environ.get("LUNA_SCREEN_VISION_MODEL") or "").strip()
        or (os.environ.get("OLLAMA_VISION_MODEL") or "").strip()
        or (os.environ.get("OLLAMA_MODEL") or "").strip()
        or "gemma4:e4b"
    )


def _openrouter_timeout_sec(*, vision: bool = False) -> int:
    key = "LUNA_OPENROUTER_VISION_TIMEOUT_SEC" if vision else "LUNA_OPENROUTER_TIMEOUT_SEC"
    default = "180" if vision else "120"
    raw = (os.environ.get(key) or default).strip() or default
    try:
        return max(30, min(int(raw), 600))
    except ValueError:
        return 180 if vision else 120


def build_ollama_client() -> Client:
    host = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
    return Client(host=host)


class _CompatMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _CompatChunk:
    def __init__(self, content: str) -> None:
        self.message = _CompatMessage(content)


class _CompatResponse:
    def __init__(self, content: str) -> None:
        self.message = _CompatMessage(content)


class OpenRouterChatClient:
    """OpenAI-compatible chat client for OpenRouter (free models use ``:free`` suffix or ``openrouter/free``)."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        http_referer: str = "",
        app_title: str = "Luna Streamer",
    ) -> None:
        self._api_key = api_key.strip()
        self._base_url = (
            (base_url or os.environ.get("OPENROUTER_BASE_URL") or "https://openrouter.ai/api/v1")
            .strip()
            .rstrip("/")
        )
        self._http_referer = (http_referer or os.environ.get("OPENROUTER_HTTP_REFERER") or "").strip()
        self._app_title = (app_title or os.environ.get("OPENROUTER_APP_TITLE") or "Luna Streamer").strip()

    def _headers(self) -> dict[str, str]:
        h = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_referer:
            h["HTTP-Referer"] = self._http_referer
        if self._app_title:
            h["X-OpenRouter-Title"] = self._app_title
        return h

    @staticmethod
    def _b64_image_data_url(b64: str) -> str:
        raw = (b64 or "").strip()
        if raw.startswith("data:"):
            return raw
        mime = "image/jpeg"
        try:
            pad = "=" * ((4 - len(raw) % 4) % 4)
            head = base64.b64decode(raw[:48] + pad)
            if head[:8] == b"\x89PNG\r\n\x1a\n":
                mime = "image/png"
            elif head[:3] == b"GIF":
                mime = "image/gif"
            elif head[:4] == b"RIFF" and len(head) >= 12 and head[8:12] == b"WEBP":
                mime = "image/webp"
        except Exception:
            pass
        return f"data:{mime};base64,{raw}"

    @staticmethod
    def _message_images(message: dict) -> list[str]:
        images = message.get("images")
        if not images:
            return []
        if isinstance(images, str):
            return [images] if images.strip() else []
        return [str(i) for i in images if i]

    @staticmethod
    def _messages_have_images(messages: list[dict]) -> bool:
        return any(OpenRouterChatClient._message_images(m) for m in messages)

    @staticmethod
    def _normalize_messages(messages: list[dict]) -> list[dict]:
        out: list[dict] = []
        for m in messages:
            role = str(m.get("role") or "user").strip()
            if role not in ("system", "user", "assistant"):
                role = "user"
            content = m.get("content")
            if content is None:
                text = ""
            elif isinstance(content, str):
                text = content
            else:
                text = str(content)
            images = OpenRouterChatClient._message_images(m)
            if images:
                parts: list[dict] = []
                if text.strip():
                    parts.append({"type": "text", "text": text.strip()})
                for img in images:
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": OpenRouterChatClient._b64_image_data_url(img),
                            },
                        }
                    )
                if not parts:
                    parts.append({"type": "text", "text": "Describe the image."})
                out.append({"role": role, "content": parts})
            else:
                out.append({"role": role, "content": text})
        return out

    def _max_tokens_from_options(self, options: dict | None) -> int | None:
        opts = options or {}
        raw = opts.get("num_predict")
        if raw is None:
            raw = (os.environ.get("LUNA_OPENROUTER_MAX_TOKENS") or os.environ.get("LUNA_OLLAMA_NUM_PREDICT") or "400").strip()
        try:
            n = int(raw)
        except (TypeError, ValueError):
            n = 400
        return max(32, n) if n > 0 else None

    def _temperature_from_options(self, options: dict | None) -> float | None:
        opts = options or {}
        raw = opts.get("temperature")
        if raw is None:
            raw = (os.environ.get("LUNA_OLLAMA_TEMPERATURE") or "").strip()
        if not raw:
            return None
        try:
            return float(raw)
        except ValueError:
            return None

    def _post_json(self, payload: dict, *, timeout_sec: int | None = None) -> dict:
        import json
        import urllib.error
        import urllib.request

        url = f"{self._base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        timeout = timeout_sec if timeout_sec is not None else _openrouter_timeout_sec(vision=False)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                body = resp.read().decode("utf-8", errors="replace")
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            hint = ""
            if exc.code == 401:
                hint = " Check OPENROUTER_API_KEY at https://openrouter.ai/keys"
            raise RuntimeError(
                f"OpenRouter HTTP {exc.code}: {err_body[:500] or exc.reason}{hint}"
            ) from exc
        return json.loads(body)

    def _stream_chunks(self, payload: dict, *, timeout_sec: int | None = None):
        import json
        import urllib.error
        import urllib.request

        payload = dict(payload)
        payload["stream"] = True
        url = f"{self._base_url}/chat/completions"
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(url, data=data, headers=self._headers(), method="POST")
        timeout = timeout_sec if timeout_sec is not None else _openrouter_timeout_sec(vision=False)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                for raw_line in resp:
                    line = raw_line.decode("utf-8", errors="replace").strip()
                    if not line or not line.startswith("data:"):
                        continue
                    piece = line[5:].strip()
                    if piece == "[DONE]":
                        break
                    try:
                        evt = json.loads(piece)
                    except json.JSONDecodeError:
                        continue
                    choices = evt.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    content = delta.get("content")
                    if content:
                        yield _CompatChunk(content)
        except urllib.error.HTTPError as exc:
            err_body = ""
            try:
                err_body = exc.read().decode("utf-8", errors="replace")
            except Exception:
                pass
            raise RuntimeError(f"OpenRouter HTTP {exc.code}: {err_body[:500] or exc.reason}") from exc
        except (ConnectionResetError, BrokenPipeError, TimeoutError) as exc:
            raise RuntimeError(f"OpenRouter stream disconnected: {exc}") from exc

    def chat(self, **kwargs):  # noqa: ANN003
        raw_messages = list(kwargs.get("messages") or [])
        model = str(kwargs.get("model") or resolve_chat_model())
        messages = self._normalize_messages(raw_messages)
        stream = bool(kwargs.get("stream", False))
        options = kwargs.get("options")
        vision = self._messages_have_images(raw_messages)
        timeout = _openrouter_timeout_sec(vision=vision)
        body: dict = {"messages": messages}
        max_tokens = self._max_tokens_from_options(options if isinstance(options, dict) else None)
        if max_tokens is not None:
            body["max_tokens"] = max_tokens
        temp = self._temperature_from_options(options if isinstance(options, dict) else None)
        if temp is not None:
            body["temperature"] = temp

        candidates = openrouter_model_candidates(model, vision=vision)
        last_err: BaseException | None = None
        for idx, try_model in enumerate(candidates):
            body["model"] = try_model
            try:
                if stream:
                    if idx > 0:
                        print(f"(openrouter) streaming via fallback {try_model!r}", flush=True)
                    return self._stream_chunks(body, timeout_sec=timeout)
                data = self._post_json(body, timeout_sec=timeout)
                choices = data.get("choices") or []
                if not choices:
                    return _CompatResponse("")
                msg = choices[0].get("message") or {}
                text = (msg.get("content") or "").strip()
                if idx > 0:
                    print(f"(openrouter) ok on fallback {try_model!r}", flush=True)
                return _CompatResponse(text)
            except RuntimeError as exc:
                last_err = exc
                if _openrouter_should_try_fallback(exc) and idx < len(candidates) - 1:
                    nxt = candidates[idx + 1]
                    why = "rate-limited" if _openrouter_is_rate_limited(exc) else "unavailable"
                    print(
                        f"(openrouter) {try_model!r} {why} — trying {nxt!r}",
                        flush=True,
                    )
                    continue
                raise
        if last_err is not None:
            raise last_err
        return _CompatResponse("")


def build_client() -> Client | OpenRouterChatClient:
    if llm_provider() == "openrouter":
        key = (os.environ.get("OPENROUTER_API_KEY") or "").strip()
        if not key:
            raise RuntimeError(
                "LUNA_LLM_PROVIDER=openrouter requires OPENROUTER_API_KEY "
                "(create one at https://openrouter.ai/keys)"
            )
        return OpenRouterChatClient(api_key=key)
    return build_ollama_client()


def build_vision_client() -> Client | OpenRouterChatClient:
    """Chat + vision client (OpenRouter multimodal when ``LUNA_LLM_PROVIDER=openrouter``)."""
    if vision_provider() == "openrouter":
        if not openrouter_configured():
            raise RuntimeError(
                "OpenRouter vision requires OPENROUTER_API_KEY "
                "(https://openrouter.ai/keys)"
            )
        return build_client()
    return build_ollama_client()


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


def _openrouter_chat_kwargs(
    model: str,
    messages: list[dict],
    *,
    stream: bool,
) -> dict:
    opts = build_ollama_options(for_screen=False)
    return {
        "model": model,
        "messages": messages,
        "stream": stream,
        "options": opts,
    }


def chat_request_kwargs(
    model: str,
    messages: list[dict],
    *,
    stream: bool,
) -> dict:
    """Shared kwargs for client.chat (options, keep_alive, think)."""
    if llm_provider() == "openrouter":
        return _openrouter_chat_kwargs(model, messages, stream=stream)
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


def summarize_viewer_screen(client: Client | OpenRouterChatClient, model: str, image_b64: str) -> str:
    """Run a single vision chat turn on a base64 JPEG/PNG (no stream, no stdout)."""
    prompt = os.environ.get(
        "LUNA_SCREEN_SUMMARY_PROMPT",
        (
            "You are helping a stream assistant. Describe what is visible on this screen capture "
            "in 2-5 short sentences. Name open applications, games, prominent on-screen text, and the main activity. "
            "If unreadable or empty, say (screen unclear). No markdown, plain text only."
        ),
    ).strip()
    base_messages = [
        {
            "role": "user",
            "content": prompt,
            "images": [image_b64],
        }
    ]
    if isinstance(client, OpenRouterChatClient):
        opts = build_ollama_options(for_screen=True) or {}
        kwargs: dict = {
            "model": model or resolve_vision_model(),
            "messages": base_messages,
            "stream": False,
            "options": opts,
        }
        ka_screen = _screen_keep_alive()
        if ka_screen is not None:
            kwargs["keep_alive"] = ka_screen
        response = client.chat(**kwargs)
        return (response.message.content or "").strip()
    ka = _screen_keep_alive()
    opts = build_ollama_options(for_screen=True)
    think = ollama_think_mode()
    final_messages = base_messages
    if think is not None and not _THINK_KWARG_SUPPORTED:
        final_messages = _apply_think_directive(base_messages, think)
    kwargs = {
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


def _screen_keep_alive() -> float | str | int | None:
    try:
        from luna_perf import screen_ollama_keep_alive

        return screen_ollama_keep_alive()
    except ImportError:
        return ollama_keep_alive()


def describe_youtube_video(
    client: Client | OpenRouterChatClient,
    model: str,
    images_b64: list[str],
    *,
    title: str = "",
) -> str:
    """Describe a YouTube video from evenly spaced JPEG frames."""
    if not images_b64:
        return ""
    title_line = f'Video title: {(title or "").strip() or "(unknown)"}\n'
    default_prompt = (
        "You are helping a stream host comment on a YouTube video. "
        f"{title_line}"
        f"You are shown {len(images_b64)} frame(s) sampled across the video.\n"
        "Describe what the video is about in 4-8 short sentences: setting, visuals, mood, "
        "on-screen text if readable, and what a viewer would take away. "
        "If it is mostly music/visuals with no speech, say that. Plain text only, no markdown."
    )
    prompt = (os.environ.get("LUNA_YT_VISION_PROMPT") or default_prompt).strip()
    prompt = prompt.replace("{title}", (title or "").strip()).replace("{n_frames}", str(len(images_b64)))
    predict_raw = (os.environ.get("LUNA_YT_VISION_NUM_PREDICT") or "320").strip() or "320"
    try:
        predict = max(64, int(predict_raw))
    except ValueError:
        predict = 320
    base_messages = [
        {
            "role": "user",
            "content": prompt,
            "images": images_b64,
        }
    ]
    if isinstance(client, OpenRouterChatClient):
        opts = build_ollama_options(for_screen=True) or {}
        opts = dict(opts)
        opts["num_predict"] = predict
        response = client.chat(
            model=model or resolve_vision_model(),
            messages=base_messages,
            stream=False,
            options=opts,
        )
        return (response.message.content or "").strip()
    ka = ollama_keep_alive()
    opts = build_ollama_options(for_screen=True) or {}
    opts = dict(opts)
    opts["num_predict"] = predict
    think = ollama_think_mode()
    final_messages = base_messages
    if think is not None and not _THINK_KWARG_SUPPORTED:
        final_messages = _apply_think_directive(base_messages, think)
    kwargs = {
        "model": model,
        "messages": final_messages,
        "stream": False,
        "options": opts,
    }
    if ka is not None:
        kwargs["keep_alive"] = ka
    if think is not None and _THINK_KWARG_SUPPORTED:
        kwargs["think"] = think
    response = client.chat(**kwargs)
    return (response.message.content or "").strip()


def chat_once(
    client: Client | OpenRouterChatClient,
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

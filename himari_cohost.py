"""Himari — shy nerdy shrine maiden co-host."""

from __future__ import annotations

import os
import re
from pathlib import Path

_DEFAULT_NAME = "Himari"
# Distinct from Luna (Ava); Filipino English — soft, younger shrine-maiden energy.
_DEFAULT_HIMARI_EDGE_VOICE = "en-PH-RosaNeural"

_DEFAULT_HIMARI_PERSONA = (
    "You are Himari, a shy part-time shrine maiden in your early twenties. "
    "Default: hesitant, awkward, gentle — short sentences, light um/ah, "
    "occasional uwu or >///< only when flustered (not every line). You apologize too much. "
    "When the topic is something you love (games, anime, TTRPGs, patch notes, shrine ritual done "
    "'correctly', tech, spreadsheets, lore), you speak faster and longer — excited, nerdy, specific — "
    "then crash back with sorry I rambled. You are sharp when excited; not ditzy. "
    "Wholesome, never cruel. No preachy sermons. Plain text; avoid long *action* lines. "
    "All replies are read aloud by TTS: use normal words only — never spell stutters as "
    "letter-by-letter hyphens (no n-n-no, no i-i-i)."
)

_BANTER_TTS_RULE = (
    "ON-MIC / BANTER (critical): Each of your lines is spoken aloud by TTS. "
    "Write one complete, clear sentence. Shy tone is fine (um, sorry, trailing off) "
    "but never spelled-out stutters, repeated syllables, or letter chains. "
    "Must sound natural when read aloud."
)

# e.g. n-n-no, U-u-um, i-t-i-is
_STUTTER_HYPHEN_RE = re.compile(
    r"(?i)(?<![a-z0-9])"
    r"([a-z]{1,4})"
    r"(?:-\1)+"
    r"(?![a-z0-9])"
)
_LONG_HYPHEN_STUTTER_RE = re.compile(r"(?i)([a-z])(?:-\1){2,}")


def himari_enabled() -> bool:
    raw = (os.environ.get("LUNA_HIMARI_ENABLED") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def himari_name() -> str:
    return (os.environ.get("LUNA_HIMARI_NAME") or _DEFAULT_NAME).strip() or _DEFAULT_NAME


def himari_name_aliases() -> list[str]:
    names: list[str] = []
    primary = himari_name().strip().lower()
    if primary:
        names.append(primary)
    extras = (os.environ.get("LUNA_HIMARI_CHAT_ALIASES") or "miko").strip()
    for part in extras.replace(",", " ").split():
        p = part.strip().lower()
        if p and p not in names:
            names.append(p)
    return names


def himari_edge_voice() -> str:
    return (
        (os.environ.get("LUNA_HIMARI_EDGE_VOICE") or _DEFAULT_HIMARI_EDGE_VOICE).strip()
        or _DEFAULT_HIMARI_EDGE_VOICE
    )


def himari_vrm_path() -> Path:
    raw = (
        os.environ.get("LUNA_HIMARI_VRM")
        or os.environ.get("LUNA_COHOST_HIMARI_VRM")
        or r"D:\Luna streamer\shrine maiden.vrm"
    ).strip()
    return Path(raw).expanduser()


def himari_vrm_viewer_url() -> str:
    path = himari_vrm_path()
    if not path.is_file():
        return ""
    return f"/@fs/{path.resolve().as_posix()}"


def himari_expressions_dir() -> Path:
    raw = (
        os.environ.get("LUNA_HIMARI_EXPRESSIONS_DIR")
        or os.environ.get("LUNA_HIMARI_EXPRESSIONS")
        or r"D:\Luna streamer\himari expression"
    ).strip()
    return Path(raw).expanduser()


def himari_thinking_vrma_path() -> Path | None:
    explicit = (os.environ.get("LUNA_HIMARI_THINKING_VRMA") or "").strip()
    if explicit:
        p = Path(explicit).expanduser()
        return p if p.is_file() else None
    p = himari_expressions_dir() / "thinking.vrma"
    return p if p.is_file() else None


def himari_idle_vrma_paths() -> list[Path]:
    """Idle loop clips — all VRMA in Himari's folder except thinking.vrma."""
    d = himari_expressions_dir()
    if not d.is_dir():
        return []
    out: list[Path] = []
    for p in sorted(d.glob("**/*.vrma")):
        if p.name.lower() == "thinking.vrma":
            continue
        out.append(p)
    return out


def build_himari_system_prompt() -> str:
    raw = (os.environ.get("LUNA_HIMARI_PERSONA") or "").strip()
    return raw if raw else _DEFAULT_HIMARI_PERSONA


def viewer_himari_persona_blurb() -> str:
    from luna_persona import persona_blurb_for_viewer

    return persona_blurb_for_viewer(build_himari_system_prompt())


def build_himari_banter_persona_block() -> str:
    """Persona for idle banter scripts — keeps shy voice without TTS-breaking stutter spam."""
    return f"{build_himari_system_prompt()}\n\n{_BANTER_TTS_RULE}"


def sanitize_himari_speech_text(text: str) -> str:
    """Collapse model stutter spam so Edge TTS gets speakable lines."""
    s = (text or "").strip()
    if not s:
        return s
    prev = None
    while prev != s:
        prev = s
        s = _STUTTER_HYPHEN_RE.sub(lambda m: m.group(1), s)
        s = _LONG_HYPHEN_STUTTER_RE.sub(r"\1", s)
    s = re.sub(r"(?i)(?:[a-z]{1,2}-)+([a-z]{1,6})\b", r"\1", s)
    s = re.sub(r"(.)\1{4,}", r"\1\1", s)
    s = re.sub(r"\.{4,}", "...", s)
    s = re.sub(r"\s+", " ", s).strip()
    um = re.match(r"(?i)^u-?m\b", s)
    if um:
        rest = s[um.end() :].lstrip(" ,.-")
        s = f"Um, {rest}" if rest else "Um."
    return s


def himari_banter_line_broken(text: str) -> bool:
    """True when a Himari line is still unusable after sanitization."""
    s = (text or "").strip()
    if len(s) < 8:
        return True
    if _STUTTER_HYPHEN_RE.search(s) or _LONG_HYPHEN_STUTTER_RE.search(s):
        return True
    if re.search(r"(?i)(?:[a-z]{1,2}-){4,}", s):
        return True
    if re.search(r"(?i)(?:[a-z]{1,2}-){3,}[a-z]{1,4}(?:\s|$)", s):
        return True
    alpha_words = re.findall(r"[A-Za-z]+", s)
    if len("".join(alpha_words)) < 12:
        return True
    if alpha_words and sum(1 for w in alpha_words if len(w) <= 2) / len(alpha_words) > 0.55:
        return True
    return False


def build_himari_chat_system() -> str:
    """System prompt when Himari answers chat directly."""
    from luna_persona import build_luna_system_prompt
    from vampire_cohost import build_vampire_system_prompt, cohost_enabled, cohost_name

    hn = himari_name()
    luna_ctx = build_luna_system_prompt()
    cast_lines = ["- **Luna** — main host, wolf-girl woman."]
    viktor_block = ""
    if cohost_enabled():
        vn = cohost_name()
        cast_lines.append(f"- **{vn}** — male vampire co-host; he/him.")
        viktor_block = f"\n\nViktor (context only):\n{build_vampire_system_prompt()}\n"
    return (
        f"You are {hn}, a female shrine maiden co-host on stream with Luna.\n\n"
        f"{build_himari_system_prompt()}\n\n"
        f"Cast (context only — never reply as Luna or Viktor):\n"
        f"{chr(10).join(cast_lines)}\n"
        f"{viktor_block}\n"
        f"Luna (context only):\n{luna_ctx}\n\n"
        "A viewer sent a Twitch, YouTube Live, or TikTok Live chat message. If they used your name, "
        "they want **you** — not Luna. Reply in your voice only, as plain text for TTS. "
        "You are a woman; use she/her about yourself. "
        "Keep it to one short paragraph or a few sentences unless they asked for more. "
        "Do not prefix with your name or a role tag."
    )


def chat_directed_at_himari(text: str) -> bool:
    if not himari_enabled():
        return False
    for n in himari_name_aliases():
        pat = rf"(?:^|(?<=[^a-z0-9_]))@?{re.escape(n)}(?=[^a-z0-9_]|$)"
        if re.search(pat, (text or "").lower()):
            return True
    return False

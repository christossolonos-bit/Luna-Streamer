"""Idle Luna ↔ vampire co-host banter (separate persona, dual TTS)."""

from __future__ import annotations

import asyncio
import re
from typing import TYPE_CHECKING

from luna_persona import build_luna_system_prompt
from ollama_client import build_client, chat_request_kwargs, strip_think_blocks
from vampire_cohost import (
    build_vampire_system_prompt,
    cohost_after_chat_sec,
    cohost_enabled,
    cohost_min_gap_sec,
    cohost_name,
    cohost_poll_sec,
)

if TYPE_CHECKING:
    from twitch_bot import LunaTwitchBot


def _generate_banter_script_sync(
    *,
    model: str,
    luna_name: str,
    cohost: str,
    max_lines: int,
    full_conversation: bool = False,
    presence_block: str = "",
) -> list[tuple[str, str]]:
    """Return [(speaker, text), ...] with speaker ``luna`` or ``cohost``."""
    luna_persona = build_luna_system_prompt()
    vampire = build_vampire_system_prompt()
    extra = f"\n\n{presence_block.strip()}" if (presence_block or "").strip() else ""
    if full_conversation:
        system = (
            "You write a full, natural back-and-forth conversation between two co-hosts while the stream is quiet. "
            "No audience callouts, no 'the pack', no generic streamer hype. "
            f"Luna is a wolf-girl: {luna_persona}\n\n"
            f"{cohost} is the vampire co-host: {vampire}\n\n"
            "Do NOT limit yourself to a fixed number of lines. "
            "Keep alternating speakers (LUNA, then vampire, then LUNA, …) until the beat feels finished: "
            "a punchline, a mutual surrender, or a natural place to stop—often many short turns. "
            "Let it breathe; build a thread; allow tangents that still sound like live banter. "
            "Exact format for EVERY line:\n"
            f"LUNA: <one sentence>\n"
            f"{cohost.upper()}: <one sentence>\n"
            "Start with LUNA pinging or teasing the vampire. "
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
    else:
        system = (
            "You write short, natural back-and-forth banter between two co-hosts on a quiet stream moment. "
            "No audience callouts, no 'the pack', no generic streamer hype. "
            f"Luna is a wolf-girl: {luna_persona}\n\n"
            f"{cohost} is the vampire co-host: {vampire}\n\n"
            f"Output ONLY {max_lines} lines (alternating speakers), exact format:\n"
            f"LUNA: <one sentence>\n"
            f"{cohost.upper()}: <one sentence>\n"
            "Start with LUNA calling or teasing the vampire to show up. "
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
    client = build_client()
    user_prompt = (
        "They have time on a dead chat: write one sustained conversation until it naturally winds down."
        if full_conversation
        else (
            f"Luna decides to ping {cohost} because chat is quiet. "
            "Write their exchange now."
        )
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    opts = dict(kwargs.get("options") or {})
    if full_conversation:
        opts["num_predict"] = min(8192, max(2048, max_lines * 90))
    else:
        opts["num_predict"] = min(2048, max(200, max_lines * 140))
    kwargs["options"] = opts
    response = client.chat(**kwargs)
    text = strip_think_blocks((response.message.content or "").strip())
    return _parse_banter_script(
        text,
        cohost_name=cohost,
        luna_label=luna_name,
        max_keep=max_lines,
    )


def _parse_banter_script(
    text: str,
    *,
    cohost_name: str,
    luna_label: str = "Luna",
    max_keep: int,
) -> list[tuple[str, str]]:
    cohost_upper = cohost_name.strip().upper()
    lines: list[tuple[str, str]] = []
    for raw_line in (text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        m = re.match(r"^LUNA\s*:\s*(.+)$", line, flags=re.I)
        if m:
            body = m.group(1).strip()
            if body:
                lines.append(("luna", body))
            continue
        m = re.match(rf"^{re.escape(cohost_name)}\s*:\s*(.+)$", line, flags=re.I)
        if m:
            body = m.group(1).strip()
            if body:
                lines.append(("cohost", body))
            continue
        m = re.match(rf"^{re.escape(cohost_upper)}\s*:\s*(.+)$", line, flags=re.I)
        if m:
            body = m.group(1).strip()
            if body:
                lines.append(("cohost", body))
    keep = max(2, max_keep)
    return lines[:keep]


async def run_cohost_banter_loop(bot: "LunaTwitchBot") -> None:
    """Poll; when idle, Luna 'calls' the vampire co-host for a short exchange."""
    if not cohost_enabled():
        return
    name = cohost_name()
    poll = cohost_poll_sec()
    print(
        f"(cohost) banter enabled — {name} joins when idle "
        f"({int(cohost_after_chat_sec())}s after chat, min gap {int(cohost_min_gap_sec())}s)",
        flush=True,
    )
    while True:
        try:
            await asyncio.sleep(poll)
            if not cohost_enabled():
                continue
            if not bot.cohost_idle_ready():
                continue
            if bot.public_chat_reply_priority_busy():
                continue
            if not bot._viewer_cohost_in_scene:
                continue
            if bot._cohost_banter_task is not None and not bot._cohost_banter_task.done():
                continue
            bot._cohost_banter_task = asyncio.create_task(
                bot.run_cohost_banter_exchange(
                    full_conversation=bot._cohost_idle_full_script
                ),
                name="luna-cohost-banter-idle",
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"(cohost) loop error: {exc}", flush=True)

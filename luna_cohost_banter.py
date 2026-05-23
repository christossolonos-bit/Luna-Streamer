"""Idle Luna ↔ co-host banter (duo or full cast trio when both are on stage)."""

from __future__ import annotations

import asyncio
import os
import re
from typing import TYPE_CHECKING

from luna_persona import build_luna_system_prompt
from ollama_client import build_client, chat_request_kwargs, strip_think_blocks
from vampire_cohost import (
    cohost_after_chat_sec,
    cohost_enabled,
    cohost_min_gap_sec,
    cohost_poll_sec,
)

if TYPE_CHECKING:
    from twitch_bot import LunaTwitchBot

# Script lines: (speaker_id, text) with speaker_id in luna | viktor | himari
BanterLine = tuple[str, str]

_FORMAT_RETRY_BLOCK = (
    "FORMAT FIX: Your last reply was not usable. Output ONLY alternating dialogue lines, "
    "one per line, exact pattern:\n"
    "LUNA: <one sentence>\n"
    "VIKTOR: <one sentence>\n"
    "(or HIMARI: when three are on stage). No markdown, no bullets, no stage directions, "
    "no narration outside those labels."
)


def _normalize_banter_raw_line(line: str) -> str:
    s = (line or "").strip()
    s = re.sub(r"^[-*•]\s+", "", s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"\1", s)
    return s.strip()


def _name_keys(*names: str) -> frozenset[str]:
    out: set[str] = set()
    for n in names:
        n = (n or "").strip().lower()
        if n:
            out.add(n)
            out.add(n.upper())
    return frozenset(out)


def _parse_labeled_banter_line(
    line: str,
    *,
    luna_keys: frozenset[str],
    viktor_keys: frozenset[str],
    himari_keys: frozenset[str],
) -> BanterLine | None:
    line = _normalize_banter_raw_line(line)
    m = re.match(r"^([A-Za-z][A-Za-z0-9 _'-]{0,40})\s*:\s*(.+)$", line)
    if not m:
        return None
    label = m.group(1).strip().lower()
    body = m.group(2).strip()
    if not body or body.startswith("<"):
        return None
    if label in luna_keys or label == "luna":
        return ("luna", body)
    if label in viktor_keys:
        return ("viktor", body)
    if label in himari_keys:
        return _finalize_himari_banter_line(body)
    return None


def _finalize_himari_banter_line(body: str) -> BanterLine | None:
    from himari_cohost import himari_banter_line_broken, sanitize_himari_speech_text

    cleaned = sanitize_himari_speech_text(body)
    if not cleaned or himari_banter_line_broken(cleaned):
        return None
    return ("himari", cleaned)


def _generate_banter_script_sync(
    *,
    model: str,
    luna_name: str,
    cohost: str,
    partner_id: str = "viktor",
    max_lines: int,
    full_conversation: bool = False,
    presence_block: str = "",
    consciousness_block: str = "",
    novelty_block: str = "",
) -> list[BanterLine]:
    """Return duo lines: luna + one partner (viktor or himari)."""
    from luna_cast import build_partner_persona_block

    luna_persona = build_luna_system_prompt()
    partner_persona = build_partner_persona_block(partner_id, for_banter=True)
    if partner_id == "himari":
        role_desc = "shy shrine maiden co-host"
        summon_hint = (
            "Start with LUNA gently drawing Himari out or teasing her awkwardness. "
            "Himari must answer in clear full sentences for TTS — no letter-by-letter stutters."
        )
    else:
        role_desc = "vampire co-host"
        summon_hint = "Start with LUNA pinging or teasing the vampire."
    extra_parts = [
        presence_block.strip(),
        consciousness_block.strip(),
        novelty_block.strip(),
    ]
    extra = "\n\n".join(p for p in extra_parts if p)
    extra = f"\n\n{extra}" if extra else ""
    chat_debrief = "Recent YouTube Live chat" in (presence_block or "")
    if chat_debrief:
        debrief_hint = (
            "The streamer's YouTube Live chatters are in the context below — "
            "your job is to talk **about them**, not to the chat.\n\n"
        )
    else:
        debrief_hint = ""
    if full_conversation:
        system = (
            debrief_hint
            + "You write a full, natural back-and-forth conversation between two co-hosts while the stream is quiet. "
            "This is a **continuation** of mood and callbacks — not a rerun of old lines or a canned skit. "
            "No audience callouts, no 'the pack', no generic streamer hype. "
            f"Luna is a wolf-girl: {luna_persona}\n\n"
            f"{cohost} is the {role_desc}: {partner_persona}\n\n"
            "Do NOT limit yourself to a fixed number of lines. "
            "Keep alternating speakers (LUNA, then co-host, then LUNA, …) until the beat feels finished: "
            "a punchline, a mutual surrender, or a natural place to stop—often many short turns. "
            "Let it breathe; build a thread; allow tangents that still sound like live banter. "
            "Exact format for EVERY line:\n"
            f"LUNA: <one sentence>\n"
            f"{cohost.upper()}: <one sentence>\n"
            f"{summon_hint} "
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
    else:
        system = (
            debrief_hint
            + "You write short, natural back-and-forth banter between two co-hosts on a quiet stream moment. "
            "Continue their thread with **new** lines — callbacks OK, no recycled punchlines. "
            "No audience callouts, no 'the pack', no generic streamer hype. "
            f"Luna is a wolf-girl: {luna_persona}\n\n"
            f"{cohost} is the {role_desc}: {partner_persona}\n\n"
            f"Output ONLY {max_lines} lines (alternating speakers), exact format:\n"
            f"LUNA: <one sentence>\n"
            f"{cohost.upper()}: <one sentence>\n"
            f"{summon_hint} "
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
    client = build_client()
    if chat_debrief:
        user_prompt = (
            f"YouTube Live chat was active and is quiet now. Luna and {cohost} debrief on mic: "
            "specific viewers, what they said, running jokes, mild disagreement — stay in character. "
            "Do not invent viewers not in the log."
        )
        if full_conversation:
            user_prompt += " Let the conversation run until it naturally winds down."
        else:
            user_prompt += f" About {max_lines} alternating lines."
    elif full_conversation:
        user_prompt = (
            "They have time on a dead chat: continue their on-mic thread in a sustained conversation "
            "until it naturally winds down."
        )
    else:
        user_prompt = (
            f"Chat is quiet — Luna and {cohost} pick up where their last on-mic thread left off. "
            "Write the next few turns (do not restart with a unrelated topic)."
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
    return _parse_duo_banter_script(
        text,
        cohost_name=cohost,
        partner_id=partner_id,
        luna_label=luna_name,
        max_keep=max_lines,
    )


def _generate_trio_banter_script_sync(
    *,
    model: str,
    luna_name: str,
    viktor_name: str,
    himari_name: str,
    max_lines: int,
    full_conversation: bool = False,
    presence_block: str = "",
    consciousness_block: str = "",
    novelty_block: str = "",
) -> list[BanterLine]:
    """Return cast lines: luna, viktor, and himari on mic together."""
    from luna_cast import build_partner_persona_block

    luna_persona = build_luna_system_prompt()
    viktor_persona = build_partner_persona_block("viktor")
    himari_persona = build_partner_persona_block("himari", for_banter=True)
    extra_parts = [
        presence_block.strip(),
        consciousness_block.strip(),
        novelty_block.strip(),
    ]
    extra = "\n\n".join(p for p in extra_parts if p)
    extra = f"\n\n{extra}" if extra else ""
    chat_debrief = "Recent YouTube Live chat" in (presence_block or "")
    debrief_hint = (
        "The streamer's live chatters are in the context below — talk **about them** on mic, not to chat.\n\n"
        if chat_debrief
        else ""
    )
    labels = (
        f"LUNA: <one sentence>\n"
        f"{viktor_name.upper()}: <one sentence>\n"
        f"{himari_name.upper()}: <one sentence>\n"
    )
    if full_conversation:
        system = (
            debrief_hint
            + "You write a full, natural three-way couch conversation while the stream is quiet. "
            "Luna (wolf-girl), Viktor (vampire co-host), and Himari (shy shrine maiden) are **all on stage**. "
            "Continue their **shared** thread with **fresh wording** — teasing across the triangle is fine; "
            "never replay lines from prior banter. No audience callouts, no 'the pack', no generic streamer hype.\n\n"
            f"Luna: {luna_persona}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            "Rotate naturally among all three — anyone may answer anyone; "
            "Viktor and Himari may banter with each other while Luna moderates or stirs. "
            "Do NOT limit line count; stop when the beat lands. "
            f"Exact format for EVERY line:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            "Chat is quiet — the three pick up their on-mic thread until it winds down naturally."
        )
        if chat_debrief:
            user_prompt = (
                "Live chat was active and is quiet. The three debrief on mic about specific viewers "
                "and running jokes — stay in character; do not invent names not in the log. "
                "Let the conversation run until it naturally winds down."
            )
    else:
        system = (
            debrief_hint
            + "You write short three-way banter on a quiet stream: Luna, Viktor, and Himari on stage together. "
            "Continue their shared thread with new beats; all three must speak. "
            "No audience callouts, no 'the pack', no generic streamer hype.\n\n"
            f"Luna: {luna_persona}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            f"Output ONLY {max_lines} lines, rotating speakers naturally. Exact format:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            f"Chat is quiet — Luna, {viktor_name}, and {himari_name} continue their couch thread. "
            f"About {max_lines} lines; do not restart with an unrelated topic."
        )
    client = build_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user_prompt},
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    opts = dict(kwargs.get("options") or {})
    if full_conversation:
        opts["num_predict"] = min(8192, max(3072, max_lines * 100))
    else:
        opts["num_predict"] = min(3072, max(280, max_lines * 120))
    kwargs["options"] = opts
    response = client.chat(**kwargs)
    text = strip_think_blocks((response.message.content or "").strip())
    return _parse_trio_banter_script(
        text,
        viktor_name=viktor_name,
        himari_name=himari_name,
        luna_label=luna_name,
        max_keep=max_lines,
    )


def _parse_duo_banter_script(
    text: str,
    *,
    cohost_name: str,
    partner_id: str,
    luna_label: str = "Luna",
    max_keep: int,
) -> list[BanterLine]:
    from vampire_cohost import cohost_name_aliases

    pid = partner_id.strip().lower()
    luna_keys = _name_keys(luna_label, "luna")
    partner_keys = _name_keys(cohost_name, *cohost_name_aliases())
    lines: list[BanterLine] = []
    for raw_line in (text or "").splitlines():
        parsed = _parse_labeled_banter_line(
            raw_line,
            luna_keys=luna_keys,
            viktor_keys=partner_keys if pid == "viktor" else frozenset(),
            himari_keys=partner_keys if pid == "himari" else frozenset(),
        )
        if parsed:
            lines.append(parsed)
    keep = max(2, max_keep)
    return lines[:keep]


def generate_banter_script_with_novelty(
    *,
    model: str,
    luna_name: str,
    trio: bool,
    ledger: "BanterNoveltyLedger",
    strict_novelty: bool,
    max_lines: int,
    full_conversation: bool,
    presence_block: str,
    consciousness_block: str,
    cohost: str = "",
    partner_id: str = "viktor",
    viktor_name: str = "Viktor",
    himari_name: str = "Himari",
    min_lines: int = 2,
) -> list[BanterLine]:
    """Generate banter; retry if format or novelty checks fail."""
    novelty = ledger.block_for_prompt(strict=strict_novelty)
    max_retries = max(0, int(os.environ.get("LUNA_BANTER_NOVELTY_RETRIES", "1") or "1"))
    min_lines = max(2, min_lines)
    script: list[BanterLine] = []

    def _generate(block: str) -> list[BanterLine]:
        if trio:
            return _generate_trio_banter_script_sync(
                model=model,
                luna_name=luna_name,
                viktor_name=viktor_name,
                himari_name=himari_name,
                max_lines=max_lines,
                full_conversation=full_conversation,
                presence_block=presence_block,
                consciousness_block=consciousness_block,
                novelty_block=block,
            )
        return _generate_banter_script_sync(
            model=model,
            luna_name=luna_name,
            cohost=cohost,
            partner_id=partner_id,
            max_lines=max_lines,
            full_conversation=full_conversation,
            presence_block=presence_block,
            consciousness_block=consciousness_block,
            novelty_block=block,
        )

    for attempt in range(max_retries + 1):
        block = novelty
        if attempt > 0:
            block = (
                f"{novelty}\n\n"
                "RETRY: Your previous draft reused banned or near-duplicate lines. "
                "Write completely new wording and a different comedic angle."
            )
        script = _generate(block)
        if ledger.count_overlaps(script) <= 1:
            break

    if len(script) < min_lines:
        fmt = f"{novelty}\n\n{_FORMAT_RETRY_BLOCK}" if novelty else _FORMAT_RETRY_BLOCK
        script = _generate(fmt)
    return script


def _parse_trio_banter_script(
    text: str,
    *,
    viktor_name: str,
    himari_name: str,
    luna_label: str = "Luna",
    max_keep: int,
) -> list[BanterLine]:
    from himari_cohost import himari_name_aliases
    from vampire_cohost import cohost_name_aliases

    luna_keys = _name_keys(luna_label, "luna")
    viktor_keys = _name_keys(viktor_name, *cohost_name_aliases())
    himari_keys = _name_keys(himari_name, *himari_name_aliases())
    lines: list[BanterLine] = []
    for raw_line in (text or "").splitlines():
        parsed = _parse_labeled_banter_line(
            raw_line,
            luna_keys=luna_keys,
            viktor_keys=viktor_keys,
            himari_keys=himari_keys,
        )
        if parsed:
            lines.append(parsed)
    keep = max(3, max_keep)
    return lines[:keep]


async def run_cohost_banter_loop(bot: "LunaTwitchBot") -> None:
    """Poll; when idle, run duo or trio banter depending on who is on stage."""
    if not cohost_enabled():
        return
    poll = cohost_poll_sec()
    print(
        f"(cohost) idle banter — duo or full cast when all on stage "
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

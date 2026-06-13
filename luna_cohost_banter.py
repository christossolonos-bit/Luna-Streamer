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

_BANTER_ENTERTAINMENT_RULES = (
    "ENTERTAINMENT (critical): The stream is **still live** — this is mid-show couch talk, "
    "not a sign-off segment. Keep it fun: teasing, absurd tangents, petty rivalries, "
    "nerd rants, dry one-liners, or unexpectedly sweet beats. "
    "Never steer toward ending the stream, saying goodnight, signing off, thanking viewers "
    "for watching, or wrapping up the night. "
    "Avoid lines like 'good night', 'we should call it', 'time to sleep', 'see you next time', "
    "'thanks for hanging out', or any farewell / end-of-stream energy.\n"
    "CHAT ENGAGEMENT: When the room has been quiet, the **last line** of the script should have "
    "one cast member speak **directly to chat** (fourth wall): a funny question, playful dare, "
    "or self-aware humorous beg for someone to type — in character, never corporate hype."
)


def banter_chat_cta_enabled() -> bool:
    raw = (os.environ.get("LUNA_BANTER_CHAT_CTA") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def banter_chat_cta_quiet_sec() -> float:
    """Min seconds since last chat before appending an extra spoken CTA after banter."""
    raw = (os.environ.get("LUNA_BANTER_CHAT_CTA_QUIET_SEC") or "45").strip() or "45"
    try:
        sec = float(raw)
    except ValueError:
        sec = 45.0
    return max(cohost_after_chat_sec() + 5.0, min(sec, 600.0))


def banter_chat_cta_post_twitch() -> bool:
    raw = (os.environ.get("LUNA_BANTER_CHAT_CTA_TWITCH") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def line_looks_like_chat_cta(text: str) -> bool:
    """True when a banter line already breaks the fourth wall to chat."""
    t = (text or "").lower()
    if not t:
        return False
    markers = (
        "chat",
        "anyone",
        "anybody",
        "somebody",
        "someone",
        "type something",
        "say something",
        "lurking",
        "lurkers",
        "hello chat",
        "hey chat",
        "drop a",
        "tell us",
        "what do you",
        "who's watching",
        "whos watching",
        "is anyone",
        "prove you're",
        "prove youre",
    )
    return any(m in t for m in markers)


def choose_banter_cta_speaker(
    scene: "CastScene",
    played: list[BanterLine],
) -> str:
    """Who should deliver the post-banter chat CTA (luna | viktor | himari)."""
    from luna_cast import CastScene

    if not isinstance(scene, CastScene):
        scene = CastScene()
    if scene.luna_in_scene:
        return "luna"
    if played:
        last = (played[-1][0] or "").strip().lower()
        if last in ("viktor", "himari"):
            return last
    if scene.himari_in_scene and not scene.viktor_in_scene:
        return "himari"
    return "viktor"


def generate_banter_chat_cta_sync(
    *,
    model: str,
    luna_name: str,
    speaker_id: str,
    quiet_sec: float,
    recent_banter: list[BanterLine],
    viktor_name: str = "Viktor",
    himari_name: str = "Himari",
) -> str | None:
    """One short humorous line asking quiet chat to engage."""
    from luna_cast import build_partner_persona_block, partner_display_name

    spk = (speaker_id or "luna").strip().lower()
    if spk == "luna":
        speaker_label = luna_name or "Luna"
        persona = build_luna_system_prompt()
    elif spk == "himari":
        speaker_label = himari_name or partner_display_name("himari")
        persona = build_partner_persona_block("himari", for_banter=True)
    else:
        spk = "viktor"
        speaker_label = viktor_name or partner_display_name("viktor")
        persona = build_partner_persona_block("viktor", for_banter=True)

    banter_snip = "\n".join(
        f"{s}: {t[:100]}" for s, t in (recent_banter or [])[-4:]
    ).strip() or "(cast was just bantering on mic)"

    system = (
        f"You are {speaker_label} on a **live stream**. Chat has been quiet for about "
        f"{int(quiet_sec)} seconds. The cast just finished an on-mic banter beat.\n\n"
        f"{persona}\n\n"
        "Write **one sentence** spoken aloud to **chat** (fourth wall): a funny engagement question, "
        "playful dare, or self-aware beg for someone to type. Tease lurkers gently; bribe them with "
        "absurd stakes if you want. Stay in character.\n"
        "Do NOT say goodnight, sign off, or imply the stream is ending. "
        "No markdown, no speaker label, no quotes — plain dialogue only. Under 200 characters."
    )
    user = (
        f"Recent on-mic context:\n{banter_snip}\n\n"
        "Your one line to chat now:"
    )
    client = build_client()
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    opts = dict(kwargs.get("options") or {})
    opts["num_predict"] = min(128, opts.get("num_predict", 128) or 128)
    kwargs["options"] = opts
    try:
        response = client.chat(**kwargs)
        raw = strip_think_blocks((response.message.content or "").strip())
    except Exception as exc:  # noqa: BLE001
        print(f"(banter) chat CTA LLM failed: {exc}", flush=True)
        return None
    line = re.sub(r"^(?:luna|viktor|himari|[A-Za-z ]{2,24})\s*:\s*", "", raw, flags=re.I).strip()
    line = line.strip("\"' ")
    if not line or len(line) < 8:
        return None
    if spk == "himari":
        from himari_cohost import himari_banter_line_broken, sanitize_himari_speech_text

        line = sanitize_himari_speech_text(line)
        if not line or himari_banter_line_broken(line):
            return None
    return line[:220]


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
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
            f"Luna is a wolf-girl: {luna_persona}\n\n"
            f"{cohost} is the {role_desc}: {partner_persona}\n\n"
            "Do NOT limit yourself to a fixed number of lines. "
            "Keep alternating speakers (LUNA, then co-host, then LUNA, …) until the beat lands: "
            "a punchline, a spicy take, or a cliffhanger that keeps the couch energy alive — "
            "not a goodbye or stream wrap-up. "
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
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
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
            user_prompt += " Keep the thread entertaining until a strong beat lands — the stream stays live."
        else:
            user_prompt += f" About {max_lines} alternating lines — lively, no sign-off energy."
    elif full_conversation:
        user_prompt = (
            "They have time on a dead chat: continue their on-mic thread with entertaining back-and-forth "
            "until a punchline or cliffhanger lands — the broadcast is still on; no goodnights."
        )
    else:
        user_prompt = (
            f"Chat is quiet — Luna and {cohost} pick up where their last on-mic thread left off. "
            "Write the next few turns (stay entertaining; do not restart with an unrelated topic or a goodbye)."
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
            "never replay lines from prior banter. No audience callouts, no 'the pack', no generic streamer hype. "
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
            f"Luna: {luna_persona}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            "Rotate naturally among all three — anyone may answer anyone; "
            "Viktor and Himari may banter with each other while Luna moderates or stirs. "
            "Do NOT limit line count; stop when a punchline or cliffhanger lands — not a goodbye. "
            f"Exact format for EVERY line:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            "Chat is quiet — the three pick up their on-mic thread with entertaining chaos "
            "until a strong beat lands. The stream is still live — no sign-offs."
        )
        if chat_debrief:
            user_prompt = (
                "Live chat was active and is quiet. The three debrief on mic about specific viewers "
                "and running jokes — stay in character; do not invent names not in the log. "
                "Keep it lively; no goodnights or stream-ending talk."
            )
    else:
        system = (
            debrief_hint
            + "You write short three-way banter on a quiet stream: Luna, Viktor, and Himari on stage together. "
            "Continue their shared thread with new beats; all three must speak. "
            "No audience callouts, no 'the pack', no generic streamer hype. "
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
            f"Luna: {luna_persona}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            f"Output ONLY {max_lines} lines, rotating speakers naturally. Exact format:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            f"Chat is quiet — Luna, {viktor_name}, and {himari_name} continue their couch thread. "
            f"About {max_lines} lines; stay entertaining — no unrelated topic resets or goodnights."
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


def _generate_cohost_duo_banter_script_sync(
    *,
    model: str,
    viktor_name: str,
    himari_name: str,
    max_lines: int,
    full_conversation: bool = False,
    presence_block: str = "",
    consciousness_block: str = "",
    novelty_block: str = "",
) -> list[BanterLine]:
    """Viktor + Himari banter while Luna is off stage."""
    from luna_cast import build_partner_persona_block

    viktor_persona = build_partner_persona_block("viktor", for_banter=True)
    himari_persona = build_partner_persona_block("himari", for_banter=True)
    extra_parts = [
        presence_block.strip(),
        consciousness_block.strip(),
        novelty_block.strip(),
    ]
    extra = "\n\n".join(p for p in extra_parts if p)
    extra = f"\n\n{extra}" if extra else ""
    labels = (
        f"{viktor_name.upper()}: <one sentence>\n"
        f"{himari_name.upper()}: <one sentence>\n"
    )
    if full_conversation:
        system = (
            "You write a full natural back-and-forth between two co-hosts while the stream is quiet. "
            f"**Luna is off stage** — only {viktor_name} (vampire) and {himari_name} (shy shrine maiden) "
            "are on mic. They banter directly with each other; do not write Luna's lines or summon her. "
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            "Alternate naturally; Viktor may tease Himari's awkwardness, Himari may nerd out or blush. "
            f"Exact format for EVERY line:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            f"Chat is quiet — {viktor_name} and {himari_name} pick up their thread with entertaining "
            "back-and-forth until a punchline lands. The stream is still on — no sign-offs."
        )
    else:
        system = (
            "You write short banter between two co-hosts on a quiet stream. "
            f"**Luna is off stage** — only {viktor_name} and {himari_name} speak. "
            "No Luna lines. "
            f"{_BANTER_ENTERTAINMENT_RULES}\n\n"
            f"Viktor ({viktor_name}): {viktor_persona}\n\n"
            f"Himari ({himari_name}): {himari_persona}\n\n"
            f"Output ONLY {max_lines} lines, alternating speakers. Exact format:\n{labels}"
            "Keep each line under 220 characters. No stage directions, no markdown."
        ) + extra
        user_prompt = (
            f"Chat is quiet — {viktor_name} and {himari_name} continue their couch thread. "
            f"About {max_lines} lines — lively teasing or nerd chaos, no goodnights."
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
    return _parse_cohost_duo_banter_script(
        text,
        viktor_name=viktor_name,
        himari_name=himari_name,
        max_keep=max_lines,
    )


def _parse_cohost_duo_banter_script(
    text: str,
    *,
    viktor_name: str,
    himari_name: str,
    max_keep: int,
) -> list[BanterLine]:
    from himari_cohost import himari_name_aliases
    from vampire_cohost import cohost_name_aliases

    viktor_keys = _name_keys(viktor_name, *cohost_name_aliases())
    himari_keys = _name_keys(himari_name, *himari_name_aliases())
    lines: list[BanterLine] = []
    for raw_line in (text or "").splitlines():
        parsed = _parse_labeled_banter_line(
            raw_line,
            luna_keys=frozenset(),
            viktor_keys=viktor_keys,
            himari_keys=himari_keys,
        )
        if parsed and parsed[0] in ("viktor", "himari"):
            lines.append(parsed)
    keep = max(2, max_keep)
    return lines[:keep]


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
    cohost_duo: bool = False,
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
        if cohost_duo:
            return _generate_cohost_duo_banter_script_sync(
                model=model,
                viktor_name=viktor_name,
                himari_name=himari_name,
                max_lines=max_lines,
                full_conversation=full_conversation,
                presence_block=presence_block,
                consciousness_block=consciousness_block,
                novelty_block=block,
            )
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

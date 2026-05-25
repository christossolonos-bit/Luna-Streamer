"""Who is on stage (Viktor / Himari) and Luna's idle banter partner choice."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from pathlib import Path

from luna_persona import build_luna_system_prompt
from ollama_client import build_client, chat_request_kwargs, strip_think_blocks


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def _state_path() -> Path:
    raw = (os.environ.get("LUNA_CAST_SCENE_STATE_PATH") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    legacy = (os.environ.get("LUNA_COHOST_SCENE_STATE_PATH") or "").strip()
    if legacy:
        return Path(legacy).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data" / "cast_scene_state.json").resolve()


@dataclass
class CastScene:
    viktor_in_scene: bool = False
    himari_in_scene: bool = False
    last_idle_partner: str = ""

    def any_in_scene(self) -> bool:
        return self.viktor_in_scene or self.himari_in_scene

    def idle_partner_ids(self) -> list[str]:
        from himari_cohost import himari_enabled
        from vampire_cohost import cohost_enabled

        out: list[str] = []
        if cohost_enabled() and self.viktor_in_scene:
            out.append("viktor")
        if himari_enabled() and self.himari_in_scene:
            out.append("himari")
        return out

    def trio_on_stage(self) -> bool:
        """Luna + Viktor + Himari all available for a three-way idle banter."""
        ids = self.idle_partner_ids()
        return "viktor" in ids and "himari" in ids


def load_cast_scene(*, default_viktor: bool = False) -> CastScene:
    path = _state_path()
    scene = CastScene()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                if "viktor_in_scene" in data:
                    scene.viktor_in_scene = bool(data.get("viktor_in_scene"))
                elif "in_scene" in data:
                    scene.viktor_in_scene = bool(data.get("in_scene"))
                scene.himari_in_scene = bool(data.get("himari_in_scene"))
                scene.last_idle_partner = str(data.get("last_idle_partner") or "").strip().lower()
        except (OSError, json.JSONDecodeError, TypeError):
            pass
    elif default_viktor:
        scene.viktor_in_scene = True
    if _env_truthy("LUNA_CAST_BOTH_ON_SCENE"):
        from himari_cohost import himari_enabled

        scene.viktor_in_scene = True
        scene.himari_in_scene = himari_enabled()
    return scene


def save_cast_scene(scene: CastScene) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "viktor_in_scene": bool(scene.viktor_in_scene),
                "himari_in_scene": bool(scene.himari_in_scene),
                "last_idle_partner": scene.last_idle_partner,
                "in_scene": scene.any_in_scene(),
            },
            indent=0,
        )
        + "\n",
        encoding="utf-8",
    )


def load_cohost_in_scene(*, default: bool = False) -> bool:
    """Backward compat: any co-host on stage."""
    return load_cast_scene(default_viktor=default).any_in_scene()


def save_cohost_in_scene(in_scene: bool) -> None:
    scene = load_cast_scene()
    scene.viktor_in_scene = bool(in_scene)
    if not in_scene:
        scene.himari_in_scene = False
    save_cast_scene(scene)


def partner_display_name(partner_id: str) -> str:
    from himari_cohost import himari_name
    from vampire_cohost import cohost_name

    if partner_id == "himari":
        return himari_name()
    return cohost_name()


def partner_vrm_viewer_url(partner_id: str) -> str:
    from himari_cohost import himari_vrm_viewer_url
    from vampire_cohost import cohost_vrm_viewer_url

    if partner_id == "himari":
        return himari_vrm_viewer_url()
    return cohost_vrm_viewer_url()


def partner_edge_voice(partner_id: str) -> str:
    from himari_cohost import himari_edge_voice
    from vampire_cohost import cohost_edge_voice

    if partner_id == "himari":
        return himari_edge_voice()
    return cohost_edge_voice()


def build_partner_persona_block(partner_id: str, *, for_banter: bool = False) -> str:
    from himari_cohost import build_himari_banter_persona_block, build_himari_system_prompt
    from vampire_cohost import build_vampire_system_prompt

    if partner_id == "himari":
        if for_banter:
            return build_himari_banter_persona_block()
        return build_himari_system_prompt()
    return build_vampire_system_prompt()


def partner_cast_line(partner_id: str) -> str:
    """One-line cast bio for prompts (gender + role)."""
    name = partner_display_name(partner_id)
    if partner_id == "himari":
        return (
            f"**{name}** — female shrine maiden co-host (shy, awkward, nerds out on games/anime). "
            "Pronouns: she/her."
        )
    return (
        f"**{name}** — male vampire co-host (dry wit, centuries-old foil to Luna). "
        "Pronouns: he/him."
    )


def format_cast_roster_block(scene: CastScene) -> str:
    """Who the co-hosts are and who is on stage — for Luna's system prompt."""
    from himari_cohost import himari_enabled
    from vampire_cohost import cohost_enabled

    lines = [
        "## Stream cast (know your co-hosts — never mix them up)",
        "- **Luna (you)** — main host, wolf-girl woman.",
    ]
    if cohost_enabled():
        stage = "on stage in the viewer" if scene.viktor_in_scene else "off stage (dismissed)"
        lines.append(f"- {partner_cast_line('viktor')} {stage}.")
    if himari_enabled():
        stage = "on stage in the viewer" if scene.himari_in_scene else "off stage (dismissed)"
        lines.append(f"- {partner_cast_line('himari')} {stage}.")
    if len(lines) <= 2:
        return ""
    lines.append(
        "If chat asks for someone off stage, answer as Luna with correct pronouns; "
        "do not pretend they are on mic or speak as them unless they are on stage."
    )
    return "\n".join(lines)


def format_partner_off_stage_block(partner_id: str) -> str:
    name = partner_display_name(partner_id)
    _, pronouns = ("female shrine maiden", "she/her") if partner_id == "himari" else (
        "vampire co-host",
        "he/him",
    )
    return (
        f"## {name} is off stage (dismissed)\n"
        f"{name} ({pronouns}) is not on screen. Do not write their dialogue or call them to the mic. "
        f"When mentioning {name}, use {pronouns}."
    )


def format_viewer_addressee_note(text: str, scene: CastScene) -> str:
    """When a viewer @'s someone off stage, tell Luna how to answer."""
    from himari_cohost import chat_directed_at_himari, himari_enabled, himari_name
    from vampire_cohost import chat_directed_at_cohost, cohost_enabled, cohost_name

    notes: list[str] = []
    if himari_enabled() and chat_directed_at_himari(text) and not scene.himari_in_scene:
        hn = himari_name()
        notes.append(
            f"The viewer asked about **{hn}** — she is a **female shrine maiden** co-host (she/her). "
            f"**{hn} is off stage** right now. Answer as Luna only: say honestly she is not on screen; "
            "never call her he/him; do not roleplay as her."
        )
    if cohost_enabled() and chat_directed_at_cohost(text) and not scene.viktor_in_scene:
        vn = cohost_name()
        notes.append(
            f"The viewer asked about **{vn}** — he is the **male vampire** co-host (he/him). "
            f"**{vn} is off stage** right now. Answer as Luna only; do not roleplay as him."
        )
    return "\n\n".join(notes)


def _mention_index(text: str, name: str) -> int | None:
    pat = rf"(?:^|(?<=[^a-z0-9_]))@?{re.escape(name)}(?=[^a-z0-9_]|$)"
    m = re.search(pat, (text or "").lower())
    return m.start() if m else None


def public_chat_addressees(text: str, *, trigger_all: bool = False) -> list[str]:
    """Who should answer this Twitch / YouTube / TikTok line (``luna`` | ``viktor`` | ``himari``).

    Multiple names → each answers in mention order. With ``trigger_all`` and no names, only Luna.
    """
    from himari_cohost import chat_directed_at_himari, himari_enabled, himari_name_aliases
    from vampire_cohost import (
        chat_directed_at_cohost,
        chat_directed_at_luna,
        cohost_enabled,
        cohost_name_aliases,
    )

    at_luna = chat_directed_at_luna(text)
    at_viktor = cohost_enabled() and chat_directed_at_cohost(text)
    at_himari = himari_enabled() and chat_directed_at_himari(text)

    def _earliest_alias(names: list[str]) -> int:
        best = 10**9
        for n in names:
            idx = _mention_index(text, n)
            if idx is not None:
                best = min(best, idx)
        return best

    mentioned: list[tuple[int, str]] = []
    if at_luna:
        l_idx = _mention_index(text, "luna")
        if l_idx is not None:
            mentioned.append((l_idx, "luna"))
    if at_viktor:
        vi = _earliest_alias(list(cohost_name_aliases()))
        if vi != 10**9:
            mentioned.append((vi, "viktor"))
    if at_himari:
        hi = _earliest_alias(list(himari_name_aliases()))
        if hi != 10**9:
            mentioned.append((hi, "himari"))

    if mentioned:
        mentioned.sort(key=lambda x: x[0])
        return [partner for _, partner in mentioned]

    if trigger_all:
        return ["luna"]
    return []


def _earliest_named_partner(text: str) -> str | None:
    from himari_cohost import himari_enabled, himari_name_aliases
    from vampire_cohost import cohost_enabled, cohost_name_aliases

    candidates: list[tuple[int, str]] = []
    if cohost_enabled():
        for n in cohost_name_aliases():
            idx = _mention_index(text, n)
            if idx is not None:
                candidates.append((idx, "viktor"))
    if himari_enabled():
        for n in himari_name_aliases():
            idx = _mention_index(text, n)
            if idx is not None:
                candidates.append((idx, "himari"))
    luna_idx = _mention_index(text, "luna")
    if luna_idx is not None:
        candidates.append((luna_idx, "luna"))
    if not candidates:
        return None
    return min(candidates, key=lambda x: x[0])[1]


def resolve_creator_reply_partner(
    text: str,
    scene: CastScene,
    *,
    explicit_target: str | None = None,
) -> str:
    """Who answers creator panel/voice — honors viewer ``reply_to`` and on-stage cast."""
    from himari_cohost import chat_directed_at_himari, himari_enabled
    from vampire_cohost import chat_directed_at_cohost, chat_directed_at_luna, cohost_enabled

    # Names in the message beat the viewer talk-target button (Luna / Himari / Viktor).
    named = _earliest_named_partner(text)
    if named == "himari" and himari_enabled():
        return "himari"
    if named == "viktor" and cohost_enabled():
        return "viktor"
    if named == "luna":
        return "luna"

    target = (explicit_target or "").strip().lower()
    if target == "luna":
        return "luna"
    if target in ("cohost", "viktor"):
        if scene.viktor_in_scene or cohost_enabled():
            return "viktor"
    elif target == "himari":
        if scene.himari_in_scene or himari_enabled():
            return "himari"

    on_stage = scene.idle_partner_ids()
    if (
        not target
        and len(on_stage) == 1
        and not chat_directed_at_luna(text)
    ):
        return on_stage[0]

    fallback = resolve_chat_reply_partner(text, scene)
    if fallback != "luna":
        return fallback
    if chat_directed_at_luna(text):
        return "luna"

    on_stage = scene.idle_partner_ids()
    if len(on_stage) == 1:
        return on_stage[0]
    last = (scene.last_idle_partner or "").strip().lower()
    if last in on_stage:
        return last

    default = (os.environ.get("LUNA_CREATOR_CHAT_DEFAULT") or "").strip().lower()
    if default in ("cohost", "viktor") and "viktor" in on_stage:
        return "viktor"
    if default == "himari" and "himari" in on_stage:
        return "himari"
    return "luna"


def resolve_chat_reply_partner(text: str, scene: CastScene) -> str:
    """Return ``luna``, ``viktor``, or ``himari`` for who should answer."""
    import random

    from himari_cohost import himari_enabled
    from vampire_cohost import (
        chat_directed_at_cohost,
        chat_directed_at_luna,
        cohost_chat_personas_enabled,
        cohost_enabled,
    )

    if not cohost_enabled() and not himari_enabled():
        return "luna"

    winner = _earliest_named_partner(text)
    if winner == "himari":
        return "himari"
    if winner == "viktor":
        return "viktor"
    if winner == "luna":
        return "luna"

    if not cohost_chat_personas_enabled() or not scene.idle_partner_ids():
        return "luna"

    mode = (os.environ.get("LUNA_COHOST_CHAT_SPEAKER") or "random").strip().lower()
    on_stage = scene.idle_partner_ids()
    if mode in ("luna", "luna_only"):
        return "luna"
    if mode in ("cohost", "viktor", "cohost_only", "vampire"):
        return on_stage[0] if on_stage else "luna"
    if mode in ("himari", "himari_only") and "himari" in on_stage:
        return "himari"
    if mode == "alternate":
        # Legacy: alternate Luna vs first on-stage co-host (Viktor if present).
        if "viktor" in on_stage:
            return "viktor"
        return on_stage[0] if on_stage else "luna"
    if mode == "random" and on_stage:
        return random.choice(on_stage)
    return "luna"


def _memory_snippet_for_choice(recent: list[dict[str, str]], *, limit: int = 10) -> str:
    rows: list[str] = []
    for msg in recent[-limit:]:
        role = (msg.get("role") or "").strip()
        body = (msg.get("content") or "").strip().replace("\n", " ")
        if len(body) > 220:
            body = body[:217] + "…"
        if body:
            rows.append(f"[{role}] {body}")
    return "\n".join(rows) if rows else "(no recent chat memory)"


def _heuristic_idle_partner(
    scene: CastScene,
    *,
    memory_text: str,
) -> str:
    from himari_cohost import chat_directed_at_himari, himari_name_aliases
    from vampire_cohost import chat_directed_at_cohost

    ids = scene.idle_partner_ids()
    if len(ids) == 1:
        return ids[0]
    text = (memory_text or "").lower()
    himari_score = 0
    viktor_score = 0
    if chat_directed_at_himari(memory_text):
        himari_score += 4
    if chat_directed_at_cohost(memory_text):
        viktor_score += 4
    for kw in ("shrine", "miko", "awkward", "uwu", "anime", "game", "patch", "nerd", "ramble"):
        if kw in text:
            himari_score += 1
    for kw in ("vampire", "centur", "blood", "viktor", "old", "dry"):
        if kw in text:
            viktor_score += 1
    for alias in himari_name_aliases():
        if alias in text:
            himari_score += 2
    if scene.last_idle_partner == "viktor":
        himari_score += 1
    elif scene.last_idle_partner == "himari":
        viktor_score += 1
    if himari_score > viktor_score and "himari" in ids:
        return "himari"
    if viktor_score > himari_score and "viktor" in ids:
        return "viktor"
    return ids[0] if ids else "viktor"


def choose_idle_banter_partner_sync(
    *,
    model: str,
    luna_name: str,
    scene: CastScene,
    recent_memory: list[dict[str, str]] | None = None,
) -> str | None:
    """Luna picks Viktor or Himari for idle banter. Returns partner id or None."""
    ids = scene.idle_partner_ids()
    if not ids:
        return None
    if len(ids) == 1:
        return ids[0]

    mem = _memory_snippet_for_choice(recent_memory or [])
    v_name = partner_display_name("viktor")
    h_name = partner_display_name("himari")

    if not _env_truthy("LUNA_CAST_IDLE_LLM_CHOOSE", default=True):
        pick = _heuristic_idle_partner(scene, memory_text=mem)
        print(f"(cast) idle partner (heuristic): Luna → {partner_display_name(pick)}", flush=True)
        return pick

    luna_persona = build_luna_system_prompt()
    system = (
        f"You are {luna_name or 'Luna'}, the main host. Chat is quiet; you want to start "
        "an on-mic back-and-forth with ONE co-host.\n\n"
        f"{luna_persona}\n\n"
        f"Co-hosts on stage right now:\n"
        f"- {v_name} (vampire, dry, teasing foil)\n"
        f"- {h_name} (shy shrine maiden, awkward until she nerds out)\n\n"
        "Pick who you actually want to talk to for this beat — mood, recent chat, "
        "who you have unfinished business with. Do not pick someone off stage.\n"
        "Reply with EXACTLY one word: viktor or himari"
    )
    user = (
        f"Last idle banter partner: {scene.last_idle_partner or 'none'}\n\n"
        f"Recent session memory:\n{mem}\n\n"
        "Who do you want to talk to right now?"
    )
    messages = [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]
    try:
        client = build_client()
        kwargs = chat_request_kwargs(model, messages, stream=False)
        opts = dict(kwargs.get("options") or {})
        opts["num_predict"] = min(64, opts.get("num_predict", 64) or 64)
        kwargs["options"] = opts
        response = client.chat(**kwargs)
        raw = strip_think_blocks((response.message.content or "").strip()).lower()
    except Exception as exc:  # noqa: BLE001
        print(f"(cast) idle partner LLM failed ({exc}) — heuristic", flush=True)
        return _heuristic_idle_partner(scene, memory_text=mem)

    if "himari" in raw and "himari" in ids:
        pick = "himari"
    elif "viktor" in raw and "viktor" in ids:
        pick = "viktor"
    else:
        pick = _heuristic_idle_partner(scene, memory_text=mem)
    print(
        f"(cast) Luna chose idle partner → {partner_display_name(pick)} ({pick})",
        flush=True,
    )
    return pick


def save_last_idle_partner(partner_id: str) -> None:
    scene = load_cast_scene()
    scene.last_idle_partner = (partner_id or "").strip().lower()
    save_cast_scene(scene)

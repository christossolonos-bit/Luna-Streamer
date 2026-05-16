"""Evolving Luna ↔ co-host relationship state (injected into both personas)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

from vampire_cohost import cohost_enabled, cohost_name

_DEFAULT_LUNA_RELATIONSHIP = (
    "Viktor and she trade barbs like equals who've done this a hundred times — "
    "she enjoys poking the 'superior' act even when she grudgingly respects him."
)
_DEFAULT_VIKTOR_RELATIONSHIP = (
    "Luna is reckless chaos in a dress; he's not her mentor, not her enemy — "
    "she's the one person who can still surprise him, which annoys him."
)

_TEASE_RE = re.compile(
    r"\b(tease|teasing|stuffy|vampire|old man|centur|chaos|reckless|"
    r"not impressed|superior|viktor|luna|wolf|foil|banter)\b",
    re.I,
)
_WARM_RE = re.compile(
    r"\b(sorry|thank|care|worried|worry|proud|glad|miss you|"
    r"got your back|fine actually|don't die)\b",
    re.I,
)
_FRIC_RE = re.compile(
    r"\b(shut up|hate you|annoying|insufferable|unbearable|"
    r"leave me alone|done with you)\b",
    re.I,
)


def _env_truthy(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def dynamics_enabled() -> bool:
    return cohost_enabled() and _env_truthy("LUNA_COHOST_DYNAMICS", default=True)


def dynamics_file_path() -> Path:
    raw = (os.environ.get("LUNA_COHOST_DYNAMICS_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "cohost_dynamics.json"


class CohostDynamics:
    """Rolling notes on how each host relates to the other and the room right now."""

    def __init__(self) -> None:
        self._path = dynamics_file_path()
        self._persist = _env_truthy("LUNA_COHOST_DYNAMICS_PERSIST", default=True)
        self._max_rel = max(2, int(os.environ.get("LUNA_COHOST_DYNAMICS_MAX_REL", "6") or "6"))
        self._max_mood = max(1, int(os.environ.get("LUNA_COHOST_DYNAMICS_MAX_MOOD", "4") or "4"))
        self._llm_every = max(
            0,
            int(os.environ.get("LUNA_COHOST_DYNAMICS_LLM_EVERY", "10") or "10"),
        )
        self._llm_cooldown_sec = max(
            30.0,
            float(os.environ.get("LUNA_COHOST_DYNAMICS_LLM_COOLDOWN_SEC", "90") or "90"),
        )
        self._exchange_count = 0
        self._last_llm_ts = 0.0
        self._luna_relationship: list[str] = [_DEFAULT_LUNA_RELATIONSHIP]
        self._viktor_relationship: list[str] = [_DEFAULT_VIKTOR_RELATIONSHIP]
        self._luna_mood: list[str] = []
        self._viktor_mood: list[str] = []
        if self._persist:
            self._load()

    def _load(self) -> None:
        try:
            if not self._path.is_file():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            self._luna_relationship = self._read_lines(
                data.get("luna_relationship"), [_DEFAULT_LUNA_RELATIONSHIP]
            )
            self._viktor_relationship = self._read_lines(
                data.get("viktor_relationship"), [_DEFAULT_VIKTOR_RELATIONSHIP]
            )
            self._luna_mood = self._read_lines(data.get("luna_mood"), [])
            self._viktor_mood = self._read_lines(data.get("viktor_mood"), [])
            self._exchange_count = int(data.get("exchange_count") or 0)
        except Exception as exc:
            print(f"(cohost_dynamics) load failed: {exc}", flush=True)

    def _read_lines(self, raw: Any, default: list[str]) -> list[str]:
        if not isinstance(raw, list):
            return list(default)
        out: list[str] = []
        for item in raw:
            s = str(item or "").strip()
            if s and s not in out:
                out.append(s)
        return out or list(default)

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "luna_relationship": self._luna_relationship[-self._max_rel :],
                "viktor_relationship": self._viktor_relationship[-self._max_rel :],
                "luna_mood": self._luna_mood[-self._max_mood :],
                "viktor_mood": self._viktor_mood[-self._max_mood :],
                "exchange_count": self._exchange_count,
                "updated_ts": int(time.time()),
            }
            self._path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"(cohost_dynamics) save failed: {exc}", flush=True)

    def _push(self, bucket: list[str], note: str, cap: int) -> bool:
        note = " ".join(note.split()).strip()
        if not note or len(note) < 8:
            return False
        if len(note) > 220:
            note = note[:219] + "…"
        if note in bucket:
            return False
        bucket.append(note)
        if len(bucket) > cap:
            del bucket[0 : len(bucket) - cap]
        return True

    def _infer_mood_notes(self, user_line: str, assistant_line: str) -> tuple[str | None, str | None]:
        combined = f"{user_line}\n{assistant_line}"
        luna_note: str | None = None
        viktor_note: str | None = None
        if _WARM_RE.search(combined):
            luna_note = "Room tone lately: warmer, less performative."
            viktor_note = "He's been a touch less cutting when people are genuine."
        elif _FRIC_RE.search(combined):
            luna_note = "Tension in the air — she's sharper, quicker to bite."
            viktor_note = "He's more brittle; barbs land harder than he admits."
        elif _TEASE_RE.search(combined):
            luna_note = "Banter-forward — she leans into teasing and chaos."
            viktor_note = "Dry wit mode — unimpressed on the surface, engaged underneath."
        return luna_note, viktor_note

    def observe_exchange(
        self,
        *,
        author: str,
        source: str,
        user_line: str,
        assistant_line: str,
        speaker: str,
    ) -> None:
        """Update relationship notes from one viewer/streamer turn (heuristic, fast)."""
        if not dynamics_enabled():
            return
        user = (user_line or "").strip()
        reply = (assistant_line or "").strip()
        if not user and not reply:
            return

        vn = cohost_name().lower()
        mentions_other = vn in user.lower() or vn in reply.lower() or "luna" in user.lower()

        changed = False
        ln, vn_m = self._infer_mood_notes(user, reply)
        if ln and self._push(self._luna_mood, ln, self._max_mood):
            changed = True
        if vn_m and self._push(self._viktor_mood, vn_m, self._max_mood):
            changed = True

        if speaker == "luna" and _TEASE_RE.search(reply):
            if self._push(
                self._luna_relationship,
                f"After chat with {author}: she kept the Viktor needle sharp — playful, not cruel.",
                self._max_rel,
            ):
                changed = True
        if speaker == "cohost" and _WARM_RE.search(reply):
            if self._push(
                self._viktor_relationship,
                "He let a little warmth slip through without naming it.",
                self._max_rel,
            ):
                changed = True
        if mentions_other and speaker == "luna":
            if self._push(
                self._viktor_relationship,
                f"Luna just framed Viktor in front of {source} — dynamic is live, not scripted.",
                self._max_rel,
            ):
                changed = True

        self._exchange_count += 1
        if changed:
            self._save()

    def observe_banter_script(self, lines: list[tuple[str, str]]) -> None:
        """Fold an idle banter script into relationship memory."""
        if not dynamics_enabled() or not lines:
            return
        changed = False
        for spk, text in lines[-6:]:
            t = (text or "").strip()
            if not t:
                continue
            if spk == "luna":
                if self._push(
                    self._luna_relationship,
                    f"Recent banter beat: {t[:120]}",
                    self._max_rel,
                ):
                    changed = True
            else:
                if self._push(
                    self._viktor_relationship,
                    f"Recent banter beat: {t[:120]}",
                    self._max_rel,
                ):
                    changed = True
        self._exchange_count += 1
        if changed:
            self._save()

    def block_for_luna(self) -> str:
        if not dynamics_enabled():
            return ""
        return self._format_block(
            title="## Dynamic with Viktor (evolves — treat as current truth)",
            relationship=self._luna_relationship,
            mood=self._luna_mood,
            other_name=cohost_name(),
        )

    def block_for_viktor(self) -> str:
        if not dynamics_enabled():
            return ""
        return self._format_block(
            title="## Dynamic with Luna (evolves — treat as current truth)",
            relationship=self._viktor_relationship,
            mood=self._viktor_mood,
            other_name="Luna",
        )

    def block_for_banter(self) -> str:
        if not dynamics_enabled():
            return ""
        luna = self.block_for_luna()
        viktor = self.block_for_viktor()
        if not luna and not viktor:
            return ""
        return (
            "Their relationship is NOT static — honor these evolving notes in the script:\n"
            f"{luna}\n\n{viktor}"
        )

    def _format_block(
        self,
        *,
        title: str,
        relationship: list[str],
        mood: list[str],
        other_name: str,
    ) -> str:
        parts: list[str] = [title]
        parts.append(
            f"Base persona stays the same; these bullets are how things feel **right now** "
            f"with {other_name} and the room. Adapt tone accordingly."
        )
        for line in relationship[-self._max_rel :]:
            parts.append(f"- {line}")
        if mood:
            parts.append("Tone lately:")
            for line in mood[-self._max_mood :]:
                parts.append(f"- {line}")
        return "\n".join(parts)

    def needs_llm_refresh(self) -> bool:
        if not dynamics_enabled() or self._llm_every <= 0:
            return False
        if self._exchange_count > 0 and self._exchange_count % self._llm_every != 0:
            return False
        return (time.monotonic() - self._last_llm_ts) >= self._llm_cooldown_sec

    def apply_llm_refresh(self, payload: dict[str, Any]) -> None:
        """Merge model-produced relationship summaries (lists of short strings)."""
        changed = False
        for key, target, default in (
            ("luna_relationship", self._luna_relationship, _DEFAULT_LUNA_RELATIONSHIP),
            ("viktor_relationship", self._viktor_relationship, _DEFAULT_VIKTOR_RELATIONSHIP),
            ("luna_mood", self._luna_mood, []),
            ("viktor_mood", self._viktor_mood, []),
        ):
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            fresh = self._read_lines(raw, default if "relationship" in key else [])
            if fresh and fresh != target:
                if "relationship" in key:
                    if key == "luna_relationship":
                        self._luna_relationship = fresh[-self._max_rel :]
                    else:
                        self._viktor_relationship = fresh[-self._max_rel :]
                elif key == "luna_mood":
                    self._luna_mood = fresh[-self._max_mood :]
                else:
                    self._viktor_mood = fresh[-self._max_mood :]
                changed = True
        if changed:
            self._last_llm_ts = time.monotonic()
            self._save()

    def build_llm_refresh_messages(self, recent_turns: list[dict[str, str]]) -> list[dict[str, str]]:
        vn = cohost_name()
        transcript = []
        for msg in recent_turns[-12:]:
            role = msg.get("role", "")
            content = (msg.get("content") or "").strip()
            if content:
                transcript.append(f"{role}: {content[:400]}")
        body = "\n".join(transcript) or "(no recent turns)"
        system = (
            "You maintain evolving relationship notes for two co-hosts on stream: "
            f"Luna (wolf-girl, mid-20s energy) and {vn} (centuries-old vampire, mid-20s presentation). "
            "They are NOT mentor/child; their dynamic shifts with chat and banter. "
            "Output ONLY valid JSON with keys: "
            "luna_relationship (array of 3-4 short strings), viktor_relationship, "
            "luna_mood (1-2 strings), viktor_mood (1-2 strings). "
            "No markdown, no extra keys."
        )
        user = (
            f"Current Luna→{vn} notes: {self._luna_relationship}\n"
            f"Current {vn}→Luna notes: {self._viktor_relationship}\n"
            f"Recent conversation:\n{body}\n\n"
            "Update notes to reflect how they relate NOW after this chat. "
            "Keep mid-20s peer energy; allow warmth or friction to shift."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

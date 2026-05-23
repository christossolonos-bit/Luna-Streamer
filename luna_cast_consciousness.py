"""Rolling on-mic threads + stream-of-consciousness notes between Luna and cast partners."""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from vampire_cohost import cohost_enabled, cohost_name


def _env_truthy(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def consciousness_enabled() -> bool:
    return cohost_enabled() and _env_truthy("LUNA_CAST_CONSCIOUSNESS", default=True)


def consciousness_file_path() -> Path:
    raw = (os.environ.get("LUNA_CAST_CONSCIOUSNESS_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path(__file__).resolve().parent / "data" / "cast_consciousness.json"


def _norm_partner(partner_id: str) -> str | None:
    p = (partner_id or "").strip().lower()
    if p in ("viktor", "himari"):
        return p
    return None


class CastConsciousness:
    """Per-partner mic thread + first-person 'head' notes for sustained cast conversation."""

    def __init__(self) -> None:
        self._path = consciousness_file_path()
        self._persist = _env_truthy("LUNA_CAST_CONSCIOUSNESS_PERSIST", default=True)
        self._max_turns = max(
            4, int(os.environ.get("LUNA_CAST_CONSCIOUSNESS_MAX_TURNS", "24") or "24")
        )
        self._max_mind = max(
            2, int(os.environ.get("LUNA_CAST_CONSCIOUSNESS_MAX_MIND", "6") or "6")
        )
        self._inject_turns = max(
            4, int(os.environ.get("LUNA_CAST_CONSCIOUSNESS_INJECT_TURNS", "12") or "12")
        )
        self._llm_every = max(
            0,
            int(os.environ.get("LUNA_CAST_CONSCIOUSNESS_LLM_EVERY", "6") or "6"),
        )
        self._llm_cooldown_sec = max(
            30.0,
            float(os.environ.get("LUNA_CAST_CONSCIOUSNESS_LLM_COOLDOWN_SEC", "75") or "75"),
        )
        self._threads: dict[str, dict[str, Any]] = {}
        self._observe_counts: dict[str, int] = {}
        self._last_llm_ts: dict[str, float] = {}
        if self._persist:
            self._load()

    def _empty_thread(self) -> dict[str, Any]:
        return {
            "topic": "",
            "turns": [],
            "luna_mind": [],
            "partner_mind": [],
            "updated_ts": 0,
        }

    def _load(self) -> None:
        try:
            if not self._path.is_file():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                return
            raw_threads = data.get("threads")
            if not isinstance(raw_threads, dict):
                return
            for key, raw in raw_threads.items():
                pid = _norm_partner(str(key))
                if not pid or not isinstance(raw, dict):
                    continue
                turns = []
                for t in raw.get("turns") or []:
                    if not isinstance(t, dict):
                        continue
                    spk = str(t.get("speaker") or "").strip().lower()
                    text = str(t.get("text") or "").strip()
                    if spk in ("luna", "partner") and text:
                        turns.append({"speaker": spk, "text": text[:400]})
                self._threads[pid] = {
                    "topic": str(raw.get("topic") or "").strip()[:280],
                    "turns": turns[-self._max_turns :],
                    "luna_mind": self._read_mind(raw.get("luna_mind")),
                    "partner_mind": self._read_mind(raw.get("partner_mind")),
                    "updated_ts": int(raw.get("updated_ts") or 0),
                }
        except Exception as exc:
            print(f"(cast_consciousness) load failed: {exc}", flush=True)

    def _read_mind(self, raw: Any) -> list[str]:
        if not isinstance(raw, list):
            return []
        out: list[str] = []
        for item in raw:
            s = " ".join(str(item or "").split()).strip()
            if not s or s in out:
                continue
            if len(s) > 200:
                s = s[:199] + "…"
            out.append(s)
        return out[-self._max_mind :]

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            threads: dict[str, Any] = {}
            for pid, th in self._threads.items():
                threads[pid] = {
                    "topic": (th.get("topic") or "")[:280],
                    "turns": (th.get("turns") or [])[-self._max_turns :],
                    "luna_mind": (th.get("luna_mind") or [])[-self._max_mind :],
                    "partner_mind": (th.get("partner_mind") or [])[-self._max_mind :],
                    "updated_ts": int(th.get("updated_ts") or time.time()),
                }
            self._path.write_text(
                json.dumps({"threads": threads, "saved_ts": int(time.time())}, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"(cast_consciousness) save failed: {exc}", flush=True)

    def _thread(self, partner_id: str) -> dict[str, Any]:
        pid = _norm_partner(partner_id)
        if not pid:
            return self._empty_thread()
        if pid not in self._threads:
            self._threads[pid] = self._empty_thread()
        return self._threads[pid]

    def _push_turn(self, partner_id: str, *, speaker: str, text: str) -> None:
        if not consciousness_enabled():
            return
        pid = _norm_partner(partner_id)
        if not pid:
            return
        t = " ".join((text or "").split()).strip()
        if not t:
            return
        th = self._thread(pid)
        spk = "luna" if (speaker or "").strip().lower() == "luna" else "partner"
        turns: list[dict[str, str]] = list(th.get("turns") or [])
        turns.append({"speaker": spk, "text": t[:400]})
        th["turns"] = turns[-self._max_turns :]
        th["updated_ts"] = int(time.time())
        self._heuristic_mind(pid, spk, t)
        self._observe_counts[pid] = self._observe_counts.get(pid, 0) + 1
        self._save()

    def _heuristic_mind(self, partner_id: str, speaker: str, text: str) -> None:
        th = self._thread(partner_id)
        bucket = "luna_mind" if speaker == "luna" else "partner_mind"
        minds: list[str] = list(th.get(bucket) or [])
        snippet = text[:140] + ("…" if len(text) > 140 else "")
        note = f"Still on: {snippet}"
        if note not in minds:
            minds.append(note)
        th[bucket] = minds[-self._max_mind :]
        if not (th.get("topic") or "").strip():
            th["topic"] = snippet[:120]

    def observe_turn(
        self,
        partner_id: str,
        *,
        speaker: str,
        text: str,
        source: str = "",
    ) -> None:
        _ = source
        self._push_turn(partner_id, speaker=speaker, text=text)

    def observe_banter_script(
        self,
        partner_id: str,
        lines: list[tuple[str, str]],
    ) -> None:
        if not consciousness_enabled() or not lines:
            return
        for spk, text in lines:
            self._push_turn(
                partner_id,
                speaker="luna" if spk == "luna" else "partner",
                text=text,
            )

    def observe_exchange(
        self,
        partner_id: str,
        *,
        user_line: str,
        assistant_line: str,
        speaker: str,
    ) -> None:
        """Fold a viewer/creator chat turn that involved this cast pair."""
        if not consciousness_enabled():
            return
        user = (user_line or "").strip()
        reply = (assistant_line or "").strip()
        if speaker == "luna":
            if user:
                self._push_turn(partner_id, speaker="partner", text=user)
            if reply:
                self._push_turn(partner_id, speaker="luna", text=reply)
        else:
            if user:
                self._push_turn(partner_id, speaker="luna", text=user)
            if reply:
                self._push_turn(partner_id, speaker="partner", text=reply)

    def _partner_display(self, partner_id: str) -> str:
        from luna_cast import partner_display_name

        return partner_display_name(partner_id)

    def _format_transcript(self, partner_id: str, *, limit: int) -> str:
        th = self._thread(partner_id)
        turns: list[dict[str, str]] = list(th.get("turns") or [])
        if not turns:
            return ""
        name = self._partner_display(partner_id)
        lines: list[str] = []
        for t in turns[-limit:]:
            spk = t.get("speaker", "")
            body = (t.get("text") or "").strip()
            if not body:
                continue
            label = "Luna" if spk == "luna" else name
            lines.append(f"{label}: {body}")
        return "\n".join(lines)

    def block_for_trio_banter(
        self,
        *,
        viktor_name: str,
        himari_name: str,
    ) -> str:
        if not consciousness_enabled():
            return ""
        blocks: list[str] = []
        for pid, label in (("viktor", viktor_name), ("himari", himari_name)):
            b = self.block_for_banter(pid, cohost_name=label)
            if b:
                blocks.append(b)
        if not blocks:
            return ""
        return (
            "## Cast couch — three on mic (continue, do not replay)\n"
            "Luna, Viktor, and Himari were talking together. "
            "Pick up emotional through-line and callbacks, but **new wording and beats only** — "
            "never recycle lines from Recent mic or «already used» banter.\n\n"
            + "\n\n".join(blocks)
        )

    def observe_trio_banter_script(
        self,
        lines: list[tuple[str, str]],
    ) -> None:
        if not consciousness_enabled() or not lines:
            return
        for spk, text in lines:
            pid = _norm_partner(spk)
            if not pid:
                continue
            self._push_turn(
                pid,
                speaker="luna" if spk == "luna" else "partner",
                text=text,
            )

    def block_for_banter(self, partner_id: str, *, cohost_name: str) -> str:
        if not consciousness_enabled():
            return ""
        pid = _norm_partner(partner_id)
        if not pid:
            return ""
        th = self._thread(pid)
        transcript = self._format_transcript(pid, limit=self._inject_turns)
        if not transcript and not (th.get("topic") or "").strip():
            return ""
        parts = [
            "## Ongoing on-mic thread (advance — do NOT replay old lines)",
            f"You and **{cohost_name}** have been talking. Continue the through-line with **fresh** lines only — "
            "no verbatim repeats from Recent mic.",
        ]
        topic = (th.get("topic") or "").strip()
        if topic:
            parts.append(f"Thread topic / beat: {topic}")
        for line in (th.get("luna_mind") or [])[-3:]:
            parts.append(f"Luna (head): {line}")
        for line in (th.get("partner_mind") or [])[-3:]:
            parts.append(f"{cohost_name} (head): {line}")
        if transcript:
            parts.append("Recent mic:\n" + transcript)
        parts.append(
            "Write the **next** stretch — new jokes and angles, not a rerun of the transcript above."
        )
        return "\n".join(parts)

    def block_for_partner_chat(self, partner_id: str, *, as_cohost: bool) -> str:
        if not consciousness_enabled():
            return ""
        pid = _norm_partner(partner_id)
        if not pid:
            return ""
        th = self._thread(pid)
        transcript = self._format_transcript(pid, limit=min(10, self._inject_turns))
        if not transcript and not (th.get("topic") or "").strip():
            return ""
        name = self._partner_display(pid)
        who = name if as_cohost else "Luna"
        parts = [
            f"## Stream of consciousness — {who}",
            "Honor the ongoing cast thread; reference prior on-mic beats when natural.",
        ]
        topic = (th.get("topic") or "").strip()
        if topic:
            parts.append(f"Current thread: {topic}")
        bucket = "partner_mind" if as_cohost else "luna_mind"
        for line in (th.get(bucket) or [])[-4:]:
            parts.append(f"Inner voice: {line}")
        if transcript:
            parts.append("Recent mic / cast context:\n" + transcript)
        return "\n".join(parts)

    def block_for_luna(self, *, on_stage_partners: list[str]) -> str:
        if not consciousness_enabled() or not on_stage_partners:
            return ""
        blocks: list[str] = []
        for pid in on_stage_partners:
            pid_n = _norm_partner(pid)
            if not pid_n:
                continue
            b = self.block_for_partner_chat(pid_n, as_cohost=False)
            if b:
                blocks.append(b)
        if not blocks:
            return ""
        return (
            "## Cast couch — what you were just talking about on mic\n"
            + "\n\n".join(blocks)
            + "\nWeave this into your reply when chat touches the cast or the quiet moment."
        )

    def needs_llm_refresh(self, partner_id: str) -> bool:
        if not consciousness_enabled() or self._llm_every <= 0:
            return False
        pid = _norm_partner(partner_id)
        if not pid:
            return False
        count = self._observe_counts.get(pid, 0)
        if count <= 0 or count % self._llm_every != 0:
            return False
        last = self._last_llm_ts.get(pid, 0.0)
        return (time.monotonic() - last) >= self._llm_cooldown_sec

    def build_llm_refresh_messages(self, partner_id: str) -> list[dict[str, str]]:
        pid = _norm_partner(partner_id) or "viktor"
        name = self._partner_display(pid)
        th = self._thread(pid)
        transcript = self._format_transcript(pid, limit=self._inject_turns) or "(no turns yet)"
        system = (
            "You maintain stream-of-consciousness notes for Luna and her co-host on stream. "
            f"Partner: {name}. Output ONLY valid JSON with keys: "
            "thread_topic (one short string), luna_mind (array of 2-4 first-person fragments), "
            "partner_mind (array of 2-4 first-person fragments). "
            "Fragments are internal voice — unfinished thoughts, grudges, jokes still burning. "
            "No markdown, no extra keys."
        )
        user = (
            f"Current topic: {th.get('topic')}\n"
            f"Luna mind: {th.get('luna_mind')}\n"
            f"{name} mind: {th.get('partner_mind')}\n\n"
            f"Transcript:\n{transcript}\n\n"
            "Update notes so the next banter or chat reply continues this thread naturally."
        )
        return [{"role": "system", "content": system}, {"role": "user", "content": user}]

    def apply_llm_refresh(self, partner_id: str, payload: dict[str, Any]) -> None:
        pid = _norm_partner(partner_id)
        if not pid or not isinstance(payload, dict):
            return
        th = self._thread(pid)
        changed = False
        topic = str(payload.get("thread_topic") or "").strip()
        if topic and topic != th.get("topic"):
            th["topic"] = topic[:280]
            changed = True
        for key, bucket in (("luna_mind", "luna_mind"), ("partner_mind", "partner_mind")):
            raw = payload.get(key)
            if not isinstance(raw, list):
                continue
            fresh = self._read_mind(raw)
            if fresh and fresh != th.get(bucket):
                th[bucket] = fresh
                changed = True
        if changed:
            th["updated_ts"] = int(time.time())
            self._last_llm_ts[pid] = time.monotonic()
            self._save()

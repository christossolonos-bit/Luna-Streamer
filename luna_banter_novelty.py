"""Track recent idle banter lines so cast scripts stay fresh (TikTok / live originality)."""

from __future__ import annotations

import json
import os
import re
import time
from collections import deque
from pathlib import Path
from typing import Any


def _env_truthy(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw not in ("0", "false", "no", "off")


def banter_novelty_enabled() -> bool:
    return _env_truthy("LUNA_BANTER_NOVELTY", default=True)


def banter_novelty_strict_on_tiktok() -> bool:
    return _env_truthy("LUNA_BANTER_STRICT_ON_TIKTOK", default=True)


def _ledger_path() -> Path:
    raw = (os.environ.get("LUNA_BANTER_RECENT_FILE") or "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return (Path(__file__).resolve().parent / "data" / "banter_recent.json").resolve()


def normalize_banter_line(text: str) -> str:
    t = re.sub(r"[^a-z0-9\s]", " ", (text or "").lower())
    return " ".join(t.split())


def lines_too_similar(a: str, b: str) -> bool:
    na = normalize_banter_line(a)
    nb = normalize_banter_line(b)
    if len(na) < 10 or len(nb) < 10:
        return False
    if na == nb:
        return True
    if na in nb or nb in na:
        return True
    wa = set(na.split())
    wb = set(nb.split())
    if len(wa) < 4 or len(wb) < 4:
        return False
    overlap = len(wa & wb) / max(1, min(len(wa), len(wb)))
    return overlap >= 0.82


class BanterNoveltyLedger:
    """Rolling store of recent on-mic banter lines injected as do-not-repeat context."""

    def __init__(self) -> None:
        self._path = _ledger_path()
        self._persist = _env_truthy("LUNA_BANTER_NOVELTY_PERSIST", default=True)
        self._max = max(8, int(os.environ.get("LUNA_BANTER_RECENT_MAX", "48") or "48"))
        self._inject = max(5, int(os.environ.get("LUNA_BANTER_NOVELTY_INJECT", "18") or "18"))
        self._entries: deque[dict[str, Any]] = deque(maxlen=self._max)
        if self._persist:
            self._load()

    def _load(self) -> None:
        try:
            if not self._path.is_file():
                return
            data = json.loads(self._path.read_text(encoding="utf-8"))
            rows = data.get("lines") if isinstance(data, dict) else None
            if not isinstance(rows, list):
                return
            for row in rows[-self._max :]:
                if not isinstance(row, dict):
                    continue
                text = str(row.get("text") or "").strip()
                norm = str(row.get("norm") or "").strip() or normalize_banter_line(text)
                if len(norm) < 8:
                    continue
                self._entries.append(
                    {
                        "text": text[:220],
                        "norm": norm[:400],
                        "ts": int(row.get("ts") or 0),
                    }
                )
        except Exception as exc:
            print(f"(banter_novelty) load failed: {exc}", flush=True)

    def _save(self) -> None:
        if not self._persist:
            return
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "lines": list(self._entries),
                "saved_ts": int(time.time()),
            }
            self._path.write_text(
                json.dumps(payload, ensure_ascii=True, indent=2),
                encoding="utf-8",
            )
        except Exception as exc:
            print(f"(banter_novelty) save failed: {exc}", flush=True)

    def record_script(self, lines: list[tuple[str, str]]) -> None:
        if not banter_novelty_enabled() or not lines:
            return
        now = int(time.time())
        for _spk, raw in lines:
            text = (raw or "").strip()
            norm = normalize_banter_line(text)
            if len(norm) < 8:
                continue
            if any(norm == e.get("norm") for e in self._entries):
                continue
            self._entries.append({"text": text[:220], "norm": norm[:400], "ts": now})
        self._save()

    def count_overlaps(self, script: list[tuple[str, str]]) -> int:
        if not script:
            return 0
        norms = [normalize_banter_line(t) for _s, t in script if normalize_banter_line(t)]
        hits = 0
        for n in norms:
            for prev in self._entries:
                if lines_too_similar(n, str(prev.get("norm") or "")):
                    hits += 1
                    break
        return hits

    def block_for_prompt(self, *, strict: bool = False) -> str:
        if not banter_novelty_enabled():
            return ""
        recent = list(self._entries)[-self._inject :]
        parts = [
            "## Banter originality (mandatory — live / TikTok-safe)",
            "This is **improvised** on-mic talk, not a recycled script.",
            "Do **not** repeat, paraphrase, or echo any line listed under «already used».",
            "Do **not** reuse the same opening hook, punchline, debate, or topic loop.",
            "Advance with a **new** beat: fresh reaction, specific detail, or question — "
            "callbacks are fine only if the **wording** is new.",
        ]
        if strict:
            parts.insert(
                1,
                "**TikTok Live is active:** sound spontaneous and unscripted; "
                "no rehearsed-sounding loops or catchphrase spam.",
            )
        if recent:
            parts.append("«Already used» on-mic lines (forbidden to repeat):")
            for entry in reversed(recent):
                snippet = str(entry.get("text") or entry.get("norm") or "").strip()
                if snippet:
                    parts.append(f"- {snippet[:180]}")
        else:
            parts.append("(No prior banter logged this session — still avoid generic VTuber filler loops.)")
        return "\n".join(parts)


_ledger: BanterNoveltyLedger | None = None


def get_banter_novelty_ledger() -> BanterNoveltyLedger:
    global _ledger
    if _ledger is None:
        _ledger = BanterNoveltyLedger()
    return _ledger


def block_for_chat_novelty(
    recent_assistant_lines: list[str],
    *,
    strict: bool = False,
) -> str:
    """Inject into live chat replies so Luna does not repeat herself on TikTok."""
    if not banter_novelty_enabled():
        return ""
    lines = [(" ".join((t or "").split()).strip()) for t in recent_assistant_lines]
    lines = [t for t in lines if len(t) >= 12][-6:]
    parts = [
        "## Do not repeat yourself (this stream)",
        "Your recent replies below are **forbidden** to reuse (same opener, joke, or wording).",
    ]
    if strict:
        parts.append(
            "TikTok Live: sound spontaneous — paraphrases of these lines still count as repeats."
        )
    if lines:
        for t in lines:
            parts.append(f"- «{t[:160]}»")
    else:
        parts.append("(No prior replies logged — still vary phrasing every message.)")
    return "\n".join(parts)

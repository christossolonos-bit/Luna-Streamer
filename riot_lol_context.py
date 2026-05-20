"""League of Legends context via local Riot Client (LCU) + in-game Live Client Data.

Reads the League Client ``lockfile`` (no Riot API key). When you are in a match,
also polls ``127.0.0.1:2999/liveclientdata`` for live KDA, gold, items, etc.

Optional Windows shortcuts (``.lnk``) can launch the client — set
``LUNA_LOL_LEAGUE_LNK`` / ``LUNA_LOL_RIOT_CLIENT_LNK``.
"""

from __future__ import annotations

import asyncio
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

BroadcastStatus = Callable[[str], Awaitable[None]]


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def lol_context_enabled() -> bool:
    return _env_truthy("LUNA_LOL_CONTEXT", default=False)


def lol_poll_sec() -> float:
    raw = (os.environ.get("LUNA_LOL_POLL_SEC") or "8").strip() or "8"
    try:
        sec = float(raw)
    except ValueError:
        sec = 8.0
    return max(4.0, min(sec, 120.0))


def lol_context_max_chars() -> int:
    raw = (os.environ.get("LUNA_LOL_CONTEXT_MAX_CHARS") or "1400").strip() or "1400"
    try:
        n = int(raw)
    except ValueError:
        n = 1400
    return max(300, min(n, 4000))


@dataclass(frozen=True)
class LcuConnection:
    base_url: str
    password: str


def _league_lockfile_paths() -> list[Path]:
    paths: list[Path] = []
    extra = (os.environ.get("LUNA_LOL_LOCKFILE") or "").strip()
    if extra:
        paths.append(Path(extra).expanduser())
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        paths.append(
            Path(local) / "Riot Games" / "League of Legends" / "lockfile"
        )
    return paths


def read_lcu_connection() -> LcuConnection | None:
    """Parse League Client lockfile → HTTPS base URL + password."""
    for path in _league_lockfile_paths():
        try:
            if not path.is_file():
                continue
            line = path.read_text(encoding="utf-8", errors="replace").strip()
            parts = line.split(":")
            if len(parts) < 5:
                continue
            port = parts[2].strip()
            password = parts[3].strip()
            protocol = parts[4].strip() or "https"
            if not port.isdigit() or not password:
                continue
            return LcuConnection(
                base_url=f"{protocol}://127.0.0.1:{port}",
                password=password,
            )
        except OSError:
            continue
    return None


def _ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return ctx


def lcu_get(conn: LcuConnection, path: str, *, timeout: float = 2.5) -> Any | None:
    if not path.startswith("/"):
        path = "/" + path
    url = f"{conn.base_url}{path}"
    req = urllib.request.Request(url, method="GET")
    token = __import__("base64").b64encode(f"riot:{conn.password}".encode()).decode(
        "ascii"
    )
    req.add_header("Authorization", f"Basic {token}")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return None
            return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def live_client_get(path: str, *, timeout: float = 1.8) -> Any | None:
    if not path.startswith("/"):
        path = "/" + path
    url = f"https://127.0.0.1:2999{path}"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_ssl_context()) as resp:
            raw = resp.read().decode("utf-8", errors="replace")
            if not raw.strip():
                return None
            return json.loads(raw)
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError):
        return None


def _safe_str(val: Any, *, default: str = "") -> str:
    if val is None:
        return default
    return str(val).strip()


def _summoner_line(data: Any) -> str:
    if not isinstance(data, dict):
        return ""
    name = _safe_str(data.get("displayName") or data.get("gameName"))
    tag = _safe_str(data.get("tagLine"))
    level = data.get("summonerLevel")
    if name and tag:
        who = f"{name}#{tag}"
    else:
        who = name or "Summoner"
    if level is not None:
        return f"{who} (level {level})"
    return who


def _format_items(item_ids: Any) -> str:
    if not isinstance(item_ids, list):
        return ""
    names: list[str] = []
    for it in item_ids:
        if isinstance(it, dict):
            names.append(_safe_str(it.get("displayName") or it.get("itemID")) or "?")
        elif it:
            names.append(str(it))
    return ", ".join(names[:6]) if names else ""


def _live_game_section() -> list[str]:
    data = live_client_get("/liveclientdata/allgamedata")
    if not isinstance(data, dict):
        return []
    lines: list[str] = ["**In match (live client):**"]
    game = data.get("gameData")
    if isinstance(game, dict):
        mode = _safe_str(game.get("gameMode"))
        t = game.get("gameTime")
        if mode:
            lines.append(f"- Mode: {mode}")
        if t is not None:
            try:
                sec = int(float(t))
                lines.append(f"- Game time: {sec // 60}:{sec % 60:02d}")
            except (TypeError, ValueError):
                pass
    active = data.get("activePlayer")
    if isinstance(active, dict):
        champ = _safe_str(
            (active.get("championStats") or {}).get("championName")
            if isinstance(active.get("championStats"), dict)
            else active.get("championName")
        )
        scores = active.get("scores") if isinstance(active.get("scores"), dict) else {}
        k = scores.get("kills", 0)
        d = scores.get("deaths", 0)
        a = scores.get("assists", 0)
        cs = scores.get("creepScore", scores.get("cs", 0))
        gold = active.get("currentGold")
        parts = [f"- You ({champ or 'champion'}): {k}/{d}/{a}"]
        if cs is not None:
            parts.append(f"CS {cs}")
        if gold is not None:
            parts.append(f"gold {gold}")
        lines.append(" ".join(parts))
        items = _format_items(active.get("items") or active.get("itemSlots"))
        if items:
            lines.append(f"- Items: {items}")
    players = data.get("allPlayers")
    if isinstance(players, list):
        allies: list[str] = []
        enemies: list[str] = []
        for p in players[:10]:
            if not isinstance(p, dict):
                continue
            name = _safe_str(p.get("summonerName") or p.get("riotId"))
            champ = _safe_str(p.get("championName"))
            team = _safe_str(p.get("team"))
            sc = p.get("scores") if isinstance(p.get("scores"), dict) else {}
            kda = f"{sc.get('kills', 0)}/{sc.get('deaths', 0)}/{sc.get('assists', 0)}"
            row = f"{name or champ} ({champ}) {kda}"
            if team.upper() == "ORDER":
                allies.append(row)
            elif team.upper() == "CHAOS":
                enemies.append(row)
        if allies:
            lines.append("- Allies: " + "; ".join(allies[:5]))
        if enemies:
            lines.append("- Enemies: " + "; ".join(enemies[:5]))
    events = data.get("events")
    if isinstance(events, dict):
        ev_list = events.get("Events")
        if isinstance(ev_list, list) and ev_list:
            recent = ev_list[-3:]
            bits: list[str] = []
            for ev in recent:
                if isinstance(ev, dict):
                    bits.append(_safe_str(ev.get("EventName") or ev.get("EventID")))
            if bits:
                lines.append("- Recent events: " + ", ".join(bits))
    return lines


def _lcu_gameflow_section(conn: LcuConnection) -> list[str]:
    lines: list[str] = []
    phase = lcu_get(conn, "/lol-gameflow/v1/gameflow-phase")
    if phase is not None:
        lines.append(f"- Client phase: {_safe_str(phase, default='unknown')}")
    summoner = lcu_get(conn, "/lol-summoner/v1/current-summoner")
    if summoner:
        lines.append(f"- Summoner: {_summoner_line(summoner)}")
    session = lcu_get(conn, "/lol-gameflow/v1/session")
    if isinstance(session, dict):
        mode = _safe_str(session.get("gameData", {}).get("gameMode") if isinstance(session.get("gameData"), dict) else "")
        if not mode:
            mode = _safe_str(session.get("map", {}).get("gameMode") if isinstance(session.get("map"), dict) else "")
        if mode:
            lines.append(f"- Queue/mode: {mode}")
    ranked = lcu_get(conn, "/lol-ranked/v1/current-ranked-stats")
    if isinstance(ranked, dict):
        for queue_key, label in (
            ("queueMap", "Ranked"),
            ("RANKED_SOLO_5x5", "Solo"),
            ("RANKED_FLEX_SR", "Flex"),
        ):
            block = ranked.get(queue_key) if queue_key in ranked else None
            if not isinstance(block, dict) and queue_key == "queueMap":
                continue
            if isinstance(ranked.get("queueMap"), dict):
                solo = ranked["queueMap"].get("RANKED_SOLO_5x5")
                if isinstance(solo, dict):
                    tier = _safe_str(solo.get("tier"))
                    div = _safe_str(solo.get("division"))
                    lp = solo.get("leaguePoints")
                    if tier:
                        lines.append(f"- Ranked solo: {tier} {div} ({lp} LP)".strip())
                break
    cs = lcu_get(conn, "/lol-champ-select/v1/session")
    if isinstance(cs, dict) and cs:
        timer = cs.get("timer", {})
        phase = _safe_str(timer.get("phase")) if isinstance(timer, dict) else ""
        my_team = cs.get("myTeam") if isinstance(cs.get("myTeam"), list) else []
        picks: list[str] = []
        for m in my_team:
            if isinstance(m, dict):
                picks.append(_safe_str(m.get("championId") or m.get("summonerId")))
        if phase:
            lines.append(f"- Champ select: {phase}")
        if picks:
            lines.append(f"- Team picks (ids): {', '.join(picks[:5])}")
    eog = lcu_get(conn, "/lol-end-of-game/v1/eog-stats-block")
    if isinstance(eog, dict) and eog:
        teams = eog.get("teams") if isinstance(eog.get("teams"), list) else []
        for team in teams[:2]:
            if not isinstance(team, dict):
                continue
            players = team.get("players") if isinstance(team.get("players"), list) else []
            for pl in players[:1]:
                if isinstance(pl, dict):
                    name = _safe_str(pl.get("summonerName"))
                    k = pl.get("kills")
                    d = pl.get("deaths")
                    a = pl.get("assists")
                    win = team.get("isWinningTeam")
                    if name:
                        w = "W" if win else "L"
                        lines.append(f"- Last game: {w} {name} {k}/{d}/{a}")
    return lines


def build_lol_context_snapshot() -> str:
    """One poll tick: LCU + optional live game data → plain-text block."""
    conn = read_lcu_connection()
    live_lines = _live_game_section()
    if conn is None and not live_lines:
        return ""
    body: list[str] = ["## League of Legends (Riot Client — local)"]
    body.append(
        "The streamer is playing solo; use these **exact stats** with screen vision. "
        "Do not invent KDA or rank."
    )
    if conn is not None:
        body.extend(_lcu_gameflow_section(conn))
    if live_lines:
        body.extend(live_lines)
    elif conn is not None:
        phase_raw = lcu_get(conn, "/lol-gameflow/v1/gameflow-phase")
        phase = _safe_str(phase_raw).lower()
        if phase in ("ingame", "inprogress", "gamestart"):
            body.append(
                "- Live match stats unavailable (enable in-game overlay / spectator API in LoL settings)."
            )
    text = "\n".join(body).strip()
    max_c = lol_context_max_chars()
    if len(text) > max_c:
        text = text[: max_c - 1] + "…"
    return text


def maybe_launch_riot_clients() -> None:
    """Windows: open shortcuts from env (Riot Client, then League) if configured."""
    if sys.platform != "win32":
        return
    if not _env_truthy("LUNA_LOL_LAUNCH_ON_START"):
        return
    for key in ("LUNA_LOL_RIOT_CLIENT_LNK", "LUNA_LOL_LEAGUE_LNK"):
        raw = (os.environ.get(key) or "").strip()
        if not raw:
            continue
        path = Path(raw).expanduser()
        if not path.is_file():
            print(f"(lol) launch path missing: {path}", flush=True)
            continue
        try:
            os.startfile(str(path))  # type: ignore[attr-defined]
            print(f"(lol) launched {path.name}", flush=True)
        except OSError as exc:
            print(f"(lol) launch failed ({path}): {exc}", flush=True)


async def run_lol_context_poller(
    on_update: Callable[[str], Awaitable[None]],
    *,
    broadcast_status: BroadcastStatus | None = None,
    interval_sec: float | None = None,
) -> None:
    """Poll LCU / live client until cancelled."""
    interval = interval_sec if interval_sec is not None else lol_poll_sec()
    print(f"(lol) context poller every {interval:.0f}s (League lockfile + live client)", flush=True)
    if broadcast_status:
        await broadcast_status(
            f"League context: polling Riot Client every {int(interval)}s."
        )
    last_nonempty = ""
    while True:
        try:
            snap = await asyncio.to_thread(build_lol_context_snapshot)
            if snap:
                if snap != last_nonempty:
                    last_nonempty = snap
                    await on_update(snap)
            else:
                if last_nonempty:
                    last_nonempty = ""
                    await on_update("")
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            print(f"(lol) poller error: {exc}", flush=True)
        try:
            await asyncio.sleep(interval)
        except asyncio.CancelledError:
            raise

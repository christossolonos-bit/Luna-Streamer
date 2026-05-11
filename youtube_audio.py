"""YouTube audio resolver / downloader using yt-dlp.

For `!play <url|search>` in Twitch chat and viewer panel: resolves a track,
optionally downloads it to a folder OBS (or anything else) can watch.

Env:
  LUNA_YT_DOWNLOAD_DIR   Folder where !play downloads audio (default <project>/data/yt_audio).
  LUNA_YT_DEFAULT_FORMAT yt-dlp format string (default bestaudio[ext=m4a]/bestaudio/best).
  LUNA_YT_DOWNLOAD       If 1, !play also downloads the file (default 1).
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any


def _default_download_dir() -> Path:
    raw = (os.environ.get("LUNA_YT_DOWNLOAD_DIR") or "").strip()
    if raw:
        return Path(raw)
    return Path(__file__).resolve().parent / "data" / "yt_audio"


def _format_pref() -> str:
    raw = (os.environ.get("LUNA_YT_DEFAULT_FORMAT") or "").strip()
    return raw or "bestaudio[ext=m4a]/bestaudio/best"


def download_enabled() -> bool:
    raw = (os.environ.get("LUNA_YT_DOWNLOAD") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _safe_filename(text: str, fallback: str = "track") -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", text or "").strip()
    return (cleaned[:80] or fallback).rstrip(". ")


def resolve_track(query: str) -> tuple[bool, dict[str, Any] | str]:
    """Resolve a YouTube URL or search phrase into stream metadata."""
    q = (query or "").strip()
    if not q:
        return False, "Please provide a YouTube URL or search terms."
    try:
        import yt_dlp
    except ImportError:
        return False, "yt-dlp is not installed. Run: pip install yt-dlp"

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "format": _format_pref(),
        "noplaylist": True,
        "default_search": "ytsearch1",
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(q, download=False)
    except Exception as exc:  # noqa: BLE001
        return False, f"Could not resolve YouTube audio: {exc}"

    if isinstance(info, dict) and info.get("entries"):
        entries = [e for e in info["entries"] if e]
        if not entries:
            return False, "No matching YouTube result."
        info = entries[0]
    if not isinstance(info, dict):
        return False, "Unexpected response from yt-dlp."

    stream_url = (info.get("url") or "").strip()
    if not stream_url:
        for f in info.get("formats", []) or []:
            if f.get("url") and (f.get("acodec") or "") not in ("none", ""):
                stream_url = f["url"]
                break
    web_url = info.get("webpage_url") or info.get("original_url") or ""
    title = (info.get("title") or "(unknown title)").strip()
    duration = info.get("duration")
    uploader = info.get("uploader") or info.get("channel") or ""
    return True, {
        "title": title,
        "uploader": uploader,
        "duration_sec": int(duration) if isinstance(duration, (int, float)) else None,
        "web_url": web_url,
        "stream_url": stream_url,
        "thumbnail": info.get("thumbnail") or "",
    }


def download_to_dir(query: str, target_dir: Path | None = None) -> tuple[bool, str]:
    """Download audio for a query. Returns (ok, path_or_error)."""
    q = (query or "").strip()
    if not q:
        return False, "Please provide a YouTube URL or search terms."
    try:
        import yt_dlp
    except ImportError:
        return False, "yt-dlp is not installed. Run: pip install yt-dlp"

    out_dir = target_dir or _default_download_dir()
    out_dir.mkdir(parents=True, exist_ok=True)

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "format": _format_pref(),
        "noplaylist": True,
        "default_search": "ytsearch1",
        "outtmpl": str(out_dir / "%(title).80s [%(id)s].%(ext)s"),
        "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
    }
    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(q, download=True)
    except Exception as exc:  # noqa: BLE001
        return False, f"Download failed: {exc}"

    if isinstance(info, dict) and info.get("entries"):
        info = next((e for e in info["entries"] if e), info)
    if not isinstance(info, dict):
        return False, "Unexpected response from yt-dlp."

    rd = info.get("requested_downloads")
    if isinstance(rd, list) and rd:
        path = rd[0].get("filepath") or rd[0].get("_filename")
        if path:
            return True, str(path)
    fname = info.get("_filename")
    if fname:
        return True, str(fname)
    return False, "Download completed but path was not returned."


YT_ID_RE = re.compile(
    r"(?:v=|/shorts/|youtu\.be/|/embed/|/v/)([A-Za-z0-9_-]{11})"
)


def extract_video_id(url: str) -> str:
    m = YT_ID_RE.search(url or "")
    return m.group(1) if m else ""


def fetch_transcript(url: str, *, languages: tuple[str, ...] = ("en", "en-US", "en-GB")) -> tuple[bool, str, str]:
    """Return (ok, title, transcript_text). Uses youtube-transcript-api, falls back to yt-dlp subtitles."""
    vid = extract_video_id(url)
    if not vid:
        return False, "", "Could not parse a YouTube video id from the URL."

    title = ""
    try:
        import yt_dlp

        with yt_dlp.YoutubeDL({"quiet": True, "no_warnings": True, "skip_download": True, "noplaylist": True}) as ydl:
            info = ydl.extract_info(url, download=False) or {}
            title = (info.get("title") or "").strip()
    except Exception:
        pass

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore
    except ImportError:
        return False, title, (
            "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"
        )

    try:
        listing = YouTubeTranscriptApi.list_transcripts(vid)
        transcript = None
        try:
            transcript = listing.find_manually_created_transcript(list(languages))
        except Exception:
            try:
                transcript = listing.find_generated_transcript(list(languages))
            except Exception:
                for t in listing:
                    transcript = t
                    break
        if transcript is None:
            return False, title, "No transcripts available for this video."
        segments = transcript.fetch()
    except Exception as exc:  # noqa: BLE001
        return False, title, f"Could not fetch transcript: {exc}"

    parts: list[str] = []
    for s in segments:
        line = (s.get("text") if isinstance(s, dict) else getattr(s, "text", "")) or ""
        line = line.replace("\n", " ").strip()
        if line:
            parts.append(line)
    text = " ".join(parts).strip()
    if not text:
        return False, title, "Transcript was empty."
    return True, title, text


def short_status_line(meta: dict[str, Any]) -> str:
    dur = meta.get("duration_sec")
    dur_s = ""
    if isinstance(dur, int) and dur > 0:
        mm, ss = divmod(dur, 60)
        dur_s = f" [{mm}:{ss:02d}]"
    src = meta.get("uploader")
    src_s = f" — {src}" if src else ""
    return f"{meta.get('title', '?')}{src_s}{dur_s}"

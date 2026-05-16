"""YouTube audio resolver / downloader using yt-dlp.

For `!play <url|search>` in Twitch chat and viewer panel: resolves a track,
optionally downloads it to a folder OBS (or anything else) can watch.

Env:
  LUNA_YT_DOWNLOAD_DIR   Folder where !play downloads audio (default <project>/data/yt_audio).
  LUNA_YT_DEFAULT_FORMAT yt-dlp format string (default bestaudio[ext=m4a]/bestaudio/best).
  LUNA_YT_DOWNLOAD       If 1, !play also downloads the file (default 1).
  LUNA_YT_VISION_FALLBACK   If 1 (default), sample video frames and describe via OLLAMA_VISION_MODEL (Qwen).
  LUNA_YT_VISION_MODEL      Vision model override (default OLLAMA_VISION_MODEL / LUNA_SCREEN_VISION_MODEL).
  LUNA_YT_VISION_MAX_SEC    Seconds of video to download for frame samples (default 120).
  LUNA_YT_VISION_FRAMES     Number of JPEG frames sent to vision (default 4).
  LUNA_YT_VISION_PROMPT     Optional prompt; {title} {n_frames}.
  LUNA_YT_WHISPER_FALLBACK  If 1, transcribe audio with Whisper (default on when vision is on).
  LUNA_YT_COMBINE_VISION_WHISPER  If 1 (default), merge vision + Whisper into one LLM context.
  LUNA_YT_PLAYER_CLIENTS    Comma-separated yt-dlp YouTube player clients (default android,web,ios,tv,mweb).
"""

from __future__ import annotations

import base64
import os
import re
import shutil
import subprocess
import tempfile
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


_VTT_TS_RE = re.compile(r"^\d{2}:\d{2}")


def _segments_to_text(segments: object) -> str:
    parts: list[str] = []
    if hasattr(segments, "snippets"):
        segments = segments.snippets  # type: ignore[attr-defined]
    for s in segments or []:
        if isinstance(s, dict):
            line = (s.get("text") or "").strip()
        else:
            line = (getattr(s, "text", "") or "").strip()
        line = line.replace("\n", " ").strip()
        if line:
            parts.append(line)
    return " ".join(parts).strip()


def _parse_vtt(raw: str) -> str:
    lines: list[str] = []
    for line in raw.splitlines():
        s = line.strip()
        if not s or s.startswith("WEBVTT") or "-->" in s or _VTT_TS_RE.match(s):
            continue
        if s.startswith("NOTE") or s.isdigit():
            continue
        lines.append(re.sub(r"<[^>]+>", "", s).strip())
    return " ".join(x for x in lines if x).strip()


def _yt_player_clients() -> list[str]:
    raw = (os.environ.get("LUNA_YT_PLAYER_CLIENTS") or "").strip()
    if raw:
        return [c.strip() for c in raw.split(",") if c.strip()]
    return ["android", "web", "ios", "tv", "mweb"]


def _yt_vision_fallback_enabled() -> bool:
    raw = (os.environ.get("LUNA_YT_VISION_FALLBACK") or "1").strip().lower()
    return raw in ("1", "true", "yes", "on")


def _yt_vision_model() -> str:
    for key in (
        "LUNA_YT_VISION_MODEL",
        "OLLAMA_VISION_MODEL",
        "LUNA_SCREEN_VISION_MODEL",
        "OLLAMA_MODEL",
        "LUNA_CHAT_MODEL",
    ):
        m = (os.environ.get(key) or "").strip()
        if m:
            return m
    return ""


def _yt_vision_max_sec() -> int:
    raw = (os.environ.get("LUNA_YT_VISION_MAX_SEC") or "120").strip() or "120"
    try:
        return max(15, min(int(raw), 600))
    except ValueError:
        return 120


def _yt_vision_frame_count() -> int:
    raw = (os.environ.get("LUNA_YT_VISION_FRAMES") or "4").strip() or "4"
    try:
        return max(1, min(int(raw), 8))
    except ValueError:
        return 4


def _yt_combine_vision_whisper() -> bool:
    raw = (os.environ.get("LUNA_YT_COMBINE_VISION_WHISPER") or "1").strip().lower()
    return raw not in ("0", "false", "no", "off")


def _yt_whisper_fallback_enabled() -> bool:
    raw = (os.environ.get("LUNA_YT_WHISPER_FALLBACK") or "").strip().lower()
    if raw in ("0", "false", "no", "off"):
        return False
    if raw in ("1", "true", "yes", "on"):
        return True
    # Default: hear the video when vision fallback is on (combine see + hear).
    return _yt_vision_fallback_enabled() and _yt_combine_vision_whisper()


def _merge_vision_whisper_context(vision: str, whisper: str) -> tuple[str, str]:
    v = (vision or "").strip()
    w = (whisper or "").strip()
    if v and w:
        return (
            "## What is visible (vision model)\n"
            f"{v}\n\n"
            "## What is heard / spoken (Whisper)\n"
            f"{w}",
            "vision+whisper",
        )
    if v:
        return v, "vision"
    if w:
        return w, "whisper"
    return "", ""


def _yt_whisper_max_sec() -> int:
    raw = (os.environ.get("LUNA_YT_WHISPER_MAX_SEC") or "480").strip() or "480"
    try:
        return max(30, min(int(raw), 3600))
    except ValueError:
        return 480


def _yt_dlp_info_once(url: str, player_client: str) -> dict[str, Any]:
    import yt_dlp

    opts: dict[str, Any] = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
        "noplaylist": True,
        "extractor_args": {"youtube": {"player_client": [player_client]}},
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=False) or {}
    return info if isinstance(info, dict) else {}


def _yt_dlp_info(url: str) -> dict[str, Any]:
    last_exc: Exception | None = None
    for client in _yt_player_clients():
        try:
            return _yt_dlp_info_once(url, client)
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
    if last_exc is not None:
        print(f"(youtube) metadata failed ({last_exc})", flush=True)
    return {}


def _ffmpeg_audio_to_wav(src: Path, wav_path: Path, *, max_sec: int) -> None:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    cmd = [
        ffmpeg,
        "-y",
        "-v",
        "error",
        "-i",
        str(src),
        "-t",
        str(max_sec),
        "-ac",
        "1",
        "-ar",
        "16000",
        str(wav_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0 or not wav_path.is_file() or wav_path.stat().st_size < 256:
        err = (proc.stderr or proc.stdout or "").strip() or "ffmpeg failed"
        raise RuntimeError(err)


def _ffmpeg_probe_duration(path: Path) -> float:
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return 0.0
    cmd = [
        ffprobe,
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        str(path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        return 0.0
    try:
        return max(0.0, float((proc.stdout or "").strip()))
    except ValueError:
        return 0.0


def _yt_dlp_download_video(url: str, out_dir: Path) -> Path | None:
    """Download a short low-res clip for vision frame extraction."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out_dir / "clip.%(ext)s")
    for client in _yt_player_clients():
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "best[height<=480][ext=mp4]/best[height<=480]/best[ext=mp4]/best",
            "outtmpl": outtmpl,
            "extractor_args": {"youtube": {"player_client": [client]}},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            print(f"(youtube) video download ({client}): {exc}", flush=True)
            continue
        files = sorted(out_dir.glob("clip.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def _extract_video_frame_jpegs(video: Path, *, count: int, max_sec: int) -> list[Path]:
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg not found in PATH")
    duration = _ffmpeg_probe_duration(video)
    if duration <= 0:
        duration = float(max_sec)
    span = min(duration, float(max_sec))
    count = max(1, count)
    max_w = int((os.environ.get("LUNA_YT_VISION_FRAME_WIDTH") or "1280").strip() or "1280")
    max_w = max(480, min(max_w, 1920))
    out_paths: list[Path] = []
    for i in range(count):
        t = max(0.0, ((i + 0.5) / count) * span - 0.25)
        out = video.parent / f"frame_{i}.jpg"
        cmd = [
            ffmpeg,
            "-y",
            "-v",
            "error",
            "-ss",
            f"{t:.2f}",
            "-i",
            str(video),
            "-frames:v",
            "1",
            "-vf",
            f"scale='min({max_w},iw)':-2",
            "-q:v",
            "4",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode == 0 and out.is_file() and out.stat().st_size > 512:
            out_paths.append(out)
    return out_paths


def _vision_from_clip(clip: Path, *, title: str) -> str:
    """Describe sampled frames with the configured Ollama vision model (e.g. Qwen 3.5)."""
    model = _yt_vision_model()
    if not model:
        print("(youtube) vision: no OLLAMA_VISION_MODEL / OLLAMA_MODEL set.", flush=True)
        return ""
    max_sec = _yt_vision_max_sec()
    n_frames = _yt_vision_frame_count()
    print(
        f"(youtube) vision: {n_frames} frame(s), first {max_sec}s, model {model!r}…",
        flush=True,
    )
    try:
        from ollama_client import build_client, describe_youtube_video
    except ImportError:
        return ""
    try:
        frames = _extract_video_frame_jpegs(clip, count=n_frames, max_sec=max_sec)
    except Exception as exc:  # noqa: BLE001
        print(f"(youtube) frame extract: {exc}", flush=True)
        return ""
    if not frames:
        return ""
    images_b64 = [
        base64.b64encode(p.read_bytes()).decode("ascii") for p in frames if p.is_file()
    ]
    if not images_b64:
        return ""
    try:
        client = build_client()
        description = describe_youtube_video(client, model, images_b64, title=title)
    except Exception as exc:  # noqa: BLE001
        print(f"(youtube) vision describe failed: {exc}", flush=True)
        return ""
    description = (description or "").strip()
    if description:
        print(f"(youtube) vision description: {len(description)} chars", flush=True)
    return description


def _whisper_from_clip(clip: Path) -> str:
    """Transcribe audio track from a downloaded video clip."""
    max_sec = _yt_whisper_max_sec()
    print(f"(youtube) Whisper: transcribing up to {max_sec}s of audio…", flush=True)
    try:
        from luna_stt import transcribe_wav_file
    except ImportError:
        print("(youtube) luna_stt unavailable for Whisper.", flush=True)
        return ""
    wav_path = clip.parent / "clip_audio.wav"
    try:
        _ffmpeg_audio_to_wav(clip, wav_path, max_sec=max_sec)
    except Exception as exc:  # noqa: BLE001
        print(f"(youtube) ffmpeg for Whisper: {exc}", flush=True)
        return ""
    text, note = transcribe_wav_file(wav_path)
    if text and not note.startswith("failed"):
        print(f"(youtube) Whisper transcript: {len(text)} chars ({note})", flush=True)
        return text
    print(f"(youtube) Whisper failed: {note}", flush=True)
    return ""


def _multimodal_context_youtube(url: str, *, title: str) -> tuple[str, str]:
    """Download once; run vision (see) and/or Whisper (hear); return merged LLM context."""
    vision_on = _yt_vision_fallback_enabled()
    whisper_on = _yt_whisper_fallback_enabled()
    if not vision_on and not whisper_on:
        return "", ""

    modes: list[str] = []
    if vision_on:
        modes.append("vision")
    if whisper_on:
        modes.append("Whisper")
    print(
        f"(youtube) no captions — analyzing with {' + '.join(modes)} (single download)…",
        flush=True,
    )

    with tempfile.TemporaryDirectory(prefix="luna-yt-multimodal-") as td:
        td_path = Path(td)
        clip = _yt_dlp_download_video(url, td_path)
        vision_text = ""
        whisper_text = ""
        if clip is not None:
            if vision_on:
                vision_text = _vision_from_clip(clip, title=title)
            if whisper_on:
                whisper_text = _whisper_from_clip(clip)
        elif whisper_on:
            audio_path = _yt_dlp_download_audio(url, td_path)
            if audio_path is not None:
                wav_path = td_path / "audio.wav"
                try:
                    _ffmpeg_audio_to_wav(audio_path, wav_path, max_sec=_yt_whisper_max_sec())
                    from luna_stt import transcribe_wav_file

                    text, note = transcribe_wav_file(wav_path)
                    if text and not note.startswith("failed"):
                        whisper_text = text
                except Exception as exc:  # noqa: BLE001
                    print(f"(youtube) audio-only Whisper: {exc}", flush=True)

        if _yt_combine_vision_whisper() or (vision_text and whisper_text):
            return _merge_vision_whisper_context(vision_text, whisper_text)
        return _merge_vision_whisper_context(
            vision_text if vision_on else "",
            whisper_text if whisper_on else "",
        )


def _yt_dlp_download_audio(url: str, out_dir: Path) -> Path | None:
    """Download best audio to ``out_dir``; return path or None."""
    import yt_dlp

    out_dir.mkdir(parents=True, exist_ok=True)
    outtmpl = str(out_dir / "audio.%(ext)s")
    for client in _yt_player_clients():
        opts: dict[str, Any] = {
            "quiet": True,
            "no_warnings": True,
            "noplaylist": True,
            "format": "bestaudio[ext=m4a]/bestaudio/best",
            "outtmpl": outtmpl,
            "extractor_args": {"youtube": {"player_client": [client]}},
        }
        try:
            with yt_dlp.YoutubeDL(opts) as ydl:
                ydl.download([url])
        except Exception as exc:  # noqa: BLE001
            print(f"(youtube) audio download ({client}): {exc}", flush=True)
            continue
        files = sorted(out_dir.glob("audio.*"), key=lambda p: p.stat().st_mtime, reverse=True)
        if files:
            return files[0]
    return None


def _yt_dlp_subtitle_text(info: dict[str, Any], languages: tuple[str, ...]) -> str:
    import urllib.request

    pools: list[dict[str, Any]] = []
    subs = info.get("subtitles")
    if isinstance(subs, dict):
        pools.append(subs)
    auto = info.get("automatic_captions")
    if isinstance(auto, dict):
        pools.append(auto)
    lang_list = list(languages) + ["en", "en-US", "en-GB"]
    seen: set[str] = set()
    ordered_langs: list[str] = []
    for lang in lang_list:
        if lang and lang not in seen:
            seen.add(lang)
            ordered_langs.append(lang)

    for pool in pools:
        for lang in ordered_langs:
            entries = pool.get(lang)
            if not entries:
                continue
            pick = None
            for ext in ("vtt", "srv1", "srv2", "srv3", "ttml", "json3"):
                for entry in entries:
                    if (entry.get("ext") or "") == ext and entry.get("url"):
                        pick = entry
                        break
                if pick:
                    break
            if pick is None:
                pick = entries[0] if entries else None
            if not pick or not pick.get("url"):
                continue
            try:
                with urllib.request.urlopen(pick["url"], timeout=30) as resp:  # noqa: S310
                    raw = resp.read().decode("utf-8", "replace")
            except Exception:
                continue
            text = _parse_vtt(raw) if (pick.get("ext") or "").startswith("vtt") else raw
            text = _segments_to_text([{"text": text}]) if not text else text
            if text:
                return text
    return ""


def _fetch_transcript_api(vid: str, languages: tuple[str, ...]) -> str:
    from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore

    lang_list = list(languages)

    # v1.x: instance API (list / fetch).
    api = YouTubeTranscriptApi()
    if hasattr(api, "fetch"):
        try:
            fetched = api.fetch(vid, languages=tuple(lang_list))
            text = _segments_to_text(fetched)
            if text:
                return text
        except Exception:
            pass
        if hasattr(api, "list"):
            listing = api.list(vid)
            transcript = None
            try:
                transcript = listing.find_manually_created_transcript(lang_list)
            except Exception:
                try:
                    transcript = listing.find_generated_transcript(lang_list)
                except Exception:
                    for t in listing:
                        transcript = t
                        break
            if transcript is not None:
                return _segments_to_text(transcript.fetch())

    # v0.6.x: class methods.
    if hasattr(YouTubeTranscriptApi, "list_transcripts"):
        listing = YouTubeTranscriptApi.list_transcripts(vid)
        transcript = None
        try:
            transcript = listing.find_manually_created_transcript(lang_list)
        except Exception:
            try:
                transcript = listing.find_generated_transcript(lang_list)
            except Exception:
                for t in listing:
                    transcript = t
                    break
        if transcript is not None:
            return _segments_to_text(transcript.fetch())
    return ""


def fetch_video_context(
    url: str, *, languages: tuple[str, ...] = ("en", "en-US", "en-GB")
) -> tuple[bool, str, str, str]:
    """Return ``(ok, title, llm_context, source)``.

    ``source`` is ``transcript``, ``subtitles``, ``vision+whisper``, ``vision``, ``whisper``, or ``description``.
    """
    vid = extract_video_id(url)
    if not vid:
        return False, "", "Could not parse a YouTube video id from the URL.", ""

    title = ""
    description = ""
    uploader = ""
    try:
        info = _yt_dlp_info(url)
        title = (info.get("title") or "").strip()
        description = (info.get("description") or "").strip()
        uploader = (info.get("uploader") or info.get("channel") or "").strip()
    except Exception:
        info = {}

    try:
        from youtube_transcript_api import YouTubeTranscriptApi  # type: ignore  # noqa: F401
    except ImportError:
        return False, title, (
            "youtube-transcript-api is not installed. Run: pip install youtube-transcript-api"
        ), ""

    transcript_text = ""
    try:
        transcript_text = _fetch_transcript_api(vid, languages)
    except Exception:
        transcript_text = ""

    if not transcript_text and info:
        try:
            transcript_text = _yt_dlp_subtitle_text(info, languages)
            if transcript_text:
                return True, title, transcript_text, "subtitles"
        except Exception:
            pass

    if transcript_text:
        return True, title, transcript_text, "transcript"

    multimodal, source = _multimodal_context_youtube(url, title=title)
    if multimodal:
        return True, title, multimodal, source

    meta_bits: list[str] = []
    if uploader:
        meta_bits.append(f"Channel: {uploader}")
    if description:
        meta_bits.append(description)
    fallback = "\n\n".join(meta_bits).strip()
    if fallback:
        return True, title, fallback, "description"

    if title:
        return True, title, f"(No captions or description text; title only: {title})", "title"

    return (
        False,
        title,
        "No transcript, subtitles, vision description, or metadata available for this video.",
        "",
    )


def fetch_transcript(url: str, *, languages: tuple[str, ...] = ("en", "en-US", "en-GB")) -> tuple[bool, str, str]:
    """Return ``(ok, title, context_text)`` for !explain / YouTube comments (see ``fetch_video_context``)."""
    ok, title, context, _source = fetch_video_context(url, languages=languages)
    if not ok:
        return False, title, context
    return True, title, context


def short_status_line(meta: dict[str, Any]) -> str:
    dur = meta.get("duration_sec")
    dur_s = ""
    if isinstance(dur, int) and dur > 0:
        mm, ss = divmod(dur, 60)
        dur_s = f" [{mm}:{ss:02d}]"
    src = meta.get("uploader")
    src_s = f" — {src}" if src else ""
    return f"{meta.get('title', '?')}{src_s}{dur_s}"

#!/usr/bin/env python3
"""Fetch recent @lunawolfsolo videos and shorts; write website/src/data/channelVideos.json."""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

CHANNEL_HANDLE = "@lunawolfsolo"
CHANNEL_VIDEOS_URL = f"https://www.youtube.com/{CHANNEL_HANDLE}/videos"
CHANNEL_SHORTS_URL = f"https://www.youtube.com/{CHANNEL_HANDLE}/shorts"
OUT = Path(__file__).resolve().parents[1] / "website" / "src" / "data" / "channelVideos.json"
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
PLACEHOLDER_IDS = frozenset({"MgCmBDHcb8"})


def fetch_page_html(url: str) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    return urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")


def extract_video_ids(html: str) -> list[str]:
    ids: list[str] = []
    for m in re.finditer(r'"videoId":"([a-zA-Z0-9_-]{11})"', html):
        vid = m.group(1)
        if vid not in ids and vid not in PLACEHOLDER_IDS:
            ids.append(vid)
    return ids


def extract_titles(html: str, ids: list[str]) -> dict[str, str]:
    titles: dict[str, str] = {}
    for vid in ids:
        for pat in (
            rf'"videoId":"{re.escape(vid)}".{{0,1200}}?"title":\{{"runs":\[\{{"text":"([^"]+)"',
            rf'"videoId":"{re.escape(vid)}".{{0,1200}}?"title":"([^"]+)"',
        ):
            tm = re.search(pat, html)
            if tm:
                titles[vid] = (
                    tm.group(1)
                    .encode("utf-8")
                    .decode("unicode_escape")
                    .replace("\\u0026", "&")[:120]
                )
                break
    return titles


def fetch_oembed_title(video_id: str) -> str:
    oembed_url = (
        "https://www.youtube.com/oembed?"
        f"url=https://www.youtube.com/watch?v={video_id}&format=json"
    )
    oreq = urllib.request.Request(oembed_url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(oreq, timeout=15) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return (data.get("title") or "").strip()[:120]


def fetch_entries(page_url: str, *, limit: int = 12, label: str) -> list[dict[str, str]]:
    html = fetch_page_html(page_url)
    ids = extract_video_ids(html)[:limit]
    titles = extract_titles(html, ids)

    for vid in ids:
        if vid in titles:
            continue
        try:
            title = fetch_oembed_title(vid)
            if title:
                titles[vid] = title
        except OSError:
            pass

    return [{"id": vid, "title": titles.get(vid, f"{label} {i + 1}")} for i, vid in enumerate(ids)]


def main() -> int:
    videos = fetch_entries(CHANNEL_VIDEOS_URL, limit=12, label="Video")
    shorts = fetch_entries(CHANNEL_SHORTS_URL, limit=12, label="Short")
    payload = {
        "channel_url": f"https://www.youtube.com/{CHANNEL_HANDLE}",
        "channel_title": "Luna wolf",
        "videos": videos,
        "shorts": shorts,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(videos)} videos and {len(shorts)} shorts to {OUT}")
    return 0 if videos or shorts else 1


if __name__ == "__main__":
    sys.exit(main())

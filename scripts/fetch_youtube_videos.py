#!/usr/bin/env python3
"""Fetch recent @lunawolfsolo video IDs and write website/src/data/channelVideos.json."""

from __future__ import annotations

import json
import re
import sys
import urllib.request
from pathlib import Path

CHANNEL_VIDEOS_URL = "https://www.youtube.com/@lunawolfsolo/videos"
OUT = Path(__file__).resolve().parents[1] / "website" / "src" / "data" / "channelVideos.json"


def main() -> int:
    req = urllib.request.Request(
        CHANNEL_VIDEOS_URL,
        headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"},
    )
    html = urllib.request.urlopen(req, timeout=45).read().decode("utf-8", "replace")
    ids: list[str] = []
    for m in re.finditer(r'"videoId":"([a-zA-Z0-9_-]{11})"', html):
        vid = m.group(1)
        if vid not in ids and vid not in ("MgCmBDHcb8",):  # youtube placeholder
            ids.append(vid)
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

    for vid in ids[:12]:
        if vid in titles:
            continue
        try:
            oembed_url = (
                "https://www.youtube.com/oembed?"
                f"url=https://www.youtube.com/watch?v={vid}&format=json"
            )
            oreq = urllib.request.Request(oembed_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(oreq, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            title = (data.get("title") or "").strip()
            if title:
                titles[vid] = title[:120]
        except OSError:
            pass

    videos = [{"id": vid, "title": titles.get(vid, f"Video {i + 1}")} for i, vid in enumerate(ids[:12])]
    payload = {
        "channel_url": "https://www.youtube.com/@lunawolfsolo",
        "channel_title": "Luna wolf",
        "videos": videos,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {len(videos)} videos to {OUT}")
    return 0 if videos else 1


if __name__ == "__main__":
    sys.exit(main())

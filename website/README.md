# Luna marketing site

Showcase page: Luna’s intro, **embedded YouTube player** ([@lunawolfsolo](https://www.youtube.com/@lunawolfsolo)), **Discord** ([Luna's Wolf Den](https://discord.gg/t3DpY3EP)), and cast bios (Luna, Himari, Viktor).

## Open quickly (Windows)

- Double-click **`Open Luna Website.bat`** in the repo root.
- Or run **`Create Luna Website Shortcut.bat`** once for a Desktop icon.

## Run locally

```bash
cd website
npm install
npm run dev
```

Open **http://127.0.0.1:5180/**

Or: `python main.py --website --no-bot`

## Refresh channel videos

From the repo root:

```bash
python scripts/fetch_youtube_videos.py
```

This updates `website/src/data/channelVideos.json` (IDs and titles). Rebuild or restart dev after refreshing.

Optional override in `website/.env`:

```env
VITE_YOUTUBE_VIDEO_IDS=VIDEO_ID_1,VIDEO_ID_2
VITE_DISCORD_INVITE_URL=https://discord.gg/t3DpY3EP
```

## GitHub Pages

1. Repo **Settings → Pages → Source: GitHub Actions**
2. Push `website/` and `.github/workflows/deploy-website.yml` to `main`
3. Site: **https://christossolonos-bit.github.io/Luna-Streamer/**

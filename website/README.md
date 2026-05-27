# Luna marketing site

Showcase page with Luna’s intro, **YouTube** ([@lunawolfsolo](https://www.youtube.com/@lunawolfsolo)), and three chat panels (Luna, Himari, Viktor).

## YouTube vs chat

| Feature | Luna running on your PC? |
|---------|-------------------------|
| YouTube links & embeds | **No** — always works |
| Cast chat (pre-written) | **No** — works everywhere, no cloud |

Full AI chat stays in the VRM viewer / stream stack, not on this public site.

## Open quickly (Windows)

- Double-click **`Open Luna Website.bat`** in the repo root (pin that file to the taskbar if you like).
- Or run **`Create Luna Website Shortcut.bat`** once — puts a **Luna Website** icon on your Desktop.

After you **commit and push**, those `.bat` files stay in the repo for everyone who clones it. A Desktop shortcut is only on your PC until you recreate it.

## Run locally

```bash
python main.py --website
```

Or:

```bash
cd website
npm install
npm run dev
```

## Featured video embeds

Add real video IDs from your channel to `website/.env`:

```env
VITE_YOUTUBE_VIDEO_IDS=VIDEO_ID_1,VIDEO_ID_2,VIDEO_ID_3
```

Copy the 11-character id from a watch URL: `youtube.com/watch?v=XXXXXXXXXXX`

## GitHub Pages

1. Repo **Settings → Pages → Build and deployment → GitHub Actions**.
2. Push to `main`; workflow `.github/workflows/deploy-website.yml` publishes `website/dist`.
3. Site URL (project page): **https://christossolonos-bit.github.io/Luna-Streamer/**

`VITE_BASE_PATH=/Luna-Streamer/` is set in CI automatically. For a **user** site (`username.github.io`), change base to `/` in the workflow.

## Config

See `.env.example` for WebSocket URL, cast names, and YouTube settings.

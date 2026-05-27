# Fix GitHub Pages (shows README instead of the Luna site)

If **https://christossolonos-bit.github.io/Luna-Streamer/** looks like the repo README but **http://127.0.0.1:5180** looks correct, Pages is publishing the **wrong source**.

## One-time fix (required)

1. Open **https://github.com/christossolonos-bit/Luna-Streamer/settings/pages**
2. Under **Build and deployment → Source**, choose **GitHub Actions** (not “Deploy from a branch”).
3. Save.
4. Open **Actions** → **Deploy website to GitHub Pages** → **Run workflow** → **Run workflow**.
5. Wait until the run is green (~1–2 minutes), then hard-refresh the site (Ctrl+F5).

You should see the dark “Hi, I’m Luna” page with the video player and **Join Discord** button.

## Why this happens

- **Branch / root** deploy renders `README.md` as the homepage (what you see now).
- **GitHub Actions** deploy runs `website/` through Vite and publishes `website/dist` (what you built locally).

Both workflows can appear under Actions; only **GitHub Actions** should be the Pages source.

## Still wrong after switching?

- Confirm the latest **Deploy website to GitHub Pages** run succeeded (green check).
- URL must include the project path: `https://christossolonos-bit.github.io/Luna-Streamer/` (trailing slash is fine).
- Give Pages a minute after the deploy job finishes.

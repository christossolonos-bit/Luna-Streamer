# GitHub Pages setup

Marketing site URL: **https://christossolonos-bit.github.io/Luna-Streamer/**

## Deploy (automatic)

Every push to `main` runs **Actions → Deploy website to GitHub Pages**, which:

1. Builds `website/` (Vite)
2. Publishes to the **`gh-pages`** branch
3. Deploys via **GitHub Actions** (if that source is enabled)

To deploy manually: **Actions** → **Deploy website to GitHub Pages** → **Run workflow**.

## If you still see the README

Pages is probably serving **`main` / root** (renders `README.md`). Switch it once:

1. **https://github.com/christossolonos-bit/Luna-Streamer/settings/pages**
2. **Source:** either
   - **GitHub Actions** (recommended — uses the workflow deploy job), or
   - **Deploy from a branch** → branch **`gh-pages`** → folder **`/ (root)`**
3. **Do not** use **main** + root for the public site.
4. Save, wait for the latest green workflow run, then hard-refresh (Ctrl+F5).

## Local preview

```bash
cd website
npm run dev
```

http://127.0.0.1:5180/

"""Save a logged-in Playwright session for Luna social sharing (X / Facebook / TikTok).

TikTok and X auto-launch **your real Chrome** (CDP) so Google sign-in is not blocked.

From the repo root (same Python venv as Luna):

  pip install playwright
  python -m playwright install chrome
  python scripts/social_playwright_login.py https://x.com D:/path/luna_x.json
  python scripts/social_playwright_login.py https://www.tiktok.com D:/path/luna_tiktok.json

Optional env (same as Luna): LUNA_SOCIAL_CHROME_EXECUTABLE, LUNA_SOCIAL_INTERACTIVE_PROFILE_ROOT,
LUNA_SOCIAL_INTERACTIVE_CDP_URL, LUNA_SOCIAL_INTERACTIVE_CDP_PORT, etc.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Open Chrome for Luna social login, then save storage_state JSON.",
    )
    ap.add_argument("start_url", help="First page, e.g. https://x.com or https://www.tiktok.com")
    ap.add_argument(
        "out_json",
        type=Path,
        help="Output path for storage state (e.g. D:/secrets/luna_x.json)",
    )
    args = ap.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    if str(repo_root) not in sys.path:
        sys.path.insert(0, str(repo_root))

    from playwright.sync_api import sync_playwright

    from social_playwright_share import (
        STEALTH_INIT_SCRIPT,
        ensure_interactive_cdp_browser,
        interactive_login_chrome_user_data_dir,
        interactive_login_persistent_launch_kwargs,
        interactive_login_prefers_user_chrome,
        stealth_browser_context_kwargs,
    )

    out = args.out_json.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    def _site_from_url(url: str) -> str:
        u = url.lower()
        if "facebook.com" in u:
            return "facebook"
        if "tiktok.com" in u:
            return "tiktok"
        if "youtube.com" in u or "youtu.be" in u:
            return "youtube"
        if "x.com" in u or "twitter.com" in u:
            return "x"
        return "web"

    site = _site_from_url(args.start_url)
    use_user_chrome = interactive_login_prefers_user_chrome(site)

    async def _bcast(text: str) -> None:
        print(text, flush=True)

    with sync_playwright() as pw:
        cdp_default_context = False
        if use_user_chrome:
            profile_dir = interactive_login_chrome_user_data_dir(out, site)
            cdp_url, _proc = asyncio.run(
                ensure_interactive_cdp_browser(profile_dir=profile_dir, broadcast=_bcast)
            )
            print(f"CDP: {cdp_url} (real Chrome — Google sign-in OK)", flush=True)
            browser = pw.chromium.connect_over_cdp(cdp_url)
            if browser.contexts:
                context = browser.contexts[0]
                cdp_default_context = True
            else:
                context = browser.new_context(
                    **stealth_browser_context_kwargs(storage_state=None, omit_user_agent=True)
                )
        else:
            profile_dir, launch_kw = interactive_login_persistent_launch_kwargs(
                out_json=out,
                site=site,
                existing_storage=out if out.is_file() else None,
            )
            print(
                f"Using persistent Chrome profile at {profile_dir}. Install Google Chrome if launch fails.",
                flush=True,
            )
            context = pw.chromium.launch_persistent_context(str(profile_dir), **launch_kw)
            browser = None

        try:
            if not cdp_default_context:
                context.add_init_script(STEALTH_INIT_SCRIPT)
            page = context.new_page()
            page.goto(args.start_url, wait_until="domcontentloaded", timeout=120_000)
            print(
                "\n>>> Log in in the browser. When you are fully signed in, return here and press Enter "
                "to save storage and exit.\n",
                flush=True,
            )
            input()
            context.storage_state(path=str(out))
            print(f"Saved storage state to: {out}", flush=True)
        finally:
            if not use_user_chrome:
                context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

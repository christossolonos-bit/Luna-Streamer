"""Save a logged-in Playwright session for Luna social sharing (X / Facebook).

Uses the same browser channel, flags, and init script as ``social_playwright_share.py`` so
Google "This browser or app may not be secure" is less likely than with plain Chromium.

From the repo root (same Python venv as Luna):

  pip install playwright
  python -m playwright install chrome
  python scripts/social_playwright_login.py https://x.com D:/path/luna_x.json
  python scripts/social_playwright_login.py https://www.facebook.com D:/path/luna_fb.json

Optional env (same as Luna): LUNA_SOCIAL_CHROME_EXECUTABLE, LUNA_SOCIAL_PLAYWRIGHT_CHANNEL, USER_AGENT, TIMEZONE,
LUNA_SOCIAL_INTERACTIVE_PROFILE_ROOT, LUNA_SOCIAL_INTERACTIVE_CDP_URL (attach to your own Chrome), etc.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Open a stealth Chrome/Edge window, then save storage_state JSON for Luna.",
    )
    ap.add_argument("start_url", help="First page, e.g. https://x.com or https://accounts.google.com")
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
        interactive_login_persistent_launch_kwargs,
    )

    out = args.out_json.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    def _site_from_url(url: str) -> str:
        u = url.lower()
        if "facebook.com" in u:
            return "facebook"
        if "x.com" in u or "twitter.com" in u:
            return "x"
        return "web"

    site = _site_from_url(args.start_url)
    cdp = (os.environ.get("LUNA_SOCIAL_INTERACTIVE_CDP_URL") or "").strip()

    with sync_playwright() as pw:
        if cdp:
            print(f"CDP mode: connecting to {cdp} (Chrome must be running with remote debugging).", flush=True)
            browser = pw.chromium.connect_over_cdp(cdp)
            context = browser.new_context()
            try:
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
                context.close()
                browser.close()
            return 0

        profile_dir, launch_kw = interactive_login_persistent_launch_kwargs(
            out_json=out,
            site=site,
            existing_storage=out if out.is_file() else None,
        )

        print(
            f"Using persistent Chrome profile at {profile_dir} (same stealth flags as Luna key-icon login). "
            "Install Google Chrome if launch fails.",
            flush=True,
        )
        context = pw.chromium.launch_persistent_context(str(profile_dir), **launch_kw)
        try:
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
            context.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

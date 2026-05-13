"""Share new YouTube uploads to X and Facebook using Playwright + saved browser sessions.

Google / X often block bundled Chromium with "This browser or app may not be secure". This module
uses **real Chrome or Edge** (``channel=``) plus light **anti-automation** flags so login and
posting behave more like a normal desktop browser.

Setup (one-time per site):
  pip install playwright
  python -m playwright install chrome
  # Prefer the Luna helper (same stealth settings as posting):
  python scripts/social_playwright_login.py https://x.com D:/path/x_storage.json
  python scripts/social_playwright_login.py https://www.facebook.com D:/path/fb_storage.json
  # Or from the viewer: key icon in the dock sends viewer_social_interactive_login (headed Chrome on the PC running Luna).
  # Optional: LUNA_SOCIAL_X_LOGIN_START_URL / LUNA_SOCIAL_FACEBOOK_LOGIN_START_URL open your profile pages instead of default login URLs.

Env:
  LUNA_SOCIAL_PLAYWRIGHT=1                 Enable automatic share on new observe uploads and manual viewer shares.
  LUNA_SOCIAL_X_STORAGE_STATE=path         JSON from the login helper above.
  LUNA_SOCIAL_FACEBOOK_STORAGE_STATE=path  Same for facebook.com (logged-in session).
  LUNA_SOCIAL_PLAYWRIGHT_HEADLESS=1        Default 1; set 0 to watch the browser (debug).
  LUNA_SOCIAL_PLAYWRIGHT_SHOW_BROWSER=1    If set, always show Chrome for auto/manual share (overrides HEADLESS).
  LUNA_SOCIAL_PLAYWRIGHT_VISIBLE=1         Same as SHOW_BROWSER (alias).
  LUNA_SOCIAL_PLAYWRIGHT_SLOW_MO=0         Milliseconds between Playwright actions (debug).
  LUNA_SOCIAL_PLAYWRIGHT_CHANNEL=chrome    Browser channel: chrome | msedge | chromium (ignored if executable set).
  LUNA_SOCIAL_CHROME_EXECUTABLE=path       Optional full path to chrome.exe (use if channel lookup fails).
  LUNA_SOCIAL_PLAYWRIGHT_USER_AGENT=...    Optional full UA string (otherwise a current Chrome desktop UA).
  LUNA_SOCIAL_PLAYWRIGHT_TIMEZONE=...      Optional IANA tz for context (e.g. America/New_York).
  LUNA_SOCIAL_X_LOGIN_START_URL=...        Optional; first page for key-icon login (default X login flow).
  LUNA_SOCIAL_X_POST_LEGACY_INTENT=1       X shares: use intent URL only (skip home → compose UI flow).
  LUNA_SOCIAL_X_POST_START_URL=...         First page for UI flow (default https://x.com/home).
  LUNA_SOCIAL_X_INTENT_PATH=post           ``post`` (modal ``intent/post``) or ``tweet`` for ``intent/tweet``.
  LUNA_SOCIAL_FACEBOOK_LOGIN_START_URL=... Optional; first page for Facebook key-icon login (default /login).
  LUNA_SOCIAL_FACEBOOK_POST_START_URL=...  Composer flow: open this page first (default: LOGIN URL or facebook.com).
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PREFIX=...  If set, ``{prefix} {title}`` then URL; else a friendly default line from the title.
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_TEMPLATE=...  Overrides prefix; use {title} and {url} (comment only); link is still appended below.
  LUNA_SOCIAL_FACEBOOK_POST_LEGACY_SHARER=1  Use sharer.php popup only (skip profile composer).
  LUNA_SOCIAL_FB_POST_UI_STEP_MS / LUNA_SOCIAL_FB_POST_UI_SETTLE_MS  Optional timeouts for Facebook UI flow.
  LUNA_SOCIAL_INTERACTIVE_EPHEMERAL=1        Key-icon login: use old temp profile (not recommended for Google OAuth on X).
  LUNA_SOCIAL_INTERACTIVE_PROFILE_ROOT=path Optional; persistent Chrome profiles live under ``{root}/x`` and ``{root}/facebook``.
  LUNA_SOCIAL_INTERACTIVE_NO_VIEWPORT=1    Default 1; real window size (omit fixed viewport) during key-icon login.
  LUNA_SOCIAL_INTERACTIVE_USE_SYNTHETIC_UA=1 Force the module default Chrome UA during interactive login (omit unless needed).
  LUNA_SOCIAL_INTERACTIVE_CDP_URL=http://127.0.0.1:9222  Optional; attach to **your** Chrome (remote debugging) instead of Playwright launching one — best chance for “Sign in with Google” on X. Close other Chrome windows or use a dedicated ``--user-data-dir``.

UI selectors change; if posting stops working, update this module or use HEADLESS=0 to inspect.
"""

from __future__ import annotations

import asyncio
import os
import re
import urllib.parse
from pathlib import Path
from typing import Any, Awaitable, Callable

# Injected on every document before site scripts; reduces obvious automation signals.
STEALTH_INIT_SCRIPT = """
(() => {
  try {
    Object.defineProperty(navigator, "webdriver", { get: () => undefined });
    Object.defineProperty(navigator, "languages", { get: () => ["en-US", "en"] });
  } catch (e) {}
  try {
    window.chrome = { runtime: {} };
  } catch (e) {}
})();
"""


def _env_truthy(key: str, *, default: bool = False) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def social_playwright_share_headless() -> bool:
    """Whether auto-share / manual share runs headless. Visible window if SHOW_BROWSER or HEADLESS=0."""
    if _env_truthy("LUNA_SOCIAL_PLAYWRIGHT_SHOW_BROWSER"):
        return False
    if _env_truthy("LUNA_SOCIAL_PLAYWRIGHT_VISIBLE"):
        return False
    return _env_truthy("LUNA_SOCIAL_PLAYWRIGHT_HEADLESS", default=True)


def _resolve_storage_path(env_key: str, *, warn: bool) -> Path | None:
    raw = (os.environ.get(env_key) or "").strip()
    if not raw:
        return None
    p = Path(raw).expanduser()
    if not p.is_file():
        if warn:
            print(f"(social playwright) missing storage file ({env_key}): {p}", flush=True)
        return None
    return p


def social_playwright_configured() -> bool:
    """True when env is on and at least one storage path is configured (file may appear later)."""
    if not _env_truthy("LUNA_SOCIAL_PLAYWRIGHT"):
        return False
    for key in ("LUNA_SOCIAL_X_STORAGE_STATE", "LUNA_SOCIAL_FACEBOOK_STORAGE_STATE"):
        raw = (os.environ.get(key) or "").strip()
        if raw:
            return True
    return False


_share_lock = asyncio.Lock()


def default_playwright_user_agent() -> str:
    custom = (os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_USER_AGENT") or "").strip()
    if custom:
        return custom
    return (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    )


def playwright_browser_channel() -> str | None:
    """Return Playwright ``channel`` name, or None for bundled Chromium."""
    raw = (os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_CHANNEL") or "chrome").strip().lower()
    if raw in ("", "chromium", "default", "bundled"):
        return None
    if raw in ("chrome", "msedge", "chrome-beta", "chrome-dev", "msedge-beta", "msedge-dev"):
        return raw
    return "chrome"


def stealth_browser_launch_kwargs(*, headless: bool, slow_mo: int) -> dict:
    """Keyword args for ``chromium.launch`` / ``launch_persistent_context`` — real browser + fewer automation fingerprints."""
    kwargs: dict = {
        "headless": headless,
        "slow_mo": slow_mo,
        # Playwright adds --enable-automation by default (green border + easier bot heuristics).
        "ignore_default_args": ["--enable-automation"],
        "args": [
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
        ],
    }
    exe = (os.environ.get("LUNA_SOCIAL_CHROME_EXECUTABLE") or "").strip()
    if exe:
        kwargs["executable_path"] = os.path.expandvars(os.path.expanduser(exe))
    else:
        ch = playwright_browser_channel()
        if ch:
            kwargs["channel"] = ch
    return kwargs


def stealth_browser_context_kwargs(
    *,
    storage_state: str | Path | None = None,
    omit_user_agent: bool = False,
) -> dict:
    """Keyword args for ``browser.new_context`` — desktop-like profile."""
    kwargs: dict[str, object] = {
        "viewport": {"width": 1280, "height": 800},
        "locale": "en-US",
        "color_scheme": "light",
        "has_touch": False,
        "is_mobile": False,
    }
    if not omit_user_agent:
        kwargs["user_agent"] = default_playwright_user_agent()
    tz = (os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_TIMEZONE") or "").strip()
    if tz:
        kwargs["timezone_id"] = tz
    if storage_state is not None:
        kwargs["storage_state"] = str(storage_state)
    return kwargs


def interactive_login_chrome_user_data_dir(out_json: Path, site: str) -> Path:
    """Disk-backed Chrome profile for key-icon / CLI login (Google OAuth is stricter on ephemeral profiles)."""
    root = (os.environ.get("LUNA_SOCIAL_INTERACTIVE_PROFILE_ROOT") or "").strip()
    if root:
        return (Path(root).expanduser().resolve() / site)
    return (out_json.parent / f"{out_json.stem}_chrome_profile").resolve()


def interactive_login_persistent_launch_kwargs(
    *,
    out_json: Path,
    site: str,
    existing_storage: Path | None,
) -> tuple[Path, dict[str, Any]]:
    """Merge launch + context options for ``chromium.launch_persistent_context`` (interactive login).

    Session data lives in the on-disk ``user_data_dir``. Playwright Python does not support
    ``storage_state`` on ``launch_persistent_context`` (unlike ``new_context``). JSON is still
    exported on tab close for headless posting. ``existing_storage`` is unused here but kept for a
    stable call signature.
    """
    profile_dir = interactive_login_chrome_user_data_dir(out_json, site)
    profile_dir.mkdir(parents=True, exist_ok=True)
    slow_mo = int((os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_SLOW_MO") or "0").strip() or "0")
    launch = stealth_browser_launch_kwargs(headless=False, slow_mo=slow_mo)
    custom_ua = (os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_USER_AGENT") or "").strip()
    # Real Chrome + matching UA reduces Google / X "automation" friction vs a fixed string that lags the binary.
    omit_ua = not custom_ua and not _env_truthy("LUNA_SOCIAL_INTERACTIVE_USE_SYNTHETIC_UA", default=False)
    ctx = stealth_browser_context_kwargs(storage_state=None, omit_user_agent=omit_ua)
    merged: dict[str, Any] = {**launch, **ctx}
    if _env_truthy("LUNA_SOCIAL_INTERACTIVE_NO_VIEWPORT", default=True):
        merged["no_viewport"] = True
        merged.pop("viewport", None)
    return profile_dir, merged


def interactive_login_start_url(site: str) -> str:
    """First URL when using the viewer key-icon login; override with env for profile/home pages."""
    s = site.strip().lower()
    if s == "x":
        raw = (os.environ.get("LUNA_SOCIAL_X_LOGIN_START_URL") or "").strip()
        return raw or "https://x.com/i/flow/login"
    if s == "facebook":
        raw = (os.environ.get("LUNA_SOCIAL_FACEBOOK_LOGIN_START_URL") or "").strip()
        return raw or "https://www.facebook.com/login/"
    return "https://x.com/i/flow/login"


def _compose_x_text(title: str, video_url: str) -> str:
    t = f"{title.strip()}\n{video_url.strip()}".strip()
    # X free-tier length; long-form X can exceed this — trim safely.
    max_len = int((os.environ.get("LUNA_SOCIAL_X_MAX_CHARS") or "4000").strip() or "4000")
    max_len = max(100, min(max_len, 10000))
    if len(t) > max_len:
        t = t[: max_len - 1] + "…"
    return t


def _x_intent_path_segment() -> str:
    """URL path under ``/intent/`` — X currently uses ``post`` for the overlay composer."""
    raw = (os.environ.get("LUNA_SOCIAL_X_INTENT_PATH") or "post").strip().lower()
    if raw in ("tweet", "twitter", "old", "status"):
        return "tweet"
    return "post"


async def _x_composer_root(page: object) -> object:
    """X often opens the composer in a ``role=dialog`` layer above the feed; scope clicks there."""
    from playwright.async_api import TimeoutError as PWTimeout

    modal = page.locator('[role="dialog"]').filter(has=page.locator('[data-testid="tweetTextarea_0"]')).last
    try:
        await modal.wait_for(state="visible", timeout=12_000)
        return modal
    except PWTimeout:
        pass
    return page


async def _x_click_post_in_composer(page: object) -> bool:
    """Click Post/Tweet in modal or full-page composer. Returns True if a click was sent."""
    from playwright.async_api import TimeoutError as PWTimeout

    root = await _x_composer_root(page)
    selectors = (
        '[data-testid="tweetButtonInline"]',
        '[data-testid="tweetButton"]',
        'button[data-testid="tweetButton"]',
    )
    for sel in selectors:
        loc = root.locator(sel).first
        try:
            if await loc.count() > 0:
                await loc.wait_for(state="visible", timeout=12_000)
                if await loc.is_enabled():
                    await loc.click(timeout=15_000)
                    return True
        except PWTimeout:
            continue
    for name in ("Post", "Tweet"):
        btn = root.get_by_role("button", name=re.compile(f"^{re.escape(name)}$", re.I)).first
        try:
            if await btn.count() > 0 and await btn.is_enabled():
                await btn.click(timeout=15_000)
                return True
        except PWTimeout:
            continue
    return False


async def _post_x_via_intent_url(page: object, title: str, video_url: str) -> None:
    """Open ``intent/post`` (or ``intent/tweet``) with prefilled text; Post sits in a modal above the feed."""
    text = _compose_x_text(title, video_url)
    q = urllib.parse.quote(text, safe="")
    primary = _x_intent_path_segment()
    fallbacks = ("tweet",) if primary == "post" else ("post",)

    for seg in (primary, *fallbacks):
        await page.goto(  # type: ignore[union-attr]
            f"https://x.com/intent/{seg}?text={q}",
            wait_until="domcontentloaded",
            timeout=90_000,
        )
        await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_X_POST_WAIT_MS") or "2800").strip() or "2800"))  # type: ignore[union-attr]
        try:
            await page.locator('[data-testid="tweetTextarea_0"]').first.wait_for(state="visible", timeout=20_000)  # type: ignore[union-attr]
        except Exception:
            continue
        if await _x_click_post_in_composer(page):
            await page.wait_for_timeout(2000)  # type: ignore[union-attr]
            print(f"(social playwright) X: posted (intent/{seg} flow, modal-aware).", flush=True)
            return

    print("(social playwright) X: intent flow — no Post/Tweet button in composer (UI changed?).", flush=True)


async def _post_x_via_compose_ui(page: object, title: str, video_url: str) -> None:
    """Logged-in X: sidebar Post → composer (often ``role=dialog``) → type → Post."""
    from playwright.async_api import TimeoutError as PWTimeout

    text = _compose_x_text(title, video_url)
    start = (os.environ.get("LUNA_SOCIAL_X_POST_START_URL") or "https://x.com/home").strip() or "https://x.com/home"
    step_timeout = int((os.environ.get("LUNA_SOCIAL_X_POST_UI_STEP_MS") or "25000").strip() or "25000")

    await page.goto(start, wait_until="domcontentloaded", timeout=90_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_X_POST_UI_SETTLE_MS") or "800").strip() or "800"))  # type: ignore[union-attr]

    sidebar = page.locator('[data-testid="SideNav_NewTweet_Button"]').first  # type: ignore[union-attr]
    try:
        await sidebar.wait_for(state="visible", timeout=step_timeout)
        await sidebar.click(timeout=15_000)
    except PWTimeout:
        await page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60_000)  # type: ignore[union-attr]

    await page.wait_for_timeout(400)  # type: ignore[union-attr]
    root = await _x_composer_root(page)
    editor = root.locator('[data-testid="tweetTextarea_0"]').first  # type: ignore[union-attr]
    await editor.wait_for(state="visible", timeout=step_timeout)
    try:
        await editor.click(timeout=10_000)
        await editor.fill(text, timeout=30_000)
    except Exception:
        await editor.click(timeout=10_000)
        await editor.press_sequentially(text, delay=5, timeout=120_000)

    for _ in range(90):
        if await _x_click_post_in_composer(page):
            await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_X_POST_WAIT_MS") or "2500").strip() or "2500"))  # type: ignore[union-attr]
            print("(social playwright) X: posted (compose UI flow, modal-aware).", flush=True)
            return
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    raise TimeoutError("X compose: Post button stayed disabled or not found (modal composer?).")


async def _post_x(context: object, title: str, video_url: str) -> None:
    page = await context.new_page()  # type: ignore[union-attr]
    try:
        if _env_truthy("LUNA_SOCIAL_X_POST_LEGACY_INTENT", default=False):
            await _post_x_via_intent_url(page, title, video_url)
            return
        try:
            await _post_x_via_compose_ui(page, title, video_url)
        except Exception as exc:
            print(f"(social playwright) X: compose UI failed ({exc}); trying intent URL.", flush=True)
            await _post_x_via_intent_url(page, title, video_url)
    finally:
        await page.close()


def _compose_fb_share_text(title: str, video_url: str) -> str:
    """First lines: short comment tied to the video; blank line; then the URL (unless template includes {url})."""
    title_clean = (title or "").strip()
    url_clean = (video_url or "").strip()
    tmpl = (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_TEMPLATE") or "").strip()
    if tmpl:
        body = tmpl.replace("{title}", title_clean).replace("{url}", url_clean).strip()
        if "{url}" not in tmpl and url_clean and url_clean not in body:
            body = f"{body}\n\n{url_clean}".strip()
    else:
        prefix = (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PREFIX") or "").strip()
        if prefix:
            comment = f"{prefix} {title_clean}".strip() if title_clean else prefix
        else:
            # Friendly default: context from the video title, then link on its own line.
            if title_clean:
                comment = f"Sharing something I enjoyed — {title_clean}. Give it a watch below."
            else:
                comment = "Sharing a video — link below."
        body = f"{comment}\n\n{url_clean}".strip() if url_clean else comment
    max_len = int((os.environ.get("LUNA_SOCIAL_FB_MAX_CHARS") or "8000").strip() or "8000")
    max_len = max(100, min(max_len, 63206))
    if len(body) > max_len:
        body = body[: max_len - 1] + "…"
    return body


def _facebook_compose_start_url() -> str:
    raw = (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_START_URL") or "").strip()
    if raw:
        return raw
    login = (os.environ.get("LUNA_SOCIAL_FACEBOOK_LOGIN_START_URL") or "").strip()
    if login and "facebook.com" in login.lower():
        return login
    return "https://www.facebook.com/"


async def _post_facebook_via_sharer(page: object, title: str, video_url: str) -> None:
    """Legacy: sharer.php popup with Post/Share in iframe or top frame."""
    from playwright.async_api import TimeoutError as PWTimeout

    u = urllib.parse.quote(video_url.strip(), safe="")
    quote = urllib.parse.quote(title.strip()[:500], safe="")
    await page.goto(  # type: ignore[union-attr]
        f"https://www.facebook.com/sharer/sharer.php?u={u}&quote={quote}&display=popup",
        wait_until="domcontentloaded",
        timeout=120_000,
    )
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_FB_POST_WAIT_MS") or "4000").strip() or "4000"))  # type: ignore[union-attr]

    async def try_click_post(scope: object) -> bool:
        for pattern in (
            re.compile(r"post", re.I),
            re.compile(r"share", re.I),
            re.compile(r"publish", re.I),
        ):
            btn = scope.get_by_role("button", name=pattern).first  # type: ignore[union-attr]
            try:
                if await btn.count() > 0:
                    await btn.click(timeout=20_000)
                    await page.wait_for_timeout(2500)  # type: ignore[union-attr]
                    return True
            except PWTimeout:
                continue
        return False

    if await try_click_post(page):
        print("(social playwright) Facebook: clicked Post/Share (top frame, sharer).", flush=True)
        return

    for fr in page.frames:
        if fr is page.main_frame:
            continue
        try:
            if await try_click_post(fr):
                print("(social playwright) Facebook: clicked Post/Share (iframe, sharer).", flush=True)
                return
        except Exception:
            continue

    print("(social playwright) Facebook: sharer — no Post/Share button found.", flush=True)


async def _fb_dismiss_add_to_post_dialog(page: object) -> None:
    """If the *Add to your post* picker is open, close it so *Create post* (with **Next**) is on top."""
    sheet = page.get_by_role("dialog", name=re.compile(r"add to your post", re.I))
    if await sheet.count() == 0:
        return
    try:
        if not await sheet.first.is_visible():
            return
    except Exception:
        return
    back = sheet.get_by_role("button", name=re.compile(r"^back$", re.I)).first
    try:
        if await back.count() > 0:
            await back.click(timeout=5000)
        else:
            await page.keyboard.press("Escape")
    except Exception:
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass
    await page.wait_for_timeout(450)


async def _post_facebook_via_composer_ui(page: object, title: str, video_url: str) -> None:
    """Facebook *Create post*: story box, comment + URL, wait for link in composer / preview, footer **Next** only, then **Post**."""

    async def _fb_story_composer(dlg: object) -> object:
        """Main composer only — ``aria-placeholder`` *What's on your mind* / *on your mind*, not *Add to your post*."""
        by_ph = dlg.locator(
            '[role="textbox"][contenteditable="true"][aria-placeholder*="on your mind"]'
        ).first
        if await by_ph.count() > 0:
            return by_ph
        by_ph2 = dlg.locator('[role="textbox"][contenteditable="true"][aria-placeholder*="What"]').first
        if await by_ph2.count() > 0:
            return by_ph2
        tb = dlg.get_by_role("textbox", name=re.compile(r"on your mind|what.?s on", re.I)).first  # type: ignore[union-attr]
        if await tb.count() > 0:
            return tb
        xp_lex = (
            "xpath=.//*[@data-lexical-editor='true' and @role='textbox' and @contenteditable='true' "
            "and not(ancestor::*[contains(@aria-label, \"Add to your post\")])]"
        )
        loc = dlg.locator(xp_lex).first  # type: ignore[union-attr]
        if await loc.count() > 0:
            return loc
        return dlg.locator('[data-lexical-editor="true"][contenteditable="true"][role="textbox"]').first  # type: ignore[union-attr]

    from playwright.async_api import TimeoutError as PWTimeout

    text = _compose_fb_share_text(title, video_url)
    start = _facebook_compose_start_url()
    step_timeout = int((os.environ.get("LUNA_SOCIAL_FB_POST_UI_STEP_MS") or "25000").strip() or "25000")
    settle = int((os.environ.get("LUNA_SOCIAL_FB_POST_UI_SETTLE_MS") or "1200").strip() or "1200")

    await page.goto(start, wait_until="domcontentloaded", timeout=120_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(settle)  # type: ignore[union-attr]

    trigger = page.get_by_text(re.compile(r"What.?s on your mind", re.I)).first  # type: ignore[union-attr]
    await trigger.wait_for(state="visible", timeout=step_timeout)
    await trigger.scroll_into_view_if_needed()  # type: ignore[union-attr]
    await trigger.click(timeout=15_000)

    await page.wait_for_timeout(800)  # type: ignore[union-attr]
    await _fb_dismiss_add_to_post_dialog(page)
    try:
        # Prefer the **Create post** sheet (`.first` — `.last` can be *Add to your post* on top).
        dialog = page.get_by_role("dialog", name=re.compile(r"create post", re.I)).first  # type: ignore[union-attr]
        await dialog.wait_for(state="visible", timeout=step_timeout)
    except PWTimeout:
        dialog = page.locator('[role="dialog"]').filter(  # type: ignore[union-attr]
            has_text=re.compile(r"Create post|on your mind|your mind", re.I)
        ).first
        await dialog.wait_for(state="visible", timeout=step_timeout)

    await _fb_dismiss_add_to_post_dialog(page)

    # Step 1 — story composer, then nice comment + URL (see ``_compose_fb_share_text``).
    editor = await _fb_story_composer(dialog)
    await editor.wait_for(state="visible", timeout=step_timeout)
    await editor.scroll_into_view_if_needed()  # type: ignore[union-attr]
    await editor.click(timeout=10_000)
    try:
        await editor.press("Control+a")  # type: ignore[union-attr]
    except Exception:
        try:
            await editor.press("Meta+a")  # type: ignore[union-attr]
        except Exception:
            pass
    await editor.press("Backspace")  # type: ignore[union-attr]
    try:
        await editor.fill(text, timeout=45_000)  # type: ignore[union-attr]
    except Exception:
        await editor.press_sequentially(text, delay=8, timeout=120_000)  # type: ignore[union-attr]

    await page.wait_for_timeout(500)  # type: ignore[union-attr]
    await _fb_dismiss_add_to_post_dialog(page)

    # Wait until the share is actually in the sheet (text + unfurl); **Next** stays disabled until then.
    # Do not interact with *Add to your post* icon row — only the primary footer control below it.
    url_s = (video_url or "").strip()
    if url_s:
        host = (urllib.parse.urlparse(url_s).hostname or "").lower()
        if host:
            try:
                await dialog.locator(f'a[href*="{host}"]').first.wait_for(  # type: ignore[union-attr]
                    state="visible", timeout=min(step_timeout, 30_000)
                )
            except PWTimeout:
                pass
        tail = url_s.rsplit("/", 1)[-1][:48] if "/" in url_s else url_s[:48]
        for _ in range(80):
            try:
                body_txt = await editor.inner_text()  # type: ignore[union-attr]
            except Exception:
                body_txt = ""
            if url_s in body_txt or (tail and tail in body_txt):
                break
            await page.wait_for_timeout(200)  # type: ignore[union-attr]

    await _fb_dismiss_add_to_post_dialog(page)

    # Step 2 — **only** the blue footer **Next**: ``div``/``role="button"`` + ``aria-label="Next"`` (not inner ``span``, not toolbar).
    next_btn = dialog.locator('[role="button"][aria-label="Next"]').first  # type: ignore[union-attr]
    if await next_btn.count() == 0:
        next_btn = dialog.get_by_role("button", name="Next", exact=True)  # type: ignore[union-attr]
    await next_btn.wait_for(state="visible", timeout=step_timeout)
    await next_btn.scroll_into_view_if_needed()  # type: ignore[union-attr]
    for _ in range(80):
        if await next_btn.is_enabled():
            break
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    await next_btn.click(timeout=15_000)

    # Let **Post settings** mount; avoid ``[role=dialog].last`` — **Create post** can still be last in the tree.
    await page.wait_for_timeout(1200)  # type: ignore[union-attr]

    # Step 3 — **Post settings** sheet only, then blue footer **Post** (not **Save**, not **Back** / compose).
    post_sheet = page.get_by_role("dialog", name=re.compile(r"post settings", re.I)).first  # type: ignore[union-attr]
    try:
        await post_sheet.wait_for(state="visible", timeout=step_timeout)
    except PWTimeout:
        post_sheet = page.locator('[role="dialog"]').filter(  # type: ignore[union-attr]
            has_text=re.compile(r"Post settings|Post audience|Boost post", re.I)
        ).first
        await post_sheet.wait_for(state="visible", timeout=step_timeout)

    # Same pattern as **Next**: ``role="button"`` + ``aria-label="Post"`` on the primary control (not inner ``span``).
    post_btn = post_sheet.locator('[role="button"][aria-label="Post"]').first  # type: ignore[union-attr]
    if await post_btn.count() == 0:
        post_btn = post_sheet.get_by_role("button", name="Post", exact=True).first  # type: ignore[union-attr]
    await post_btn.wait_for(state="visible", timeout=step_timeout)
    await post_btn.scroll_into_view_if_needed()  # type: ignore[union-attr]
    for _ in range(80):
        if await post_btn.is_enabled():
            break
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    await post_btn.click(timeout=20_000)
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_FB_POST_WAIT_MS") or "4000").strip() or "4000"))  # type: ignore[union-attr]
    print("(social playwright) Facebook: posted (steps: textbox → Next → Post).", flush=True)


async def _post_facebook(context: object, title: str, video_url: str) -> None:
    page = await context.new_page()  # type: ignore[union-attr]
    try:
        if _env_truthy("LUNA_SOCIAL_FACEBOOK_POST_LEGACY_SHARER", default=False):
            await _post_facebook_via_sharer(page, title, video_url)
            return
        try:
            await _post_facebook_via_composer_ui(page, title, video_url)
        except Exception as exc:
            print(f"(social playwright) Facebook: composer UI failed ({exc}); trying sharer.", flush=True)
            await _post_facebook_via_sharer(page, title, video_url)
    finally:
        await page.close()


async def share_new_youtube_upload(*, title: str, video_url: str) -> None:
    """Post ``title`` + ``video_url`` to X and/or Facebook using configured storage states."""
    x_path = _resolve_storage_path("LUNA_SOCIAL_X_STORAGE_STATE", warn=True)
    fb_path = _resolve_storage_path("LUNA_SOCIAL_FACEBOOK_STORAGE_STATE", warn=True)
    if x_path is None and fb_path is None:
        return

    async with _share_lock:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            print(
                "(social playwright) Install: pip install playwright && python -m playwright install chrome",
                flush=True,
            )
            return

        headless = social_playwright_share_headless()
        slow_mo = int((os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_SLOW_MO") or "0").strip() or "0")

        try:
            async with async_playwright() as p:
                launch_kw = stealth_browser_launch_kwargs(headless=headless, slow_mo=slow_mo)
                browser = await p.chromium.launch(**launch_kw)
                try:
                    if x_path is not None:
                        ctx = await browser.new_context(
                            **stealth_browser_context_kwargs(storage_state=x_path)
                        )
                        await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                        try:
                            await _post_x(ctx, title, video_url)
                        finally:
                            await ctx.close()
                    if fb_path is not None:
                        ctx = await browser.new_context(
                            **stealth_browser_context_kwargs(storage_state=fb_path)
                        )
                        await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                        try:
                            await _post_facebook(ctx, title, video_url)
                        finally:
                            await ctx.close()
                finally:
                    await browser.close()
        except Exception as exc:
            print(f"(social playwright) browser run failed: {exc}", flush=True)


async def run_interactive_social_login(
    *,
    site: str,
    out_path: Path,
    broadcast: Callable[[str], Awaitable[None]],
) -> None:
    """Open a **visible** Chrome window for manual X/Facebook login, then save ``storage_state`` to ``out_path``.

    A second **blank** tab stays open while you use the first tab: closing only the login tab used to tear down
    Chromium before ``storage_state`` could run (no JSON written). After save, Luna closes the blank tab.
    """
    from playwright.async_api import TimeoutError as PWTimeout

    s = site.strip().lower()
    if s in ("twitter", "t", "x"):
        s = "x"
    elif s in ("facebook", "fb"):
        s = "facebook"
    else:
        await broadcast("Social login: use site x or facebook.")
        return

    start_url = interactive_login_start_url(s)

    out = out_path.expanduser().resolve()
    out.parent.mkdir(parents=True, exist_ok=True)
    existing = out if out.is_file() else None

    async with _share_lock:
        ctx = None
        browser = None
        try:
            try:
                from playwright.async_api import async_playwright
            except ImportError:
                await broadcast("Social login: pip install playwright && python -m playwright install chrome")
                return

            cdp_url = (os.environ.get("LUNA_SOCIAL_INTERACTIVE_CDP_URL") or "").strip()
            slow_mo = int((os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_SLOW_MO") or "0").strip() or "0")
            use_ephemeral = _env_truthy("LUNA_SOCIAL_INTERACTIVE_EPHEMERAL", default=False)

            profile_dir: Path | None = None
            merged_persistent_kw: dict[str, Any] | None = None
            if not cdp_url and not use_ephemeral:
                profile_dir, merged_persistent_kw = interactive_login_persistent_launch_kwargs(
                    out_json=out,
                    site=s,
                    existing_storage=existing,
                )

            if cdp_url:
                await broadcast(
                    f"Social login ({s}): CDP attach → {cdp_url} (Chrome must already be running with that port). "
                    f"Saving session to: {out}"
                )
            else:
                extra = f" On-disk Chrome profile: {profile_dir}" if profile_dir is not None else ""
                x_google = ""
                if s == "x":
                    x_google = (
                        " **On X:** “Sign in with Google” is usually blocked in Playwright-launched Chrome — "
                        "use **password / phone / Apple**, or set **LUNA_SOCIAL_INTERACTIVE_CDP_URL** and log in via your own Chrome."
                    )
                await broadcast(
                    f"Social login ({s}): opening Chrome — sign in, then **close the login tab** when done "
                    f"(Luna opens a blank second tab so cookies save reliably). Saving to: {out}.{extra}{x_google}"
                )
            async with async_playwright() as p:
                if cdp_url:
                    browser = await p.chromium.connect_over_cdp(cdp_url)
                    ctx = await browser.new_context()
                elif use_ephemeral:
                    launch_kw = stealth_browser_launch_kwargs(headless=False, slow_mo=slow_mo)
                    browser = await p.chromium.launch(**launch_kw)
                    ctx = await browser.new_context(
                        **stealth_browser_context_kwargs(storage_state=existing, omit_user_agent=False)
                    )
                else:
                    assert profile_dir is not None and merged_persistent_kw is not None
                    ctx = await p.chromium.launch_persistent_context(
                        str(profile_dir), **merged_persistent_kw
                    )
                await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                page = await ctx.new_page()
                await page.goto(start_url, wait_until="domcontentloaded", timeout=120_000)
                keeper = None
                try:
                    keeper = await ctx.new_page()
                    await keeper.goto("about:blank", wait_until="domcontentloaded", timeout=15_000)
                except Exception:
                    keeper = None
                    print(
                        "(social playwright) interactive login: could not open keeper tab; "
                        "if cookies are not saved, close only the login tab (not Exit) or try again.",
                        flush=True,
                    )
                await broadcast(
                    "Social login: use the **first tab** to sign in. When done, **close that tab** "
                    "(a blank second tab keeps Chrome alive so Luna can save cookies). "
                    "Wait for “saved” in chat before using File→Exit."
                )
                try:
                    await page.wait_for_event("close", timeout=3_600_000)
                except PWTimeout:
                    await broadcast("Social login: timed out after 1 hour — closing without saving.")
                    return
                try:
                    await ctx.storage_state(path=str(out))
                    await broadcast(
                        f"Social login: saved to {out}. "
                        f"Ensure LUNA_SOCIAL_{'FACEBOOK' if s == 'facebook' else 'X'}_STORAGE_STATE matches this path; restart Luna if you changed it."
                    )
                except Exception as exc:
                    await broadcast(f"Social login: could not save storage ({exc}).")
                finally:
                    if keeper is not None:
                        try:
                            if not keeper.is_closed():
                                await keeper.close()
                        except Exception:
                            pass
        except Exception as exc:
            await broadcast(f"Social login: {exc}")
        finally:
            if ctx is not None:
                try:
                    await ctx.close()
                except Exception:
                    pass
            if browser is not None:
                try:
                    await browser.close()
                except Exception:
                    pass

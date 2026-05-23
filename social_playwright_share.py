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
  python scripts/social_playwright_login.py https://www.youtube.com D:/path/luna_youtube.json
  # Or from the viewer: Settings → Social login sends viewer_social_interactive_login (headed Chrome on the PC running Luna).
  # Optional: LUNA_SOCIAL_X_LOGIN_START_URL / LUNA_SOCIAL_FACEBOOK_LOGIN_START_URL open your profile pages instead of default login URLs.

Env:
  LUNA_SOCIAL_PLAYWRIGHT=1                 Enable automatic share on new observe uploads and manual viewer shares.
  LUNA_SOCIAL_X_STORAGE_STATE=path         JSON from the login helper above.
  LUNA_SOCIAL_FACEBOOK_STORAGE_STATE=path  Same for facebook.com (logged-in session).
  LUNA_SOCIAL_YOUTUBE_STORAGE_STATE=path   Saved Chrome session for Luna's YouTube account (comment on videos).
  LUNA_SOCIAL_YOUTUBE_COMMENT=1            Post to YouTube's comment box when storage is set (set 0 to disable).
  LUNA_SOCIAL_YOUTUBE_LOGIN_START_URL=...  Key-icon login first page (default https://www.youtube.com).
  LUNA_SOCIAL_YOUTUBE_COMMENT_PROMPT=...   Optional LLM user prompt; {title} {url} {transcript}.
  LUNA_SOCIAL_YOUTUBE_COMMENT_NUM_PREDICT=80
  LUNA_SOCIAL_YOUTUBE_COMMENT_MAX_CHARS=900
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
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PREFIX=...  If set, ``{prefix} {title}`` then URL; else LLM comment (or friendly default).
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_TEMPLATE=...  Overrides LLM/prefix; use {title} and {url} (comment only); link is still appended below.
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_LLM=1       Default on when no template/prefix; uses OLLAMA_MODEL / LUNA_CHAT_MODEL + TWITCH_SYSTEM.
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PROMPT=...  Optional user prompt; ``{title}`` and ``{url}`` substituted (URL still appended separately unless in template).
  LUNA_SOCIAL_FACEBOOK_POST_COMMENT_NUM_PREDICT=120  Max tokens for the LLM comment line.
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
    if s in ("youtube", "yt"):
        raw = (os.environ.get("LUNA_SOCIAL_YOUTUBE_LOGIN_START_URL") or "").strip()
        return raw or "https://www.youtube.com"
    return "https://x.com/i/flow/login"


def default_youtube_storage_path() -> Path:
    """Default session JSON next to other Luna data (Settings → YouTube login)."""
    return (Path(__file__).resolve().parent / "data" / "luna_youtube.json").resolve()


def youtube_comment_storage_path(*, warn: bool = False) -> Path | None:
    raw = (os.environ.get("LUNA_SOCIAL_YOUTUBE_STORAGE_STATE") or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return p
        if warn:
            print(
                f"(social playwright) missing YouTube storage file (LUNA_SOCIAL_YOUTUBE_STORAGE_STATE): {p}",
                flush=True,
            )
        return None
    default = default_youtube_storage_path()
    if default.is_file():
        return default
    return None


def youtube_comment_posting_requested() -> bool:
    raw = (os.environ.get("LUNA_SOCIAL_YOUTUBE_COMMENT") or "").strip().lower()
    return raw not in ("0", "false", "no", "off")


def youtube_comment_posting_enabled() -> bool:
    """True when a saved YouTube session exists and posting is not disabled."""
    if not youtube_comment_posting_requested():
        return False
    return youtube_comment_storage_path(warn=False) is not None


def youtube_comment_setup_hint() -> str:
    default = default_youtube_storage_path()
    env_hint = (
        os.environ.get("LUNA_SOCIAL_YOUTUBE_STORAGE_STATE") or str(default)
    ).strip()
    return (
        "YouTube comment needs a saved login. Set "
        f"LUNA_SOCIAL_YOUTUBE_STORAGE_STATE={env_hint} in .env, restart Luna, then "
        "Settings → YouTube login (sign in, close tab when chat says saved). "
        "Or: python scripts/social_playwright_login.py https://www.youtube.com "
        f'"{env_hint}"'
    )


def clamp_youtube_public_comment(text: str) -> str:
    t = (text or "").strip()
    max_len = _yt_comment_max_chars()
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"
    return t


def _yt_comment_max_chars() -> int:
    raw = (os.environ.get("LUNA_SOCIAL_YOUTUBE_COMMENT_MAX_CHARS") or "900").strip() or "900"
    try:
        return max(80, min(int(raw), 9500))
    except ValueError:
        return 900


def _yt_llm_comment_user_prompt(
    title: str, video_url: str, transcript: str, *, context_source: str = ""
) -> str:
    custom = (os.environ.get("LUNA_SOCIAL_YOUTUBE_COMMENT_PROMPT") or "").strip()
    title_clean = (title or "").strip() or "this video"
    src = (context_source or "video context").strip()
    if custom:
        return (
            custom.replace("{title}", title_clean)
            .replace("{url}", (video_url or "").strip())
            .replace("{transcript}", (transcript or "").strip())
            .replace("{context}", (transcript or "").strip())
            .replace("{context_source}", src)
        )
    snippet = (transcript or "").strip()
    if len(snippet) > 2500:
        snippet = snippet[:2499] + "…"
    return (
        "Write a short public YouTube comment (1–2 sentences) reacting to this video.\n"
        f"Video title: {title_clean}\n"
        f"Context ({src}):\n{snippet or '(minimal metadata)'}\n\n"
        "Write in first person as the channel host. Sound natural and specific, not spammy.\n"
        "Do NOT include URLs, hashtags, markdown, or labels like \"Comment:\".\n"
        "Output only the comment text."
    )


def _sanitize_yt_public_comment(raw: str, video_url: str) -> str:
    from ollama_client import strip_think_blocks

    text = strip_think_blocks((raw or "").strip())
    text = re.sub(r"^[\"'`]+|[\"'`]+$", "", text).strip()
    url_clean = (video_url or "").strip()
    if url_clean:
        text = text.replace(url_clean, "").strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    max_len = _yt_comment_max_chars()
    if len(text) > max_len:
        text = text[: max_len - 1].rstrip() + "…"
    return text.strip()


def _generate_yt_public_comment_llm_sync(
    title: str, video_url: str, transcript: str, *, context_source: str = ""
) -> str | None:
    from ollama_client import build_client, chat_request_kwargs

    model = (os.environ.get("LUNA_CHAT_MODEL") or os.environ.get("OLLAMA_MODEL") or "").strip()
    if not model:
        return None
    messages = [
        {"role": "system", "content": _fb_llm_comment_system_prompt()},
        {
            "role": "user",
            "content": _yt_llm_comment_user_prompt(
                title, video_url, transcript, context_source=context_source
            ),
        },
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    predict_raw = (os.environ.get("LUNA_SOCIAL_YOUTUBE_COMMENT_NUM_PREDICT") or "80").strip() or "80"
    try:
        predict = max(24, int(predict_raw))
    except ValueError:
        predict = 80
    opts = dict(kwargs.get("options") or {})
    opts["num_predict"] = predict
    kwargs["options"] = opts
    client = build_client()
    response = client.chat(**kwargs)
    comment = _sanitize_yt_public_comment(response.message.content or "", video_url)
    return comment or None


async def generate_youtube_public_comment(
    *, title: str, video_url: str, transcript: str, context_source: str = ""
) -> str | None:
    try:
        return await asyncio.to_thread(
            _generate_yt_public_comment_llm_sync,
            title,
            video_url,
            transcript,
            context_source=context_source,
        )
    except Exception as exc:
        print(f"(social playwright) YouTube comment LLM failed ({exc}).", flush=True)
        return None


async def _yt_dismiss_consent(page: object) -> None:
    """Best-effort dismiss of cookie / consent overlays."""
    for pattern in (
        re.compile(r"accept all", re.I),
        re.compile(r"i agree", re.I),
        re.compile(r"reject all", re.I),
    ):
        try:
            btn = page.get_by_role("button", name=pattern).first  # type: ignore[union-attr]
            if await btn.count() > 0:
                await btn.click(timeout=4000)
                await page.wait_for_timeout(400)  # type: ignore[union-attr]
                return
        except Exception:
            continue


async def _yt_scroll_to_comments(page: object) -> None:
    from playwright.async_api import TimeoutError as PWTimeout

    try:
        comments = page.locator("#comments").first  # type: ignore[union-attr]
        await comments.wait_for(state="attached", timeout=25_000)
        await comments.scroll_into_view_if_needed(timeout=20_000)
    except PWTimeout:
        await page.evaluate("window.scrollBy(0, Math.min(900, window.innerHeight))")  # type: ignore[union-attr]
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_YT_COMMENT_SETTLE_MS") or "1200").strip() or "1200"))  # type: ignore[union-attr]


def _yt_comment_editor_locator(page: object) -> object:
    """``div#contenteditable-root`` inside ``ytd-commentbox`` (locale-agnostic)."""
    return page.locator(  # type: ignore[union-attr]
        "ytd-commentbox div#contenteditable-root[contenteditable='true']"
    ).first


async def _yt_open_comment_composer(page: object) -> object:
    """Focus the public comment field under the video (``#contenteditable-root``)."""
    from playwright.async_api import TimeoutError as PWTimeout

    await _yt_scroll_to_comments(page)
    editor = _yt_comment_editor_locator(page)

    # Signed-in layout: the Lexical/contenteditable box is already in the comment thread header.
    try:
        await editor.wait_for(state="visible", timeout=15_000)
        await editor.scroll_into_view_if_needed()
        await editor.click(timeout=12_000)
        await page.wait_for_timeout(400)  # type: ignore[union-attr]
        return editor
    except PWTimeout:
        pass

    # Collapsed placeholder (some layouts / not yet focused).
    for sel in (
        "ytd-comment-simplebox-renderer #placeholder-area",
        "ytd-comment-simplebox-renderer #simplebox-placeholder",
        "#placeholder-area",
    ):
        loc = page.locator(sel).first  # type: ignore[union-attr]
        try:
            if await loc.count() == 0:
                continue
            await loc.scroll_into_view_if_needed()
            await loc.click(timeout=12_000)
            await page.wait_for_timeout(600)  # type: ignore[union-attr]
            await editor.wait_for(state="visible", timeout=12_000)
            await editor.click(timeout=10_000)
            return editor
        except Exception:
            continue
    raise PWTimeout(
        "YouTube comment editor (#contenteditable-root in ytd-commentbox) not found — sign in?"
    )


async def _yt_write_contenteditable(page: object, editor: object, text: str) -> None:
    """Type into YouTube's ``#contenteditable-root`` (``fill`` alone often leaves Comment disabled)."""
    await editor.click(timeout=10_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(250)  # type: ignore[union-attr]
    for key in ("Control+a", "Meta+a"):
        try:
            await page.keyboard.press(key)
        except Exception:
            pass
    await page.keyboard.press("Backspace")
    delay = int((os.environ.get("LUNA_SOCIAL_YT_COMMENT_TYPE_DELAY_MS") or "12").strip() or "12")
    blob = (text or "").strip()
    if not blob:
        return
    try:
        await editor.press_sequentially(blob, delay=delay, timeout=180_000)  # type: ignore[union-attr]
    except Exception:
        await page.keyboard.type(blob, delay=delay)  # type: ignore[union-attr]
    await page.wait_for_timeout(600)  # type: ignore[union-attr]
    need = max(8, min(len(blob), 24))
    try:
        got = (await editor.inner_text() or "").strip()  # type: ignore[union-attr]
    except Exception:
        got = ""
    if len(got) >= need:
        return
    await editor.click(timeout=5000)  # type: ignore[union-attr]
    await page.keyboard.type(blob, delay=delay)  # type: ignore[union-attr]


async def _yt_type_and_submit_comment(page: object, editor: object, comment: str) -> None:
    from playwright.async_api import TimeoutError as PWTimeout

    await _yt_write_contenteditable(page, editor, comment)
    await page.wait_for_timeout(500)  # type: ignore[union-attr]

    # Submit lives in the same ytd-commentbox footer (#submit-button); label varies by locale.
    box = page.locator("ytd-commentbox").first  # type: ignore[union-attr]
    submit_selectors = (
        "ytd-button-renderer#submit-button:not([hidden]) button",
        "#submit-button:not([hidden]) button",
        "ytd-button-renderer#submit-button button",
    )
    for sel in submit_selectors:
        btn = box.locator(sel).first  # type: ignore[union-attr]
        try:
            if await btn.count() == 0:
                continue
            await btn.wait_for(state="visible", timeout=10_000)
            for _ in range(50):
                if await btn.is_enabled():
                    break
                await page.wait_for_timeout(200)  # type: ignore[union-attr]
            await btn.click(timeout=15_000)
            await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_YT_COMMENT_POST_WAIT_MS") or "3000").strip() or "3000"))  # type: ignore[union-attr]
            return
        except PWTimeout:
            continue
    # Greek: Σχόλιο, English: Comment, etc.
    named = box.get_by_role("button", name=re.compile(r"comment|σχόλ|kommentar|coment", re.I)).first  # type: ignore[union-attr]
    await named.wait_for(state="visible", timeout=10_000)
    for _ in range(50):
        if await named.is_enabled():
            break
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    await named.click(timeout=15_000)
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_YT_COMMENT_POST_WAIT_MS") or "3000").strip() or "3000"))  # type: ignore[union-attr]


async def _post_youtube_comment_on_page(page: object, video_url: str, comment: str) -> None:
    from youtube_audio import extract_video_id

    vid = extract_video_id(video_url)
    watch = video_url.strip()
    if vid and "watch" not in watch.lower():
        watch = f"https://www.youtube.com/watch?v={vid}"
    await page.goto(watch, wait_until="domcontentloaded", timeout=120_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_YT_COMMENT_PAGE_MS") or "2500").strip() or "2500"))  # type: ignore[union-attr]
    await _yt_dismiss_consent(page)
    editor = await _yt_open_comment_composer(page)
    await _yt_type_and_submit_comment(page, editor, comment)
    print(f"(social playwright) YouTube: posted comment on {watch}", flush=True)


async def post_youtube_video_comment(*, video_url: str, comment: str) -> tuple[bool, str]:
    """Post ``comment`` on ``video_url`` using Luna's saved YouTube session (Playwright + Chrome)."""
    text = clamp_youtube_public_comment(comment)
    if not text:
        return False, "YouTube comment: empty text."
    yt_path = youtube_comment_storage_path(warn=True)
    if yt_path is None:
        return False, youtube_comment_setup_hint()

    print(
        f"(social playwright) YouTube: opening Chrome to post comment on {video_url.strip()[:80]}…",
        flush=True,
    )

    async with _share_lock:
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            return False, "YouTube comment: pip install playwright && python -m playwright install chrome"

        headless = social_playwright_share_headless()
        slow_mo = int((os.environ.get("LUNA_SOCIAL_PLAYWRIGHT_SLOW_MO") or "0").strip() or "0")
        try:
            async with async_playwright() as p:
                launch_kw = stealth_browser_launch_kwargs(headless=headless, slow_mo=slow_mo)
                browser = await p.chromium.launch(**launch_kw)
                try:
                    ctx = await browser.new_context(
                        **stealth_browser_context_kwargs(storage_state=yt_path)
                    )
                    await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                    page = await ctx.new_page()
                    try:
                        await _post_youtube_comment_on_page(page, video_url, text)
                    finally:
                        await page.close()
                        await ctx.close()
                finally:
                    await browser.close()
        except Exception as exc:
            print(f"(social playwright) YouTube comment failed: {exc}", flush=True)
            return False, f"YouTube comment failed: {exc}"
    return True, "YouTube comment posted."


async def generate_and_post_youtube_video_comment(
    *,
    video_url: str,
    title: str,
    transcript: str,
    context_source: str = "",
) -> tuple[bool, str]:
    """LLM-write a public comment from the same video context as !explain, then post via Playwright."""
    comment = await generate_youtube_public_comment(
        title=title,
        video_url=video_url,
        transcript=transcript,
        context_source=context_source,
    )
    if not comment:
        return False, "YouTube comment: could not generate text (check Ollama model)."
    preview = comment[:120] + ("…" if len(comment) > 120 else "")
    print(f"(social playwright) YouTube comment (LLM): {preview}", flush=True)
    return await post_youtube_video_comment(video_url=video_url, comment=comment)


def live_announce_image_path() -> Path | None:
    from live_social_share import live_announce_image_path as _path

    return _path()


async def _playwright_attach_image(scope: object, image_path: Path) -> bool:
    """Attach a local image to an open X/Facebook composer via ``input[type=file]``."""
    if not image_path.is_file():
        return False
    try:
        inputs = scope.locator('input[type="file"]')  # type: ignore[union-attr]
        n = await inputs.count()
        for i in range(n):
            inp = inputs.nth(i)
            try:
                await inp.set_input_files(str(image_path), timeout=30_000)
                return True
            except Exception:
                continue
    except Exception as exc:
        print(f"(social playwright) image attach failed: {exc}", flush=True)
    return False


async def _attach_image_x_composer(page: object, image_path: Path | None) -> None:
    if image_path is None:
        return
    root = await _x_composer_root(page)
    if await _playwright_attach_image(root, image_path):
        await page.wait_for_timeout(1500)  # type: ignore[union-attr]
        print("(social playwright) X: image attached.", flush=True)


async def _attach_image_fb_dialog(dialog: object, page: object, image_path: Path | None) -> None:
    if image_path is None:
        return
    from playwright.async_api import TimeoutError as PWTimeout

    for label in ("Photo/video", "Photo/Video", "Add photos"):
        btn = dialog.get_by_role("button", name=re.compile(re.escape(label), re.I)).first  # type: ignore[union-attr]
        try:
            if await btn.count() > 0:
                await btn.click(timeout=10_000)
                break
        except PWTimeout:
            continue
    await page.wait_for_timeout(600)  # type: ignore[union-attr]
    if await _playwright_attach_image(dialog, image_path) or await _playwright_attach_image(page, image_path):
        await page.wait_for_timeout(2000)  # type: ignore[union-attr]
        print("(social playwright) Facebook: image attached.", flush=True)


def _live_invite_uses_explicit_template() -> bool:
    return bool((os.environ.get("LUNA_SOCIAL_LIVE_INVITE_TEMPLATE") or "").strip())


def _live_invite_llm_enabled() -> bool:
    if _live_invite_uses_explicit_template():
        return False
    return _env_truthy("LUNA_SOCIAL_LIVE_INVITE_LLM", default=True)


def _live_invite_llm_user_prompt(platform: str, title: str, stream_url: str) -> str:
    custom = (os.environ.get("LUNA_SOCIAL_LIVE_INVITE_PROMPT") or "").strip()
    plat = (platform or "live").strip()
    title_clean = (title or "").strip() or "Live stream"
    url_clean = (stream_url or "").strip()
    if custom:
        return (
            custom.replace("{platform}", plat)
            .replace("{title}", title_clean)
            .replace("{url}", url_clean)
        )
    return (
        "Write a short, cute go-live invitation (1–3 sentences) for social media.\n"
        f"Platform: {plat}\n"
        f"Stream title: {title_clean}\n"
        "Voice: Luna, a playful wolf-girl VTuber — warm, bubbly, a little mischievous; "
        "mention Viktor (vampire co-host) if it fits naturally.\n"
        "Invite people to join live. Do NOT include the URL, hashtags, or markdown.\n"
        "Output only the post text."
    )


def _generate_live_invite_comment_llm_sync(platform: str, title: str, stream_url: str) -> str | None:
    from ollama_client import build_client, chat_request_kwargs, strip_think_blocks

    model = (os.environ.get("LUNA_CHAT_MODEL") or os.environ.get("OLLAMA_MODEL") or "").strip()
    if not model:
        return None
    messages = [
        {"role": "system", "content": _fb_llm_comment_system_prompt()},
        {"role": "user", "content": _live_invite_llm_user_prompt(platform, title, stream_url)},
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    predict_raw = (os.environ.get("LUNA_SOCIAL_LIVE_INVITE_NUM_PREDICT") or "100").strip() or "100"
    try:
        predict = max(32, int(predict_raw))
    except ValueError:
        predict = 100
    opts = dict(kwargs.get("options") or {})
    opts["num_predict"] = predict
    kwargs["options"] = opts
    client = build_client()
    response = client.chat(**kwargs)
    comment = _sanitize_fb_llm_comment(response.message.content or "", stream_url)
    return strip_think_blocks(comment).strip() or None


async def compose_live_share_text_async(platform: str, title: str, stream_url: str) -> str:
    """Cute invitation body + stream URL on its own line (for X / Facebook live posts)."""
    if _live_invite_uses_explicit_template():
        tmpl = (os.environ.get("LUNA_SOCIAL_LIVE_INVITE_TEMPLATE") or "").strip()
        plat = (platform or "live").strip()
        body = (
            tmpl.replace("{platform}", plat)
            .replace("{title}", (title or "").strip())
            .replace("{url}", (stream_url or "").strip())
        )
        return _clamp_fb_share_body(body)
    comment: str | None = None
    if _live_invite_llm_enabled():
        try:
            comment = await asyncio.to_thread(
                _generate_live_invite_comment_llm_sync, platform, title, stream_url
            )
        except Exception as exc:
            print(f"(social playwright) live invite LLM failed ({exc}); using fallback.", flush=True)
    if not comment:
        plat = (platform or "live").strip().title()
        title_clean = (title or "").strip()
        comment = (
            f"We're live on {plat}! Luna & Viktor would love to see you — "
            f"{title_clean}." if title_clean else f"We're live on {plat}! Come say hi to Luna & Viktor 💫"
        )
    url_clean = (stream_url or "").strip()
    body = f"{comment}\n\n{url_clean}".strip() if url_clean else comment
    return _clamp_fb_share_body(body)


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


async def _post_x_via_compose_ui(
    page: object,
    title: str,
    video_url: str,
    *,
    image_path: Path | None = None,
    compose_text: str | None = None,
) -> None:
    """Logged-in X: sidebar Post → composer (often ``role=dialog``) → type → Post."""
    from playwright.async_api import TimeoutError as PWTimeout

    text = (compose_text or "").strip() or _compose_x_text(title, video_url)
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

    await _attach_image_x_composer(page, image_path)

    for _ in range(90):
        if await _x_click_post_in_composer(page):
            await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_X_POST_WAIT_MS") or "2500").strip() or "2500"))  # type: ignore[union-attr]
            print("(social playwright) X: posted (compose UI flow, modal-aware).", flush=True)
            return
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    raise TimeoutError("X compose: Post button stayed disabled or not found (modal composer?).")


async def _post_x(
    context: object,
    title: str,
    video_url: str,
    *,
    image_path: Path | None = None,
    compose_text: str | None = None,
) -> None:
    page = await context.new_page()  # type: ignore[union-attr]
    try:
        if image_path is not None and _env_truthy("LUNA_SOCIAL_X_POST_LEGACY_INTENT", default=False):
            print(
                "(social playwright) X: intent URL cannot attach images — using compose UI.",
                flush=True,
            )
        if (
            _env_truthy("LUNA_SOCIAL_X_POST_LEGACY_INTENT", default=False)
            and image_path is None
            and not compose_text
        ):
            await _post_x_via_intent_url(page, title, video_url)
            return
        try:
            await _post_x_via_compose_ui(
                page,
                title,
                video_url,
                image_path=image_path,
                compose_text=compose_text,
            )
        except Exception as exc:
            if image_path is not None or compose_text:
                raise
            print(f"(social playwright) X: compose UI failed ({exc}); trying intent URL.", flush=True)
            await _post_x_via_intent_url(page, title, video_url)
    finally:
        await page.close()


def _compose_fb_share_text(title: str, video_url: str) -> str:
    """Static comment + URL (template/prefix or fallback). Prefer :func:`_compose_fb_share_text_async` for LLM."""
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
            if title_clean:
                comment = f"Sharing something I enjoyed — {title_clean}. Give it a watch below."
            else:
                comment = "Sharing a video — link below."
        body = f"{comment}\n\n{url_clean}".strip() if url_clean else comment
    return _clamp_fb_share_body(body)


def _clamp_fb_share_body(body: str) -> str:
    max_len = int((os.environ.get("LUNA_SOCIAL_FB_MAX_CHARS") or "8000").strip() or "8000")
    max_len = max(100, min(max_len, 63206))
    if len(body) > max_len:
        return body[: max_len - 1] + "…"
    return body


def _fb_share_uses_explicit_template() -> bool:
    return bool(
        (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_TEMPLATE") or "").strip()
        or (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PREFIX") or "").strip()
    )


def _fb_share_comment_llm_enabled() -> bool:
    if _fb_share_uses_explicit_template():
        return False
    return _env_truthy("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_LLM", default=True)


def _fb_llm_comment_user_prompt(title: str, video_url: str) -> str:
    custom = (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_PROMPT") or "").strip()
    if custom:
        return custom.replace("{title}", (title or "").strip()).replace("{url}", (video_url or "").strip())
    title_clean = (title or "").strip() or "Untitled video"
    return (
        "Write a short Facebook post comment (1–3 sentences) announcing a new YouTube upload.\n"
        f"Video title: {title_clean}\n"
        "Write in first person as the creator. Sound natural and warm, not salesy.\n"
        "Do NOT include the URL, hashtags, markdown, or labels like \"Comment:\".\n"
        "Output only the post text."
    )


def _fb_llm_comment_system_prompt() -> str:
    from luna_persona import build_luna_system_prompt

    extra = build_luna_system_prompt()
    base = (
        "You help a streamer write brief social posts. "
        "Reply with plain text only — no reasoning tags, no bullet lists."
    )
    return f"{extra}\n\n{base}".strip() if extra else base


def _sanitize_fb_llm_comment(raw: str, video_url: str) -> str:
    from ollama_client import strip_think_blocks

    text = strip_think_blocks((raw or "").strip())
    text = re.sub(r"^[\"'`]+|[\"'`]+$", "", text).strip()
    url_clean = (video_url or "").strip()
    if url_clean:
        text = text.replace(url_clean, "").strip()
    text = re.sub(r"https?://\S+", "", text).strip()
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _generate_fb_share_comment_llm_sync(title: str, video_url: str) -> str | None:
    from ollama_client import build_client, chat_request_kwargs

    model = (os.environ.get("LUNA_CHAT_MODEL") or os.environ.get("OLLAMA_MODEL") or "").strip()
    if not model:
        return None
    messages = [
        {"role": "system", "content": _fb_llm_comment_system_prompt()},
        {"role": "user", "content": _fb_llm_comment_user_prompt(title, video_url)},
    ]
    kwargs = chat_request_kwargs(model, messages, stream=False)
    predict_raw = (os.environ.get("LUNA_SOCIAL_FACEBOOK_POST_COMMENT_NUM_PREDICT") or "120").strip() or "120"
    try:
        predict = max(32, int(predict_raw))
    except ValueError:
        predict = 120
    opts = dict(kwargs.get("options") or {})
    opts["num_predict"] = predict
    kwargs["options"] = opts
    client = build_client()
    response = client.chat(**kwargs)
    comment = _sanitize_fb_llm_comment(response.message.content or "", video_url)
    return comment or None


async def _generate_fb_share_comment_llm(title: str, video_url: str) -> str | None:
    try:
        return await asyncio.to_thread(_generate_fb_share_comment_llm_sync, title, video_url)
    except Exception as exc:
        print(f"(social playwright) Facebook comment LLM failed ({exc}); using static fallback.", flush=True)
        return None


async def _compose_fb_share_text_async(title: str, video_url: str) -> str:
    """Comment from Ollama when enabled; else template/prefix/static fallback; URL on its own line."""
    if _fb_share_uses_explicit_template():
        return _compose_fb_share_text(title, video_url)
    comment: str | None = None
    if _fb_share_comment_llm_enabled():
        comment = await _generate_fb_share_comment_llm(title, video_url)
        if comment:
            print(f"(social playwright) Facebook comment (LLM): {comment[:120]}{'…' if len(comment) > 120 else ''}", flush=True)
    if not comment:
        return _compose_fb_share_text(title, video_url)
    url_clean = (video_url or "").strip()
    body = f"{comment}\n\n{url_clean}".strip() if url_clean else comment
    return _clamp_fb_share_body(body)


def _split_fb_comment_body(body: str, video_url: str) -> tuple[str, str]:
    """Return ``(comment, url)`` for separate Lexical typing (comment, blank line, URL)."""
    url_clean = (video_url or "").strip()
    comment = (body or "").strip()
    if url_clean:
        comment = comment.replace(url_clean, "").strip().strip("\n")
    return comment, url_clean


async def _fb_role_button_ready(btn: object) -> bool:
    try:
        disabled = await btn.get_attribute("aria-disabled")  # type: ignore[union-attr]
        if disabled in ("true", "1"):
            return False
        return await btn.is_enabled()  # type: ignore[union-attr]
    except Exception:
        return False


async def _fb_write_lexical_composer(
    page: object, editor: object, comment: str, video_url: str
) -> None:
    """Type into Facebook's Lexical ``data-lexical-editor`` box (``fill`` often leaves Next disabled)."""
    await editor.click(timeout=10_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(400)  # type: ignore[union-attr]
    for key in ("Control+a", "Meta+a"):
        try:
            await page.keyboard.press(key)
        except Exception:
            pass
    await page.keyboard.press("Backspace")
    await page.wait_for_timeout(250)  # type: ignore[union-attr]

    delay = int((os.environ.get("LUNA_SOCIAL_FB_POST_TYPE_DELAY_MS") or "14").strip() or "14")
    comment_s = (comment or "").strip()
    url_s = (video_url or "").strip()
    if comment_s:
        await page.keyboard.type(comment_s, delay=delay)  # type: ignore[union-attr]
    if url_s:
        if comment_s:
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
        await page.keyboard.type(url_s, delay=max(8, delay - 2))  # type: ignore[union-attr]
    await page.wait_for_timeout(1000)  # type: ignore[union-attr]

    need = max(10, min(len(comment_s), 24)) if comment_s else 5
    try:
        got = (await editor.inner_text() or "").strip()  # type: ignore[union-attr]
    except Exception:
        got = ""
    if len(got) >= need:
        return
    # Fallback: ``press_sequentially`` on the textbox node.
    await editor.click(timeout=5000)  # type: ignore[union-attr]
    for key in ("Control+a", "Meta+a"):
        try:
            await page.keyboard.press(key)
        except Exception:
            pass
    await page.keyboard.press("Backspace")
    blob = f"{comment_s}\n\n{url_s}".strip() if url_s and comment_s else (comment_s or url_s)
    if blob:
        await editor.press_sequentially(blob, delay=delay, timeout=180_000)  # type: ignore[union-attr]
    await page.wait_for_timeout(800)  # type: ignore[union-attr]


async def _fb_wait_story_ready(
    dialog: object, editor: object, page: object, comment: str, video_url: str, step_timeout: int
) -> None:
    """Wait until composer has text / link preview so **Next** can turn blue."""
    from playwright.async_api import TimeoutError as PWTimeout

    url_s = (video_url or "").strip()
    comment_s = (comment or "").strip()
    loops = max(40, step_timeout // 250)
    host = (urllib.parse.urlparse(url_s).hostname or "").lower() if url_s else ""
    tail = url_s.rsplit("/", 1)[-1][:48] if url_s and "/" in url_s else (url_s[:48] if url_s else "")
    for _ in range(loops):
        try:
            body_txt = (await editor.inner_text() or "").strip()  # type: ignore[union-attr]
        except Exception:
            body_txt = ""
        has_comment = len(body_txt) >= max(8, min(len(comment_s), 20)) if comment_s else len(body_txt) > 0
        has_url = not url_s or url_s in body_txt or (tail and tail in body_txt)
        if has_comment and has_url:
            return
        if host:
            try:
                if await dialog.locator(f'a[href*="{host}"]').count() > 0:  # type: ignore[union-attr]
                    return
            except Exception:
                pass
        await page.wait_for_timeout(250)  # type: ignore[union-attr]
    if url_s and host:
        try:
            await dialog.locator(f'a[href*="{host}"]').first.wait_for(  # type: ignore[union-attr]
                state="visible", timeout=min(step_timeout, 20_000)
            )
            return
        except PWTimeout:
            pass


async def _fb_wait_and_click_next(dialog: object, page: object, step_timeout: int) -> None:
    """Step 2 — blue **Next** when ``aria-disabled`` is gone."""
    next_btn = dialog.locator('[role="button"][aria-label="Next"]').first  # type: ignore[union-attr]
    if await next_btn.count() == 0:
        next_btn = dialog.get_by_role("button", name="Next", exact=True)  # type: ignore[union-attr]
    await next_btn.wait_for(state="visible", timeout=step_timeout)
    await next_btn.scroll_into_view_if_needed()  # type: ignore[union-attr]
    loops = max(60, step_timeout // 250)
    for _ in range(loops):
        if await _fb_role_button_ready(next_btn):
            break
        await page.wait_for_timeout(250)  # type: ignore[union-attr]
    await next_btn.click(timeout=20_000)


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


async def _fb_resolve_post_settings_dialog(page: object, step_timeout: int) -> object:
    """**Post settings** sheet — markers like *Post audience* / *Publish now*, not loose ``post`` substring."""
    from playwright.async_api import TimeoutError as PWTimeout

    markers = re.compile(r"Post audience|Scheduling options|Publish now", re.I)
    sheet = page.locator('[role="dialog"]').filter(has_text=markers).first  # type: ignore[union-attr]
    try:
        await sheet.wait_for(state="visible", timeout=step_timeout)
        return sheet
    except PWTimeout:
        pass
    sheet = page.get_by_role("dialog", name=re.compile(r"post settings", re.I)).first  # type: ignore[union-attr]
    try:
        await sheet.wait_for(state="visible", timeout=step_timeout)
        return sheet
    except PWTimeout:
        pass
    sheet = page.locator('[role="dialog"]').filter(  # type: ignore[union-attr]
        has=page.get_by_role("heading", name=re.compile(r"post settings", re.I))
    ).first
    await sheet.wait_for(state="visible", timeout=step_timeout)
    return sheet


async def _fb_find_post_settings_publish_button(post_sheet: object) -> object | None:
    """Blue footer **Post** beside grey **Save** — ``role=button`` whose visible label is exactly Post."""
    deny = re.compile(r"add to|boost|audience|save|schedule|share to|back", re.I)

    # Footer pair: Save (left) + Post (right) — prefer ``span`` with exact text inside ``role=button``.
    by_span = post_sheet.locator(  # type: ignore[union-attr]
        '[role="button"]:has(span:text-is("Post"))'
    )
    if await by_span.count() > 0:
        return by_span.last

    for loc in (
        post_sheet.locator('[role="button"][aria-label="Post"]'),  # type: ignore[union-attr]
        post_sheet.locator('[role="button"][aria-label="Publish"]'),  # type: ignore[union-attr]
    ):
        n = await loc.count()
        for i in range(n - 1, -1, -1):
            btn = loc.nth(i)
            label = (await btn.get_attribute("aria-label") or "").strip()
            if label not in ("Post", "Publish"):
                continue
            try:
                if await btn.is_visible():
                    return btn
            except Exception:
                continue

    all_btns = post_sheet.locator('[role="button"]')  # type: ignore[union-attr]
    n = await all_btns.count()
    for i in range(n - 1, -1, -1):
        btn = all_btns.nth(i)
        try:
            if not await btn.is_visible():
                continue
        except Exception:
            continue
        raw = (await btn.inner_text() or "").strip()
        label = re.sub(r"\s+", " ", raw)
        if label != "Post":
            continue
        if deny.search(raw):
            continue
        return btn

    spans = post_sheet.get_by_text("Post", exact=True)  # type: ignore[union-attr]
    sn = await spans.count()
    for i in range(sn - 1, -1, -1):
        sp = spans.nth(i)
        try:
            if not await sp.is_visible():
                continue
        except Exception:
            continue
        btn = sp.locator("xpath=ancestor::*[@role='button'][1]")
        if await btn.count() == 0:
            btn = sp.locator("xpath=ancestor::*[@tabindex='0'][1]")
        if await btn.count() == 0:
            continue
        try:
            if await btn.first.is_visible():
                return btn.first
        except Exception:
            continue
    return None


async def _fb_click_post_settings_publish(post_sheet: object, page: object, step_timeout: int) -> None:
    """Step 4 — click the blue footer **Post** on *Post settings*."""
    from playwright.async_api import TimeoutError as PWTimeout

    await post_sheet.get_by_text(re.compile(r"Post audience|Scheduling options", re.I)).first.wait_for(  # type: ignore[union-attr]
        state="visible", timeout=step_timeout
    )
    post_btn = None
    for _ in range(60):
        post_btn = await _fb_find_post_settings_publish_button(post_sheet)
        if post_btn is not None:
            break
        await page.wait_for_timeout(250)  # type: ignore[union-attr]
    if post_btn is None:
        raise PWTimeout("Post settings: blue Post footer button not found")
    await post_btn.wait_for(state="visible", timeout=step_timeout)
    await post_btn.scroll_into_view_if_needed()  # type: ignore[union-attr]
    for _ in range(80):
        if await _fb_role_button_ready(post_btn):
            break
        await page.wait_for_timeout(200)  # type: ignore[union-attr]
    await post_btn.click(timeout=20_000)


async def _post_facebook_via_composer_ui(
    page: object,
    title: str,
    video_url: str,
    *,
    image_path: Path | None = None,
    compose_text: str | None = None,
) -> None:
    """Facebook *Create post* → **Next** → *Post settings* blue **Post** only (never *Add to your post*)."""

    async def _fb_story_composer(dlg: object) -> object:
        """Lexical story box — ``data-lexical-editor`` + *What's on your mind* placeholder."""
        by_lex = dlg.locator(
            '[data-lexical-editor="true"][role="textbox"][contenteditable="true"]'
            '[aria-placeholder*="on your mind"]'
        ).first
        if await by_lex.count() > 0:
            return by_lex
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

    text = (compose_text or "").strip() or await _compose_fb_share_text_async(title, video_url)
    comment, url_for_compose = _split_fb_comment_body(text, video_url)
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

    # Step 1 — LLM comment + URL into Lexical ``What's on your mind?`` box (keyboard, not ``fill``).
    editor = await _fb_story_composer(dialog)
    await editor.wait_for(state="visible", timeout=step_timeout)
    await editor.scroll_into_view_if_needed()  # type: ignore[union-attr]
    await _fb_dismiss_add_to_post_dialog(page)
    await _fb_write_lexical_composer(page, editor, comment, url_for_compose)
    await _fb_dismiss_add_to_post_dialog(page)
    await _fb_wait_story_ready(dialog, editor, page, comment, url_for_compose, step_timeout)

    await _fb_dismiss_add_to_post_dialog(page)
    await _attach_image_fb_dialog(dialog, page, image_path)

    # Step 2 — blue **Next** (enabled when composer has content).
    await _fb_wait_and_click_next(dialog, page, step_timeout)

    # Step 3 — wait for *Post settings* (after **Next**).
    await page.wait_for_timeout(1200)  # type: ignore[union-attr]
    try:
        await dialog.wait_for(state="hidden", timeout=min(step_timeout, 12_000))  # type: ignore[union-attr]
    except PWTimeout:
        pass

    post_sheet = await _fb_resolve_post_settings_dialog(page, step_timeout)

    # Step 4 — find and click the blue footer **Post** (exact label, not *Add to your post*).
    await _fb_click_post_settings_publish(post_sheet, page, step_timeout)
    await page.wait_for_timeout(int((os.environ.get("LUNA_SOCIAL_FB_POST_WAIT_MS") or "4000").strip() or "4000"))  # type: ignore[union-attr]
    print("(social playwright) Facebook: posted (steps: textbox → Next → Post settings → Post).", flush=True)


async def _post_facebook(
    context: object,
    title: str,
    video_url: str,
    *,
    image_path: Path | None = None,
    compose_text: str | None = None,
) -> None:
    page = await context.new_page()  # type: ignore[union-attr]
    try:
        if _env_truthy("LUNA_SOCIAL_FACEBOOK_POST_LEGACY_SHARER", default=False):
            if image_path is not None or compose_text:
                print(
                    "(social playwright) Facebook: legacy sharer cannot attach images — using composer.",
                    flush=True,
                )
            else:
                await _post_facebook_via_sharer(page, title, video_url)
                return
        try:
            await _post_facebook_via_composer_ui(
                page,
                title,
                video_url,
                image_path=image_path,
                compose_text=compose_text,
            )
        except Exception as exc:
            if image_path is not None or compose_text:
                raise
            print(f"(social playwright) Facebook: composer UI failed ({exc}); trying sharer.", flush=True)
            await _post_facebook_via_sharer(page, title, video_url)
    finally:
        await page.close()


async def share_live_stream(
    *,
    platform: str,
    title: str,
    stream_url: str,
    image_path: Path | None = None,
) -> None:
    """Go-live post to X and Facebook with optional promo image + cute LLM invitation."""
    img = image_path if image_path is not None else live_announce_image_path()
    body = await compose_live_share_text_async(platform, title, stream_url)
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
                            await _post_x(
                                ctx,
                                title,
                                stream_url,
                                image_path=img,
                                compose_text=body,
                            )
                        finally:
                            await ctx.close()
                    if fb_path is not None:
                        ctx = await browser.new_context(
                            **stealth_browser_context_kwargs(storage_state=fb_path)
                        )
                        await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                        try:
                            await _post_facebook(
                                ctx,
                                title,
                                stream_url,
                                image_path=img,
                                compose_text=body,
                            )
                        finally:
                            await ctx.close()
                finally:
                    await browser.close()
        except Exception as exc:
            print(f"(social playwright) live share failed: {exc}", flush=True)


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
                            await _post_x(ctx, title, video_url, image_path=None)
                        finally:
                            await ctx.close()
                    if fb_path is not None:
                        ctx = await browser.new_context(
                            **stealth_browser_context_kwargs(storage_state=fb_path)
                        )
                        await ctx.add_init_script(STEALTH_INIT_SCRIPT)
                        try:
                            await _post_facebook(ctx, title, video_url, image_path=None)
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
    elif s in ("youtube", "yt"):
        s = "youtube"
    else:
        await broadcast("Social login: use site x, facebook, or youtube.")
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
                        f"Ensure LUNA_SOCIAL_{'FACEBOOK' if s == 'facebook' else 'YOUTUBE' if s == 'youtube' else 'X'}_STORAGE_STATE matches this path; restart Luna if you changed it."
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

"""Quick check: does DISCORD_TOKEN in .env actually authenticate against Discord?

Run:  python verify_discord_token.py

Hits https://discord.com/api/v10/users/@me with the token and prints either:
  OK  -> bot tag + application id
  FAIL -> HTTP status + Discord's exact error JSON

This bypasses discord.py and the gateway, so it isolates the token itself
from any library / intent / process issues.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request

from dotenv import load_dotenv


def main() -> int:
    load_dotenv(override=True)
    token = (os.environ.get("DISCORD_TOKEN") or "").strip()
    if not token:
        print("FAIL: DISCORD_TOKEN is empty in .env (or .env missing).")
        return 1

    # Show only safe metadata about the token, never the token itself.
    parts = token.split(".")
    sig_len = len(parts[2]) if len(parts) >= 3 else 0
    print(
        f"Token shape: segments={len(parts)} "
        f"first_seg_len={len(parts[0]) if parts else 0} "
        f"signature_len={sig_len} total_len={len(token)}"
    )
    if len(parts) != 3:
        print(
            "FAIL: bot tokens have exactly THREE segments separated by '.', e.g. AAAA.BBBB.CCCCCCCC. "
            "Yours has the wrong shape — almost certainly a partial copy/paste."
        )
        return 2

    req = urllib.request.Request(
        "https://discord.com/api/v10/users/@me",
        headers={
            "Authorization": f"Bot {token}",
            "User-Agent": "LunaStreamerTokenCheck (https://luna.local, 0.1)",
        },
        method="GET",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
    except urllib.error.HTTPError as exc:
        body = ""
        try:
            body = exc.read().decode("utf-8", errors="replace")
        except Exception:
            pass
        print(f"FAIL: HTTP {exc.code} from Discord. Body: {body[:500]}")
        if exc.code == 401:
            print(
                "Discord says the token is not valid. Causes (any of):\n"
                "  1. The token in .env is not the latest one — Reset Token in the portal again, "
                "use the 'Copy' button, paste into line 1 of .env, save, restart.\n"
                "  2. You reset under the wrong Application — confirm the App's Application ID matches the bot id.\n"
                "  3. There is a trailing space / hidden newline in .env after the token."
            )
        return 3
    except urllib.error.URLError as exc:
        print(f"FAIL: network error reaching discord.com: {exc.reason}")
        print("If the rest of your bot can reach Discord normally, this is unlikely. Otherwise check firewall/VPN/system clock.")
        return 4
    except Exception as exc:  # noqa: BLE001
        print(f"FAIL: unexpected error: {type(exc).__name__}: {exc}")
        return 5

    username = data.get("username", "?")
    discriminator = data.get("discriminator", "0")
    bot_id = data.get("id", "?")
    flags = data.get("flags")
    bot_flag = data.get("bot")
    print(f"OK: authenticated as {username}#{discriminator} (id={bot_id}) bot={bot_flag} flags={flags}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

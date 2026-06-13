"""Export X/Facebook login JSON from existing Chrome profiles (one-time recovery).

Run:  python scripts/recover_social_login.py
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from dotenv import load_dotenv

from social_playwright_share import recover_social_storage_states


async def main() -> int:
    load_dotenv(override=True)

    async def _print(text: str) -> None:
        print(text, flush=True)

    results = await recover_social_storage_states(broadcast=_print)
    if not results:
        print("No LUNA_SOCIAL_*_STORAGE_STATE paths in .env", flush=True)
        return 1
    ok = any(results.values())
    for site, saved in results.items():
        print(f"  {site}: {'OK' if saved else 'missing profile or export failed'}", flush=True)
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

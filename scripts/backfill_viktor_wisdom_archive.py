"""One-shot: archive all past Viktor duty DM MP3s from Discord into viktor 's wisdom for men.

Run:  python scripts/backfill_viktor_wisdom_archive.py
      python scripts/backfill_viktor_wisdom_archive.py --no-synth   # download MP3s only
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    load_dotenv(override=True)
    parser = argparse.ArgumentParser(description="Backfill Viktor wisdom archive from Discord DMs")
    parser.add_argument(
        "--no-synth",
        action="store_true",
        help="Only download existing Viktor_discord MP3 attachments (no TTS for text-only reminders)",
    )
    args = parser.parse_args()

    token = (os.environ.get("DISCORD_TOKEN") or "").strip()
    if not token:
        print("DISCORD_TOKEN missing in .env", file=sys.stderr)
        return 1

    from luna_discord_private_duty_dm import (
        backfill_viktor_wisdom_archive_from_discord,
        private_duty_dm_owner_ids,
    )

    if not private_duty_dm_owner_ids():
        print("Set LUNA_OWNER_DISCORD_ID (or LUNA_DISCORD_PRIVATE_DUTY_DM_USER_ID) in .env", file=sys.stderr)
        return 1

    import discord

    intents = discord.Intents.default()
    intents.message_content = True

    class _BackfillClient(discord.Client):
        async def on_ready(self) -> None:
            try:
                await backfill_viktor_wisdom_archive_from_discord(
                    self,
                    synthesize_missing=not args.no_synth,
                )
            finally:
                await self.close()

    client = _BackfillClient(intents=intents)
    try:
        asyncio.run(client.start(token))
    except discord.LoginFailure:
        print("Invalid DISCORD_TOKEN", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

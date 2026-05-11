# Luna Streamer

A focused, streaming-only build of Luna — a wolf-girl VTuber co-host that runs
locally and ties together Twitch chat, a Discord music bot, a VRM viewer with
microphone STT and TTS, and YouTube integration.

It's intentionally small: one orchestrator (`main.py`) launches a Vite-hosted
VRM viewer and a Twitch bot, and the Twitch bot in turn boots the Discord
music bot, the YouTube RSS poller, and the chat-bridge WebSocket the viewer
connects to.

## Features

- **Twitch chat ↔ Ollama** — `!ai` / `!luna` plus optional auto-reply on any
  message in the configured channel.
- **VRM viewer with mic input** — a Vite/React app shows your VRM avatar and
  streams microphone audio over WebSocket to the backend, which transcribes
  with `faster-whisper` (CUDA + float16 when available, CPU + int8 otherwise).
- **Speaker verification gate** — enroll your voice once from the viewer's
  panel and Luna will ignore every other voice on the mic (including her own
  TTS bleeding through your headphones). Falls back to a coarse "male voice"
  pitch gate if you prefer.
- **Luna TTS** — Edge-TTS by default; optional Chatterbox voice cloning when
  you point it at a 5–15s reference WAV.
- **Discord music bot** — `!join`, `!play <url|search>`, `!skip`, `!stop`,
  `!pause`, `!resume`, `!queue`, `!nowplaying`. The same `!play` works from
  Twitch chat (with `!explain` summarizing a YouTube transcript through Luna).
- **YouTube upload announcer** — RSS-polls a channel and announces new videos
  in Twitch chat.
- **GPU offload** — both `faster-whisper` (STT) and Ollama (LLM) auto-detect
  CUDA and prefer the GPU.

## Layout

```
main.py                  orchestrator: starts viewer + twitch_bot
twitch_bot.py            Twitch IRC bot + chat-bridge WS + glue
luna_discord_bot.py      Discord music bot (discord.py[voice])
luna_stt.py              faster-whisper wrapper (CUDA/CPU auto)
luna_tts.py              Edge-TTS / Chatterbox
luna_speaker_id.py       MFCC speaker verification gate
luna_voice_gate.py       Coarse F0 pitch gate (fallback)
ollama_client.py         Ollama HTTP client + GPU options
youtube_audio.py         yt-dlp + transcript helpers (!play / !explain)
youtube_feed.py          Channel RSS poller (new-upload announcements)
chat_ws.py               WebSocket bridge to the viewer
ollama/Modelfile.luna    Optional baked-in persona model
viewer/                  Vite + React VRM viewer (mic, chat, controls)
verify_discord_token.py  One-shot Discord token validity check
```

## Requirements

- Python 3.11+ (3.12 / 3.13 verified)
- Node 18+ (for the viewer)
- A local [Ollama](https://ollama.com) install with at least one chat model
  pulled (`ollama pull qwen3.5:4b`)
- FFmpeg on PATH (used by `faster-whisper` and `discord.py[voice]`)
- For GPU STT: a CUDA-capable GPU and a matching `ctranslate2` build
- For GPU LLM: a recent Ollama with CUDA support

## Setup

```powershell
# 1. Clone
git clone https://github.com/christossolonos-bit/Luna-Streamer.git
cd Luna-Streamer

# 2. Python deps
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# 3. Viewer deps
cd viewer
npm install
cd ..

# 4. Configure
copy .env.example .env
copy viewer\.env.example viewer\.env
# Open .env and fill in DISCORD_TOKEN, TWITCH_TOKEN, TWITCH_CHANNEL, etc.

# 5. (Optional) bake the persona into Ollama as `luna`
ollama create luna -f ollama/Modelfile.luna
```

## Running

```powershell
python main.py
```

That single command:

1. Picks a VRM and idle motions from `expressions/` (override with
   `--vrm <path>` / `--idle <path>`).
2. Starts the Vite dev server (default `http://127.0.0.1:5173`, falls back to
   5174 if busy) and opens the viewer in your browser.
3. Launches `twitch_bot.py`, which:
   - connects to Twitch IRC,
   - serves the chat-bridge WebSocket on `ws://127.0.0.1:8765/ws`,
   - starts the Discord music bot if `DISCORD_TOKEN` is set,
   - starts the YouTube RSS poller if `LUNA_YOUTUBE_CHANNEL_ID` is set.

## Verifying Discord works

The most common Luna setup pain is a bad Discord token. There's a standalone
checker:

```powershell
python verify_discord_token.py
```

It calls Discord's `/users/@me` and prints either:

```
OK: authenticated as YourBot#0000 (id=...) bot=True
```

or a specific reason (`401 Unauthorized`, malformed shape, etc.).

If you ever see `(discord) FAILED: invalid DISCORD_TOKEN` in the main log:

1. Reset the token in the [Developer Portal](https://discord.com/developers/applications).
2. Enable **Message Content Intent** under Privileged Gateway Intents.
3. Paste the new token into `.env`.
4. Restart `main.py`.

The codebase calls `load_dotenv(override=True)` so values in `.env` always win
over any stale `DISCORD_TOKEN` left in your shell or Windows User environment.

## Inviting the bot to a server

```
https://discord.com/oauth2/authorize?client_id=<APPLICATION_ID>&permissions=36719616&scope=bot%20applications.commands
```

Permissions `36719616` covers: view channels, send messages, connect, speak,
use voice activity. Replace `<APPLICATION_ID>` with the bot's application id
from the Developer Portal.

## License

MIT — see [LICENSE](LICENSE).

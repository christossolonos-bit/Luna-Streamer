"""Luna orchestrator: startup entrypoint for local modules."""

from __future__ import annotations

import argparse
import http.server
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path


DEFAULT_VRM = Path(r"D:\Luna streamer\Luna.vrm")


def _url_alive(url: str, timeout: float = 0.8) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout):
            return True
    except Exception:
        return False


def _port_open(host: str, port: int, timeout: float = 0.5) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _find_free_port(host: str, start_port: int, max_tries: int = 30) -> int:
    for port in range(start_port, start_port + max_tries):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind((host, port))
                return port
            except OSError:
                continue
    raise RuntimeError(f"No free port found in range {start_port}-{start_port + max_tries - 1}")


def _to_vite_fs_url(path: Path) -> str:
    absolute = path.resolve()
    normalized = absolute.as_posix()
    return f"/@fs/{normalized}"


def _viewer_page_url(
    port: int,
    vrm_file: Path,
    idle_motion_files: list[Path],
    *,
    cohost_idle_motion_files: list[Path] | None = None,
    chat_ws: str | None = None,
    cohost_vrm_file: Path | None = None,
    cohost_display_name: str | None = None,
    cohost_idle_skip_sec: float | None = None,
) -> str:
    fs_url = _to_vite_fs_url(vrm_file)
    payload: list[tuple[str, str]] = [("vrm", fs_url)]
    for motion in idle_motion_files:
        payload.append(("idle", _to_vite_fs_url(motion)))
    for motion in cohost_idle_motion_files or []:
        payload.append(("cohost_idle", _to_vite_fs_url(motion)))
    if cohost_vrm_file is not None and cohost_vrm_file.is_file():
        payload.append(("cohost_vrm", _to_vite_fs_url(cohost_vrm_file)))
    if cohost_display_name:
        payload.append(("cohost_name", cohost_display_name.strip()))
    if cohost_idle_skip_sec is not None and cohost_idle_skip_sec > 0:
        payload.append(("cohost_idle_skip_sec", str(cohost_idle_skip_sec)))
    if chat_ws:
        payload.append(("chat_ws", chat_ws))
    query = urllib.parse.urlencode(payload, doseq=True)
    return f"http://127.0.0.1:{port}/?{query}"


def _terminate_process(proc: subprocess.Popen[str], name: str) -> None:
    if proc.poll() is not None:
        return
    print(f"Stopping {name}...")
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()


class _ViewerRequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path: str) -> str:
        parsed_path = urllib.parse.urlparse(path).path
        if parsed_path.startswith("/@fs/"):
            fs_path = urllib.parse.unquote(parsed_path[len("/@fs/") :])
            return str(Path(fs_path))
        return super().translate_path(path)


def _start_viewer_static(dist_dir: Path, port: int) -> http.server.ThreadingHTTPServer:
    if not dist_dir.is_dir():
        raise FileNotFoundError(
            f"Viewer build folder not found: {dist_dir}. "
            "Build with: cd viewer && npm run build   "
            "Or omit --static to use Vite dev (hot reload)."
        )
    print(f"Starting static viewer server from: {dist_dir}")
    handler = lambda *a, **kw: _ViewerRequestHandler(*a, directory=str(dist_dir), **kw)
    server = http.server.ThreadingHTTPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    print(f"Serving HTTP on 127.0.0.1 port {port} (http://127.0.0.1:{port}/) ...")
    return server


def _start_viewer_vite(viewer_dir: Path, port: int) -> subprocess.Popen[str]:
    """Run `vite` dev server (HMR). Requires Node and viewer/node_modules."""
    if sys.platform == "win32":
        vite = viewer_dir / "node_modules" / ".bin" / "vite.cmd"
    else:
        vite = viewer_dir / "node_modules" / ".bin" / "vite"
    if vite.is_file():
        cmd: list[str] = [
            str(vite),
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ]
    else:
        cmd = [
            "npx",
            "--yes",
            "vite",
            "--host",
            "127.0.0.1",
            "--port",
            str(port),
            "--strictPort",
        ]
    print(f"Starting Vite dev server in {viewer_dir} (hot reload; pass --static for dist/) ...")
    return subprocess.Popen(
        cmd,
        cwd=str(viewer_dir),
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        text=True,
    )


def _start_twitch_bot(root_dir: Path) -> subprocess.Popen[str]:
    script = root_dir / "twitch_bot.py"
    if not script.is_file():
        raise FileNotFoundError(f"twitch_bot.py not found: {script}")
    cmd = [sys.executable, str(script)]
    print("Starting Twitch bot...")
    return subprocess.Popen(cmd, cwd=str(root_dir), text=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run Luna modules from a single startup script."
    )
    parser.add_argument(
        "--vrm",
        type=Path,
        default=DEFAULT_VRM,
        help=r"Path to default VRM file (default: D:\Chris Stuff\Luna.vrm).",
    )
    parser.add_argument(
        "--viewer-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "viewer",
        help="Path to viewer directory (contains dist/).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=5173,
        help="Viewer port (Vite dev by default, or static dist with --static).",
    )
    parser.add_argument(
        "--static",
        action="store_true",
        help="Serve viewer/dist only (no npm). Default is Vite dev for instant UI reload.",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Do not open browser automatically.",
    )
    parser.add_argument(
        "--with-bot",
        action="store_true",
        help="Also start twitch_bot.py (legacy; bot now starts by default).",
    )
    parser.add_argument(
        "--no-bot",
        action="store_true",
        help="Do not start twitch_bot.py.",
    )
    parser.add_argument(
        "--viewer-only",
        action="store_true",
        help="Start only the viewer, even if --with-bot is set.",
    )
    parser.add_argument(
        "--expressions-dir",
        type=Path,
        default=Path(__file__).resolve().parent / "expressions",
        help="Folder containing idle VRMA files.",
    )
    root_dir_pre = Path(__file__).resolve().parent
    _cohost_idle_env = (os.environ.get("LUNA_COHOST_EXPRESSIONS_DIR") or "").strip()
    _cohost_idle_default = (
        Path(_cohost_idle_env).expanduser().resolve()
        if _cohost_idle_env
        else root_dir_pre / "expressions1"
    )
    parser.add_argument(
        "--cohost-expressions-dir",
        type=Path,
        default=_cohost_idle_default,
        help="Folder containing co-host (Viktor) idle VRMA files (same style as Luna).",
    )
    args = parser.parse_args()

    root_dir = Path(__file__).resolve().parent
    vrm_file = args.vrm.resolve()
    viewer_dir = args.viewer_dir.resolve()
    viewer_dist = viewer_dir / "dist"
    expressions_dir = args.expressions_dir.resolve()
    cohost_expressions_dir = args.cohost_expressions_dir.resolve()
    active_port = args.port
    base_url = f"http://127.0.0.1:{active_port}/"

    if not viewer_dir.is_dir():
        print(f"Viewer folder not found: {viewer_dir}", file=sys.stderr)
        sys.exit(1)
    if not vrm_file.is_file():
        print(f"Default VRM not found: {vrm_file}", file=sys.stderr)
        sys.exit(1)
    if args.static and not viewer_dist.is_dir():
        print(
            f"No {viewer_dist} — run: cd viewer && npm run build   "
            "Or drop --static to use Vite dev.",
            file=sys.stderr,
        )
        sys.exit(1)
    if not args.static and not (viewer_dir / "package.json").is_file():
        print(f"No package.json in {viewer_dir}; use --static with a built dist.", file=sys.stderr)
        sys.exit(1)

    print(f"Viewer dir: {viewer_dir}")
    print(f"Default VRM: {vrm_file}")
    if expressions_dir.is_dir():
        idle_motion_files = sorted(expressions_dir.glob("**/*.vrma"))
    else:
        idle_motion_files = []
    print(f"Idle motions found: {len(idle_motion_files)} in {expressions_dir}")
    if cohost_expressions_dir.is_dir():
        cohost_idle_motion_files = sorted(cohost_expressions_dir.glob("**/*.vrma"))
    else:
        cohost_idle_motion_files = []
    print(
        f"Co-host idle motions: {len(cohost_idle_motion_files)} in {cohost_expressions_dir}",
    )

    viewer_server: http.server.ThreadingHTTPServer | None = None
    viewer_proc: subprocess.Popen[str] | None = None
    bot_proc: subprocess.Popen[str] | None = None

    viewer_already_running = _url_alive(base_url)
    if not viewer_already_running and _port_open("127.0.0.1", active_port):
        active_port = _find_free_port("127.0.0.1", active_port + 1)
        base_url = f"http://127.0.0.1:{active_port}/"
        print(
            f"Port {args.port} is occupied by another process. "
            f"Using fallback port {active_port}."
        )
    chat_ws_port = int(os.environ.get("LUNA_CHAT_WS_PORT", "8765").strip() or "8765")
    chat_ws_url = (
        f"ws://127.0.0.1:{chat_ws_port}/ws" if chat_ws_port > 0 else None
    )
    cohost_vrm: Path | None = None
    cohost_name: str | None = None
    try:
        from vampire_cohost import cohost_name as _cohost_name
        from vampire_cohost import cohost_vrm_path

        cohost_name = _cohost_name()
        p = cohost_vrm_path()
        if p.is_file():
            cohost_vrm = p
            print(
                f"Co-host VRM (summon from viewer dock): {cohost_vrm} ({cohost_name})"
            )
    except Exception:
        cohost_vrm = None
        cohost_name = None

    _cohost_skip_raw = (os.environ.get("LUNA_COHOST_IDLE_SKIP_SEC") or "2").strip() or "2"
    try:
        cohost_idle_skip_sec = max(0.0, float(_cohost_skip_raw))
    except ValueError:
        cohost_idle_skip_sec = 2.0

    page_url = _viewer_page_url(
        active_port,
        vrm_file,
        idle_motion_files,
        cohost_idle_motion_files=cohost_idle_motion_files,
        chat_ws=chat_ws_url,
        cohost_vrm_file=cohost_vrm,
        cohost_display_name=cohost_name,
        cohost_idle_skip_sec=cohost_idle_skip_sec,
    )
    if viewer_already_running:
        print(f"Viewer already running at {base_url}")
    try:
        if not viewer_already_running:
            if args.static:
                viewer_server = _start_viewer_static(viewer_dist, active_port)
            else:
                viewer_proc = _start_viewer_vite(viewer_dir, active_port)
                time.sleep(0.6)
                if viewer_proc.poll() is not None:
                    raise RuntimeError(
                        "Vite exited immediately. Install deps: cd viewer && npm install"
                    )
            start = time.time()
            while not _port_open("127.0.0.1", active_port):
                if time.time() - start > 45:
                    raise TimeoutError("Viewer startup timed out.")
                time.sleep(0.35)
            print(f"Viewer ready at {base_url}")

        if not args.no_open:
            webbrowser.open(page_url)
            print(f"Opened: {page_url}")

        should_start_bot = not args.viewer_only and not args.no_bot
        if should_start_bot:
            bot_proc = _start_twitch_bot(root_dir)

        if viewer_already_running and bot_proc is None:
            return

        print("Luna orchestrator running. Press Ctrl+C to stop managed modules.")
        while True:
            if bot_proc is not None and bot_proc.poll() is not None:
                print("Twitch bot process exited.")
                break
            time.sleep(0.5)
    except (TimeoutError, RuntimeError, FileNotFoundError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        print("\nShutdown requested.")
    finally:
        if bot_proc is not None:
            _terminate_process(bot_proc, "Twitch bot")
        if viewer_proc is not None:
            _terminate_process(viewer_proc, "Vite dev server")
        if viewer_server is not None:
            print("Stopping viewer...")
            viewer_server.shutdown()
            viewer_server.server_close()


if __name__ == "__main__":
    main()

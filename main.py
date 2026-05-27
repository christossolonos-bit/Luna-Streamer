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


def _brave_executable() -> Path | None:
    """Resolve Brave browser binary (Windows-focused; common install paths)."""
    env_path = (os.environ.get("LUNA_VIEWER_BRAVE_PATH") or "").strip()
    if env_path:
        p = Path(env_path).expanduser()
        if p.is_file():
            return p

    candidates: list[Path] = []
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        candidates.append(
            Path(local)
            / "BraveSoftware"
            / "Brave-Browser"
            / "Application"
            / "brave.exe"
        )
    for prefix in (
        os.environ.get("ProgramFiles", r"C:\Program Files"),
        os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"),
    ):
        if prefix:
            candidates.append(
                Path(prefix) / "BraveSoftware" / "Brave-Browser" / "Application" / "brave.exe"
            )

    for path in candidates:
        if path.is_file():
            return path
    return None


def _open_viewer_in_browser(url: str) -> bool:
    """Open the viewer URL (default: Brave). Set LUNA_VIEWER_BROWSER=default for OS default."""
    choice = (os.environ.get("LUNA_VIEWER_BROWSER") or "brave").strip().lower()
    if choice in ("0", "false", "no", "off", "none"):
        return False
    if choice in ("default", "system", "os"):
        webbrowser.open(url)
        return True

    if choice in ("brave", "brave-browser"):
        brave = _brave_executable()
        if brave is not None:
            try:
                subprocess.Popen(
                    [str(brave), url],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    close_fds=True,
                )
                print(f"Opened in Brave: {url}", flush=True)
                return True
            except OSError as exc:
                print(f"(viewer) Brave launch failed: {exc}", flush=True)
        try:
            webbrowser.get("brave").open(url)
            print(f"Opened in Brave: {url}", flush=True)
            return True
        except (webbrowser.Error, AttributeError):
            print(
                "(viewer) Brave not found — install Brave or set LUNA_VIEWER_BRAVE_PATH. "
                "Falling back to default browser.",
                flush=True,
            )

    if choice == "chrome":
        for name in ("chrome", "google-chrome", "google-chrome-stable"):
            try:
                webbrowser.get(name).open(url)
                print(f"Opened in {name}: {url}", flush=True)
                return True
            except webbrowser.Error:
                continue

    if choice == "edge":
        try:
            webbrowser.get("windows-default" if sys.platform == "win32" else "edge").open(url)
            print(f"Opened: {url}", flush=True)
            return True
        except webbrowser.Error:
            pass

    webbrowser.open(url)
    return True


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
    cohost_thinking_motion_file: Path | None = None,
    himari_vrm_file: Path | None = None,
    himari_display_name: str | None = None,
    himari_idle_motion_files: list[Path] | None = None,
    himari_thinking_motion_file: Path | None = None,
    himari_idle_skip_sec: float | None = None,
    luna_idle_skip_sec: float | None = None,
    luna_thinking_motion_file: Path | None = None,
) -> str:
    fs_url = _to_vite_fs_url(vrm_file)
    payload: list[tuple[str, str]] = [("vrm", fs_url)]
    for motion in idle_motion_files:
        payload.append(("idle", _to_vite_fs_url(motion)))
    if luna_thinking_motion_file is not None and luna_thinking_motion_file.is_file():
        payload.append(("luna_thinking", _to_vite_fs_url(luna_thinking_motion_file)))
    for motion in cohost_idle_motion_files or []:
        payload.append(("cohost_idle", _to_vite_fs_url(motion)))
    if cohost_vrm_file is not None and cohost_vrm_file.is_file():
        payload.append(("cohost_vrm", _to_vite_fs_url(cohost_vrm_file)))
    if cohost_display_name:
        payload.append(("cohost_name", cohost_display_name.strip()))
    if cohost_idle_skip_sec is not None and cohost_idle_skip_sec > 0:
        payload.append(("cohost_idle_skip_sec", str(cohost_idle_skip_sec)))
    if cohost_thinking_motion_file is not None and cohost_thinking_motion_file.is_file():
        payload.append(("cohost_thinking", _to_vite_fs_url(cohost_thinking_motion_file)))
    if himari_vrm_file is not None and himari_vrm_file.is_file():
        payload.append(("himari_vrm", _to_vite_fs_url(himari_vrm_file)))
    if himari_display_name:
        payload.append(("himari_name", himari_display_name.strip()))
    for motion in himari_idle_motion_files or []:
        payload.append(("himari_idle", _to_vite_fs_url(motion)))
    if himari_thinking_motion_file is not None and himari_thinking_motion_file.is_file():
        payload.append(("himari_thinking", _to_vite_fs_url(himari_thinking_motion_file)))
    if himari_idle_skip_sec is not None and himari_idle_skip_sec > 0:
        payload.append(("himari_idle_skip_sec", str(himari_idle_skip_sec)))
    if luna_idle_skip_sec is not None and luna_idle_skip_sec > 0:
        payload.append(("luna_idle_skip_sec", str(luna_idle_skip_sec)))
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


def _start_vite_app(app_dir: Path, port: int, *, label: str) -> subprocess.Popen[str]:
    """Run `vite` dev server (HMR). Requires Node and app_dir/node_modules."""
    if sys.platform == "win32":
        vite = app_dir / "node_modules" / ".bin" / "vite.cmd"
    else:
        vite = app_dir / "node_modules" / ".bin" / "vite"
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
    print(f"Starting Vite dev server for {label} in {app_dir} ...")
    return subprocess.Popen(
        cmd,
        cwd=str(app_dir),
        stdin=subprocess.DEVNULL,
        stdout=None,
        stderr=None,
        text=True,
    )


def _start_viewer_vite(viewer_dir: Path, port: int) -> subprocess.Popen[str]:
    return _start_vite_app(viewer_dir, port, label="viewer")


def _website_page_url(port: int, chat_ws: str | None) -> str:
    if chat_ws:
        query = urllib.parse.urlencode({"chat_ws": chat_ws})
        return f"http://127.0.0.1:{port}/?{query}"
    return f"http://127.0.0.1:{port}/"


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
        help="Do not open the viewer in a browser (default opens Brave).",
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
        "--website",
        action="store_true",
        help="Open the marketing site (website/) instead of the VRM viewer.",
    )
    parser.add_argument(
        "--website-port",
        type=int,
        default=5180,
        help="Marketing site port when using --website (default 5180).",
    )
    parser.add_argument(
        "--with-viewer",
        action="store_true",
        help="With --website, also start the VRM viewer on --port.",
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
    website_dir = root_dir / "website"
    viewer_dist = viewer_dir / "dist"
    website_dist = website_dir / "dist"
    expressions_dir = args.expressions_dir.resolve()
    cohost_expressions_dir = args.cohost_expressions_dir.resolve()
    active_port = args.port
    website_port = args.website_port
    launch_website = args.website
    launch_viewer = not launch_website or args.with_viewer
    base_url = f"http://127.0.0.1:{active_port}/"
    website_base_url = f"http://127.0.0.1:{website_port}/"

    if launch_viewer:
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
            print(
                f"No package.json in {viewer_dir}; use --static with a built dist.",
                file=sys.stderr,
            )
            sys.exit(1)
    if launch_website:
        if not website_dir.is_dir():
            print(f"Website folder not found: {website_dir}", file=sys.stderr)
            sys.exit(1)
        if not (website_dir / "package.json").is_file():
            print(
                f"No package.json in {website_dir}; run: cd website && npm install",
                file=sys.stderr,
            )
            sys.exit(1)

    if launch_viewer:
        print(f"Viewer dir: {viewer_dir}")
        print(f"Default VRM: {vrm_file}")
    if launch_website:
        print(f"Website dir: {website_dir}")
    luna_thinking_motion_file: Path | None = None
    if expressions_dir.is_dir():
        luna_thinking_motion_file = expressions_dir / "thinking.vrma"
        if not luna_thinking_motion_file.is_file():
            luna_thinking_motion_file = None
        idle_motion_files = sorted(
            p
            for p in expressions_dir.glob("**/*.vrma")
            if p.name.lower() != "thinking.vrma"
        )
    else:
        idle_motion_files = []
    think_note = (
        f", thinking={luna_thinking_motion_file.name}"
        if luna_thinking_motion_file
        else ""
    )
    print(f"Idle motions found: {len(idle_motion_files)} in {expressions_dir}{think_note}")
    cohost_thinking_motion_file: Path | None = None
    if cohost_expressions_dir.is_dir():
        cohost_thinking_motion_file = cohost_expressions_dir / "thinking.vrma"
        if not cohost_thinking_motion_file.is_file():
            cohost_thinking_motion_file = None
        cohost_idle_motion_files = sorted(
            p
            for p in cohost_expressions_dir.glob("**/*.vrma")
            if p.name.lower() != "thinking.vrma"
        )
    else:
        cohost_idle_motion_files = []
    cohost_think_note = (
        f", thinking={cohost_thinking_motion_file.name}"
        if cohost_thinking_motion_file
        else ""
    )
    print(
        f"Co-host idle motions: {len(cohost_idle_motion_files)} in {cohost_expressions_dir}{cohost_think_note}",
    )

    viewer_server: http.server.ThreadingHTTPServer | None = None
    viewer_proc: subprocess.Popen[str] | None = None
    website_proc: subprocess.Popen[str] | None = None
    bot_proc: subprocess.Popen[str] | None = None

    viewer_already_running = launch_viewer and _url_alive(base_url)
    if launch_viewer and not viewer_already_running and _port_open("127.0.0.1", active_port):
        active_port = _find_free_port("127.0.0.1", active_port + 1)
        base_url = f"http://127.0.0.1:{active_port}/"
        print(
            f"Port {args.port} is occupied by another process. "
            f"Using fallback port {active_port}."
        )
    website_already_running = launch_website and _url_alive(website_base_url)
    if (
        launch_website
        and not website_already_running
        and _port_open("127.0.0.1", website_port)
    ):
        website_port = _find_free_port("127.0.0.1", website_port + 1)
        website_base_url = f"http://127.0.0.1:{website_port}/"
        print(
            f"Website port {args.website_port} is occupied. "
            f"Using fallback port {website_port}."
        )
    chat_ws_port = int(os.environ.get("LUNA_CHAT_WS_PORT", "8765").strip() or "8765")
    chat_ws_url = (
        f"ws://127.0.0.1:{chat_ws_port}/ws" if chat_ws_port > 0 else None
    )
    cohost_vrm: Path | None = None
    cohost_name: str | None = None
    himari_vrm: Path | None = None
    himari_name: str | None = None
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
    himari_idle_motion_files: list[Path] = []
    himari_thinking_motion_file: Path | None = None
    try:
        from himari_cohost import (
            himari_enabled,
            himari_idle_vrma_paths,
            himari_name as _himari_name,
            himari_thinking_vrma_path,
            himari_vrm_path,
        )

        if himari_enabled():
            himari_name = _himari_name()
            hp = himari_vrm_path()
            if hp.is_file():
                himari_vrm = hp
                print(
                    f"Himari VRM (summon from viewer dock): {himari_vrm} ({himari_name})"
                )
            from himari_cohost import himari_expressions_dir

            himari_idle_motion_files = himari_idle_vrma_paths()
            himari_thinking_motion_file = himari_thinking_vrma_path()
            if himari_idle_motion_files or himari_thinking_motion_file:
                print(
                    f"Himari expressions: {len(himari_idle_motion_files)} idle in "
                    f"{himari_expressions_dir()}"
                    + (
                        f", thinking={himari_thinking_motion_file.name}"
                        if himari_thinking_motion_file
                        else ""
                    ),
                )
    except Exception:
        himari_vrm = None
        himari_name = None
        himari_idle_motion_files = []
        himari_thinking_motion_file = None

    _idle_skip_raw = (os.environ.get("LUNA_IDLE_SKIP_SEC") or "").strip()
    if not _idle_skip_raw:
        _idle_skip_raw = (os.environ.get("LUNA_COHOST_IDLE_SKIP_SEC") or "2").strip() or "2"
    try:
        idle_skip_sec = max(0.0, float(_idle_skip_raw))
    except ValueError:
        idle_skip_sec = 2.0

    page_url = ""
    if launch_viewer:
        page_url = _viewer_page_url(
            active_port,
            vrm_file,
            idle_motion_files,
            cohost_idle_motion_files=cohost_idle_motion_files,
            chat_ws=chat_ws_url,
            cohost_vrm_file=cohost_vrm,
            cohost_display_name=cohost_name,
            cohost_idle_skip_sec=idle_skip_sec,
            cohost_thinking_motion_file=cohost_thinking_motion_file,
            himari_vrm_file=himari_vrm,
            himari_display_name=himari_name,
            himari_idle_motion_files=himari_idle_motion_files,
            himari_thinking_motion_file=himari_thinking_motion_file,
            himari_idle_skip_sec=idle_skip_sec,
            luna_idle_skip_sec=idle_skip_sec,
            luna_thinking_motion_file=luna_thinking_motion_file,
        )
    website_page_url = _website_page_url(website_port, chat_ws_url)
    if viewer_already_running:
        print(f"Viewer already running at {base_url}")
    if website_already_running:
        print(f"Website already running at {website_base_url}")
    try:
        if launch_viewer and not viewer_already_running:
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

        if launch_website and not website_already_running:
            website_proc = _start_vite_app(website_dir, website_port, label="website")
            time.sleep(0.6)
            if website_proc.poll() is not None:
                raise RuntimeError(
                    "Website Vite exited immediately. Install deps: cd website && npm install"
                )
            start = time.time()
            while not _port_open("127.0.0.1", website_port):
                if time.time() - start > 45:
                    raise TimeoutError("Website startup timed out.")
                time.sleep(0.35)
            print(f"Website ready at {website_base_url}")

        if not args.no_open:
            open_url = website_page_url if launch_website and not launch_viewer else page_url
            if launch_website and launch_viewer and args.with_viewer:
                _open_viewer_in_browser(page_url)
                _open_viewer_in_browser(website_page_url)
            elif open_url:
                _open_viewer_in_browser(open_url)

        should_start_bot = not args.viewer_only and not args.no_bot
        if should_start_bot:
            bot_proc = _start_twitch_bot(root_dir)

        ui_already_up = (viewer_already_running and launch_viewer) or (
            website_already_running and launch_website
        )
        if ui_already_up and bot_proc is None:
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
        if website_proc is not None:
            _terminate_process(website_proc, "Website dev server")
        if viewer_proc is not None:
            _terminate_process(viewer_proc, "Vite dev server")
        if viewer_server is not None:
            print("Stopping viewer...")
            viewer_server.shutdown()
            viewer_server.server_close()


if __name__ == "__main__":
    main()

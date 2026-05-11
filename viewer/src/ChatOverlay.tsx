import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
} from "react";
import { useBridge } from "./chatBridgeContext";
import { CloseIcon, MinimizeIcon, SendIcon } from "./icons";

type Props = {
  /** Hide the overlay entirely (dock toggle). */
  onClose: () => void;
};

type Position = { x: number; y: number } | null;
type Size = { w: number; h: number } | null;

const POSITION_STORAGE_KEY = "luna.chatCard.pos.v2";
const SIZE_STORAGE_KEY = "luna.chatCard.size.v2";
const MIN_W = 280;
const MIN_H = 220;

function readJSON<T>(key: string, valid: (v: unknown) => v is T): T | null {
  try {
    const raw = window.localStorage.getItem(key);
    if (!raw) return null;
    const parsed: unknown = JSON.parse(raw);
    if (valid(parsed)) return parsed;
  } catch {
    /* ignore */
  }
  return null;
}

function isPosition(v: unknown): v is { x: number; y: number } {
  return (
    typeof v === "object" &&
    v !== null &&
    typeof (v as { x?: unknown }).x === "number" &&
    typeof (v as { y?: unknown }).y === "number"
  );
}

function isSize(v: unknown): v is { w: number; h: number } {
  return (
    typeof v === "object" &&
    v !== null &&
    typeof (v as { w?: unknown }).w === "number" &&
    typeof (v as { h?: unknown }).h === "number"
  );
}

function clampPosition(pos: { x: number; y: number }, w: number, h: number) {
  const maxX = Math.max(0, window.innerWidth - w);
  const maxY = Math.max(0, window.innerHeight - h);
  return {
    x: Math.max(0, Math.min(maxX, pos.x)),
    y: Math.max(0, Math.min(maxY, pos.y)),
  };
}

/**
 * Floating, draggable, resizable, minimizable chat card.
 *
 * Header drag → move. Bottom-left corner handle → resize. Position and size
 * persist in localStorage and are clamped on window resize so the card never
 * slips offscreen. Clicking a header action button does NOT start a drag.
 */
export function ChatOverlay({ onClose }: Props) {
  const {
    lines,
    conn,
    sendPrompt,
    sendPlayRequest,
    sendYouTubeSummary,
    addStatusLine,
    clear,
  } = useBridge();
  const [prompt, setPrompt] = useState("");
  const [minimized, setMinimized] = useState(false);
  const [position, setPosition] = useState<Position>(() =>
    readJSON(POSITION_STORAGE_KEY, isPosition),
  );
  const [size, setSize] = useState<Size>(() => readJSON(SIZE_STORAGE_KEY, isSize));
  const [dragging, setDragging] = useState<"move" | "resize" | null>(null);

  const cardRef = useRef<HTMLDivElement>(null);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (minimized) return;
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, minimized]);

  // Persist position + size (debounced — drag fires many state updates).
  useEffect(() => {
    if (!position) return;
    const t = window.setTimeout(() => {
      try {
        window.localStorage.setItem(POSITION_STORAGE_KEY, JSON.stringify(position));
      } catch {
        /* ignore */
      }
    }, 200);
    return () => window.clearTimeout(t);
  }, [position]);

  useEffect(() => {
    if (!size) return;
    const t = window.setTimeout(() => {
      try {
        window.localStorage.setItem(SIZE_STORAGE_KEY, JSON.stringify(size));
      } catch {
        /* ignore */
      }
    }, 200);
    return () => window.clearTimeout(t);
  }, [size]);

  // Re-clamp on window resize so the card can't end up offscreen if the
  // browser window shrinks underneath it.
  useEffect(() => {
    const onResize = () => {
      const card = cardRef.current;
      if (!card) return;
      const w = size?.w ?? card.offsetWidth;
      const h = minimized ? card.offsetHeight : size?.h ?? card.offsetHeight;
      setPosition((cur) => (cur ? clampPosition(cur, w, h) : cur));
    };
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [minimized, size]);

  // Drag-to-move from the header.
  const startMove = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    // Ignore drags that originate on buttons / inputs inside the header.
    if ((e.target as HTMLElement).closest("button, input, select, textarea")) return;
    e.preventDefault();
    const card = cardRef.current;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const startX = e.clientX;
    const startY = e.clientY;
    const origX = rect.left;
    const origY = rect.top;
    const w = rect.width;
    const h = rect.height;
    setDragging("move");
    try {
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }

    const onMove = (ev: PointerEvent) => {
      const next = clampPosition(
        { x: origX + (ev.clientX - startX), y: origY + (ev.clientY - startY) },
        w,
        h,
      );
      setPosition(next);
    };
    const onUp = () => {
      setDragging(null);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }, []);

  // Drag-to-resize from the bottom-left corner. We grow leftward (so the
  // right edge stays put) and downward (so the top edge stays put), which
  // matches where the handle visually pokes out.
  const startResize = useCallback((e: ReactPointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    const card = cardRef.current;
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const startX = e.clientX;
    const startY = e.clientY;
    const startW = rect.width;
    const startH = rect.height;
    const rightEdge = rect.right;
    setDragging("resize");
    try {
      (e.currentTarget as Element).setPointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }

    const onMove = (ev: PointerEvent) => {
      // Movement to the left (negative dx) grows the card.
      const dx = startX - ev.clientX;
      const dy = ev.clientY - startY;
      const maxW = Math.max(MIN_W, rightEdge);
      const maxH = Math.max(MIN_H, window.innerHeight - rect.top);
      const w = Math.max(MIN_W, Math.min(maxW, startW + dx));
      const h = Math.max(MIN_H, Math.min(maxH, startH + dy));
      setSize({ w, h });
      // Card's right edge stays anchored: new left = rightEdge - w.
      setPosition({ x: Math.max(0, rightEdge - w), y: rect.top });
    };
    const onUp = () => {
      setDragging(null);
      window.removeEventListener("pointermove", onMove);
      window.removeEventListener("pointerup", onUp);
      window.removeEventListener("pointercancel", onUp);
    };
    window.addEventListener("pointermove", onMove);
    window.addEventListener("pointerup", onUp);
    window.addEventListener("pointercancel", onUp);
  }, []);

  const resetLayout = useCallback(() => {
    setPosition(null);
    setSize(null);
    try {
      window.localStorage.removeItem(POSITION_STORAGE_KEY);
      window.localStorage.removeItem(SIZE_STORAGE_KEY);
    } catch {
      /* ignore */
    }
  }, []);

  const submit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const trimmed = prompt.trim();
    if (!trimmed) return;
    if (trimmed.toLowerCase().startsWith("/play ")) {
      const q = trimmed.slice("/play ".length).trim();
      const ok = await sendPlayRequest(q);
      if (ok) setPrompt("");
      else addStatusLine("!play failed: chat bridge socket not ready.");
      return;
    }
    if (
      trimmed.toLowerCase().startsWith("/explain ") ||
      trimmed.toLowerCase().startsWith("/yt ")
    ) {
      const u = trimmed.replace(/^\/(explain|yt)\s+/i, "").trim();
      const ok = await sendYouTubeSummary(u);
      if (ok) setPrompt("");
      else addStatusLine("!explain failed: chat bridge socket not ready.");
      return;
    }
    const ok = await sendPrompt(trimmed);
    if (ok) {
      setPrompt("");
    } else {
      addStatusLine(
        "Send failed: chat bridge socket not ready. Wait for ● live, or refresh if this persists.",
      );
    }
  };

  const connLabel =
    conn === "open" ? "● live" : conn === "connecting" ? "◌ connecting…" : "○ offline";

  const style: CSSProperties = {};
  if (position) {
    style.left = position.x;
    style.top = position.y;
    style.right = "auto";
    style.bottom = "auto";
  }
  if (size && !minimized) {
    style.width = size.w;
    style.height = size.h;
    style.maxHeight = size.h;
  }

  return (
    <div
      ref={cardRef}
      className={`chat-card ${minimized ? "chat-card--min" : ""} ${
        dragging ? `chat-card--${dragging}` : ""
      }`}
      style={style}
    >
      <div
        className="chat-card-header chat-card-header--drag"
        onPointerDown={startMove}
        onDoubleClick={resetLayout}
        title="Drag to move · Double-click to reset position & size"
      >
        <span className={`chat-card-title chat-conn--${conn}`}>
          Chat with Luna · <span className="chat-card-conn">{connLabel}</span>
        </span>
        <div className="chat-card-header-actions">
          <button
            type="button"
            className="chat-card-icon-btn"
            onClick={clear}
            disabled={lines.length === 0}
            title="Clear chat history"
          >
            clear
          </button>
          <button
            type="button"
            className="chat-card-icon-btn"
            onClick={() => setMinimized((v) => !v)}
            title={minimized ? "Expand chat" : "Minimize chat"}
            aria-label={minimized ? "Expand chat" : "Minimize chat"}
          >
            <MinimizeIcon />
          </button>
          <button
            type="button"
            className="chat-card-icon-btn"
            onClick={onClose}
            title="Hide chat"
            aria-label="Hide chat"
          >
            <CloseIcon />
          </button>
        </div>
      </div>

      {!minimized && (
        <>
          <div
            className="chat-feed"
            role="log"
            aria-live="polite"
            aria-relevant="additions"
          >
            {lines.length === 0 && (
              <div className="chat-empty">
                Talk to Luna here. Tips: <code className="chat-code">/play &lt;query&gt;</code>,{" "}
                <code className="chat-code">/explain &lt;url&gt;</code>.
              </div>
            )}
            {lines.map((row) => (
              <div key={row.id} className={`chat-line chat-line--${row.kind}`}>
                {row.kind === "status" && (
                  <span className="chat-status">{row.text}</span>
                )}
                {row.kind === "chat" && (
                  <>
                    <span className="chat-user">{row.user}</span>
                    {row.channel ? (
                      <span className="chat-channel"> {row.channel}</span>
                    ) : null}
                    <span className="chat-sep">: </span>
                    <span className="chat-text">{row.text}</span>
                  </>
                )}
                {row.kind === "assistant" && (
                  <>
                    <span className="chat-assistant-label">{row.user}</span>
                    <span className="chat-assistant-body">{row.text}</span>
                  </>
                )}
              </div>
            ))}
            <div ref={endRef} />
          </div>

          <form className="chat-input-row" onSubmit={submit}>
            <input
              className="chat-input"
              value={prompt}
              onChange={(e) => setPrompt(e.target.value)}
              placeholder="Talk to Luna…"
              autoComplete="off"
            />
            <button
              type="submit"
              className="chat-send-btn"
              disabled={conn !== "open" || prompt.trim().length === 0}
              aria-label="Send message"
              title="Send"
            >
              <SendIcon />
            </button>
          </form>

          <div
            className="chat-card-resize"
            onPointerDown={startResize}
            title="Drag to resize"
            aria-label="Resize chat"
            role="separator"
          />
        </>
      )}
    </div>
  );
}

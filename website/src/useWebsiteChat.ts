import { useCallback, useEffect, useRef, useState } from "react";
import {
  type CastId,
  castById,
  matchAssistantToCast,
} from "./characters";
import { parseBridgeMessage } from "./chatTypes";
import { cannedReplyDelayMs, pickCannedReply } from "./pickCannedReply";

const DEFAULT_WS = "ws://127.0.0.1:8765/ws";
const MAX_LINES = 120;
const RECONNECT_MS = 500;
const WS_PROBE_MS = 2200;

export type ChatLine =
  | { id: string; kind: "status"; text: string; ts: number }
  | { id: string; kind: "user"; text: string; ts: number }
  | {
      id: string;
      kind: "assistant";
      text: string;
      ts: number;
      streaming?: boolean;
    };

export type ConnState = "connecting" | "open" | "closed";

/** Live bridge to stream PC, or offline canned persona lines. */
export type ChatMode = "connecting" | "live" | "canned";

function wsUrl(): string {
  try {
    const q = new URLSearchParams(window.location.search).get("chat_ws");
    if (q?.trim().startsWith("ws")) return q.trim();
  } catch {
    /* ignore */
  }
  const env = import.meta.env.VITE_CHAT_WS_URL;
  if (typeof env === "string" && env.trim()) return env.trim();
  return DEFAULT_WS;
}

function readPreferCanned(): boolean {
  const raw = (import.meta.env.VITE_CHAT_CANNED_ONLY || "").trim().toLowerCase();
  return ["1", "true", "yes", "on"].includes(raw);
}

let idCounter = 0;
function nextId() {
  idCounter += 1;
  return `${Date.now()}-${idCounter}`;
}

function append(prev: ChatLine[], row: ChatLine): ChatLine[] {
  const next = [...prev, row];
  return next.length > MAX_LINES ? next.slice(-MAX_LINES) : next;
}

export function useWebsiteChat() {
  const [conn, setConn] = useState<ConnState>("closed");
  const [chatMode, setChatMode] = useState<ChatMode>("connecting");
  const [messages, setMessages] = useState<Record<CastId, ChatLine[]>>({
    luna: [],
    himari: [],
    viktor: [],
  });
  const [thinking, setThinking] = useState<Record<CastId, boolean>>({
    luna: false,
    himari: false,
    viktor: false,
  });

  const wsRef = useRef<WebSocket | null>(null);
  const timerRef = useRef<number>(0);
  const modeRef = useRef<ChatMode>("connecting");
  const pendingRef = useRef<CastId | null>(null);
  const cannedOnly = readPreferCanned();
  const bridgeUrl = wsUrl();

  const setThinkingForCast = useCallback((cast: CastId, active: boolean) => {
    setThinking((p) => ({ ...p, [cast]: active }));
  }, []);

  const pushToCast = useCallback((cast: CastId, row: ChatLine) => {
    setMessages((p) => ({ ...p, [cast]: append(p[cast], row) }));
  }, []);

  const replyCanned = useCallback(
    (castId: CastId, userText: string) => {
      const delay = cannedReplyDelayMs(userText);
      window.setTimeout(() => {
        const reply = pickCannedReply(castId, userText);
        setThinkingForCast(castId, false);
        pushToCast(castId, {
          id: nextId(),
          kind: "assistant",
          text: reply,
          ts: Date.now(),
        });
        pendingRef.current = null;
      }, delay);
    },
    [pushToCast, setThinkingForCast],
  );

  const handleParsed = useCallback(
    (msg: ReturnType<typeof parseBridgeMessage>) => {
      if (!msg) return;
      const ts = Date.now();

      if (msg.type === "status") {
        if (chatMode === "live") {
          for (const c of ["luna", "himari", "viktor"] as CastId[]) {
            pushToCast(c, { id: nextId(), kind: "status", text: msg.text, ts });
          }
        }
        return;
      }

      if (msg.type === "chat" && msg.channel === "panel") {
        const target = pendingRef.current;
        if (target) {
          pushToCast(target, {
            id: nextId(),
            kind: "user",
            text: msg.text,
            ts: msg.ts ?? ts,
          });
        }
        return;
      }

      if (msg.type === "assistant_delta" || msg.type === "assistant") {
        const cast = matchAssistantToCast(msg.user) ?? pendingRef.current;
        if (!cast) return;

        if (msg.type === "assistant_delta") {
          setThinkingForCast(cast, true);
          setMessages((p) => {
            const lines = p[cast];
            const last = lines[lines.length - 1];
            if (last?.kind === "assistant" && last.streaming) {
              const updated = [...lines];
              updated[updated.length - 1] = {
                ...last,
                text: last.text + msg.text,
              };
              return { ...p, [cast]: updated };
            }
            return {
              ...p,
              [cast]: append(lines, {
                id: nextId(),
                kind: "assistant",
                text: msg.text,
                ts,
                streaming: true,
              }),
            };
          });
          return;
        }

        setThinkingForCast(cast, false);
        setMessages((p) => {
          const lines = p[cast];
          const last = lines[lines.length - 1];
          if (last?.kind === "assistant" && last.streaming) {
            const updated = [...lines];
            updated[updated.length - 1] = {
              ...last,
              text: msg.text,
              streaming: false,
            };
            return { ...p, [cast]: updated };
          }
          return {
            ...p,
            [cast]: append(lines, {
              id: nextId(),
              kind: "assistant",
              text: msg.text,
              ts: msg.ts ?? ts,
            }),
          };
        });
        pendingRef.current = null;
      }
    },
    [chatMode, pushToCast, setThinkingForCast],
  );

  useEffect(() => {
    if (cannedOnly) {
      modeRef.current = "canned";
      setChatMode("canned");
      setConn("closed");
      return;
    }

    let cancelled = false;

    const goCanned = () => {
      if (cancelled) return;
      modeRef.current = "canned";
      setConn("closed");
      setChatMode("canned");
      wsRef.current = null;
    };

    const connect = () => {
      if (cancelled || modeRef.current === "canned") return;
      setConn("connecting");
      setChatMode("connecting");

      const ws = new WebSocket(bridgeUrl);
      wsRef.current = ws;

      const probe = window.setTimeout(() => {
        if (cancelled || ws.readyState === WebSocket.OPEN) return;
        try {
          ws.close();
        } catch {
          /* ignore */
        }
        goCanned();
      }, WS_PROBE_MS);

      ws.onopen = () => {
        if (cancelled) return;
        window.clearTimeout(probe);
        modeRef.current = "live";
        setConn("open");
        setChatMode("live");
      };

      ws.onmessage = (ev) => {
        try {
          const raw: unknown = JSON.parse(String(ev.data));
          handleParsed(parseBridgeMessage(raw));
        } catch {
          /* ignore */
        }
      };

      ws.onclose = () => {
        if (cancelled) return;
        window.clearTimeout(probe);
        if (modeRef.current === "live") {
          setConn("closed");
          timerRef.current = window.setTimeout(connect, RECONNECT_MS);
          return;
        }
        goCanned();
      };

      ws.onerror = () => {
        window.clearTimeout(probe);
        ws.close();
      };
    };

    connect();
    return () => {
      cancelled = true;
      window.clearTimeout(timerRef.current);
      wsRef.current?.close();
      wsRef.current = null;
    };
  }, [bridgeUrl, cannedOnly, handleParsed]);

  const sendPrompt = useCallback(
    async (castId: CastId, text: string): Promise<boolean> => {
      const message = text.trim();
      if (!message) return false;

      pendingRef.current = castId;
      setThinkingForCast(castId, true);

      pushToCast(castId, {
        id: nextId(),
        kind: "user",
        text: message,
        ts: Date.now(),
      });

      if (modeRef.current === "canned" || cannedOnly) {
        replyCanned(castId, message);
        return true;
      }

      let ws = wsRef.current;
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        await new Promise((r) => window.setTimeout(r, 300));
        ws = wsRef.current;
      }
      if (!ws || ws.readyState !== WebSocket.OPEN) {
        replyCanned(castId, message);
        return true;
      }

      ws.send(
        JSON.stringify({
          type: "viewer_prompt",
          text: message,
          reply_to: castById(castId).replyTo,
        }),
      );
      return true;
    },
    [cannedOnly, pushToCast, replyCanned, setThinkingForCast],
  );

  const clearCast = useCallback((castId: CastId) => {
    setMessages((p) => ({ ...p, [castId]: [] }));
    setThinking((p) => ({ ...p, [castId]: false }));
  }, []);

  return {
    conn,
    chatMode,
    bridgeUrl,
    messages,
    thinking,
    sendPrompt,
    clearCast,
  };
}

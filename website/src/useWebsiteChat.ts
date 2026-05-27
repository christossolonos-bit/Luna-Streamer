import { useCallback, useRef, useState } from "react";
import { type CastId } from "./characters";
import { cannedReplyDelayMs, pickCannedReply } from "./pickCannedReply";

const MAX_LINES = 120;

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

  const pendingRef = useRef<CastId | null>(null);

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

      replyCanned(castId, message);
      return true;
    },
    [pushToCast, replyCanned, setThinkingForCast],
  );

  const clearCast = useCallback((castId: CastId) => {
    setMessages((p) => ({ ...p, [castId]: [] }));
    setThinking((p) => ({ ...p, [castId]: false }));
  }, []);

  return {
    messages,
    thinking,
    sendPrompt,
    clearCast,
  };
}

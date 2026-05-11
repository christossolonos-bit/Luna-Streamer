import { useEffect, useRef, useState } from "react";
import { useBridge } from "./chatBridgeContext";

/** ms of idle (no new tokens / no new reply) before captions fade out. */
const CAPTION_HIDE_MS = 8000;
/** Cap how many characters live on screen so long replies don't dominate. */
const CAPTION_MAX_CHARS = 320;

type Props = {
  /** Off hides captions entirely (toggle from the dock). */
  enabled: boolean;
};

/**
 * Live caption overlay floating just above the dock. Mirrors the latest
 * assistant turn from the chat bridge (streaming tokens included), then fades
 * out after a short idle window so the avatar isn't permanently covered.
 *
 * Source-agnostic: shows whatever Luna last replied, whether it came from
 * Twitch chat, the viewer panel, the viewer mic, or Discord.
 */
export function CaptionsOverlay({ enabled }: Props) {
  const { lines } = useBridge();
  const [text, setText] = useState("");
  const [show, setShow] = useState(false);
  const hideTimerRef = useRef<number>(0);

  useEffect(() => {
    if (!enabled) return;
    let latest: { text: string; streaming: boolean } | null = null;
    for (let i = lines.length - 1; i >= 0; i--) {
      const row = lines[i]!;
      if (row.kind === "assistant" && row.text.trim().length > 0) {
        latest = { text: row.text, streaming: Boolean(row.streaming) };
        break;
      }
    }
    if (!latest) return;
    setText(latest.text);
    setShow(true);

    if (hideTimerRef.current) {
      window.clearTimeout(hideTimerRef.current);
      hideTimerRef.current = 0;
    }
    if (!latest.streaming) {
      hideTimerRef.current = window.setTimeout(() => setShow(false), CAPTION_HIDE_MS);
    }

    return () => {
      // No-op cleanup — the timer is cleared at the top of the next effect.
    };
  }, [enabled, lines]);

  useEffect(() => {
    if (!enabled) {
      setShow(false);
      if (hideTimerRef.current) {
        window.clearTimeout(hideTimerRef.current);
        hideTimerRef.current = 0;
      }
    }
  }, [enabled]);

  useEffect(() => {
    return () => {
      if (hideTimerRef.current) window.clearTimeout(hideTimerRef.current);
    };
  }, []);

  if (!enabled || !show || !text) return null;

  const display =
    text.length > CAPTION_MAX_CHARS
      ? `${text.slice(text.length - CAPTION_MAX_CHARS).replace(/^\S*\s/, "")}`
      : text;

  return (
    <div className="captions" role="status" aria-live="polite">
      <div className="captions-text">{display}</div>
    </div>
  );
}

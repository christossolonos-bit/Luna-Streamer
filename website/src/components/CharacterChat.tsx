import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type FormEvent,
} from "react";
import type { CastProfile } from "../characters";
import type { ChatLine } from "../useWebsiteChat";

type Props = {
  cast: CastProfile;
  lines: ChatLine[];
  thinking: boolean;
  onSend: (text: string) => Promise<boolean>;
  onClear: () => void;
};

export function CharacterChat({
  cast,
  lines,
  thinking,
  onSend,
  onClear,
}: Props) {
  const [draft, setDraft] = useState("");
  const [sending, setSending] = useState(false);
  const endRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [lines, thinking]);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!draft.trim() || sending) return;
    setSending(true);
    await onSend(draft);
    setDraft("");
    setSending(false);
  };

  return (
    <article
      className="chat-card"
      style={
        {
          "--cast-accent": cast.accent,
          "--cast-glow": cast.glow,
        } as CSSProperties
      }
    >
      <header className="chat-card__head">
        <div className="chat-card__avatar" aria-hidden>
          {cast.name.charAt(0)}
        </div>
        <div className="chat-card__meta">
          <h3>{cast.name}</h3>
          <p>{cast.title}</p>
        </div>
      </header>

      <div className="chat-card__log" role="log" aria-live="polite">
        {lines.length === 0 ? (
          <p className="chat-card__empty">
            Say hello to {cast.name} — demo replies work anytime, no stream PC needed.
          </p>
        ) : (
          lines.map((line) => (
            <div
              key={line.id}
              className={`chat-bubble chat-bubble--${line.kind}`}
            >
              {line.kind === "status" ? (
                <span className="chat-bubble__status">{line.text}</span>
              ) : line.kind === "user" ? (
                <p>{line.text}</p>
              ) : (
                <p>
                  {line.text}
                  {line.streaming ? (
                    <span className="chat-bubble__cursor" aria-hidden>
                      ▍
                    </span>
                  ) : null}
                </p>
              )}
            </div>
          ))
        )}
        {thinking ? (
          <div className="chat-bubble chat-bubble--assistant chat-bubble--typing">
            <span className="typing-dots">
              <span />
              <span />
              <span />
            </span>
          </div>
        ) : null}
        <div ref={endRef} />
      </div>

      <form className="chat-card__form" onSubmit={submit}>
        <input
          type="text"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          placeholder={`Message ${cast.name}…`}
          disabled={sending}
          autoComplete="off"
          aria-label={`Message ${cast.name}`}
        />
        <button type="submit" disabled={sending || !draft.trim()}>
          Send
        </button>
      </form>
      <button type="button" className="chat-card__clear" onClick={onClear}>
        Clear chat
      </button>
    </article>
  );
}

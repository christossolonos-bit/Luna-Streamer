import type { ChatMode, ConnState } from "../useWebsiteChat";

type Props = {
  conn: ConnState;
  chatMode: ChatMode;
};

export function ChatAvailability({ conn, chatMode }: Props) {
  const live = chatMode === "live" && conn === "open";
  const canned = chatMode === "canned";

  return (
    <div
      className={`chat-availability ${live ? "chat-availability--live" : canned ? "chat-availability--canned" : ""}`}
      role="status"
    >
      <span className="chat-availability__dot" aria-hidden />
      <div>
        <strong>
          {live
            ? "Live Luna stack connected"
            : canned
              ? "Demo chat (pre-written)"
              : "Connecting…"}
        </strong>
        <p>
          {live ? (
            <>
              Replies come from the real bot on the stream PC — same as the VRM
              viewer.
            </>
          ) : canned ? (
            <>
              No cloud and no PC required. Luna, Himari, and Viktor answer from
              curated lines that match what you type. Run <code>main.py</code>{" "}
              locally if you want full AI instead.
            </>
          ) : (
            <>Checking for a local bridge…</>
          )}
        </p>
      </div>
    </div>
  );
}

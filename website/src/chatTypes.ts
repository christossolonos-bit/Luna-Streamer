/** Minimal bridge parser for the marketing site (subset of viewer/chatTypes.ts). */

export type BridgeChatMessage = {
  type: "chat";
  user: string;
  text: string;
  channel: string;
  ts?: number;
};

export type BridgeAssistantMessage = {
  type: "assistant";
  user: string;
  text: string;
  channel: string;
  ts?: number;
};

export type BridgeAssistantDeltaMessage = {
  type: "assistant_delta";
  user: string;
  text: string;
  channel: string;
};

export type BridgeStatusMessage = {
  type: "status";
  text: string;
};

export type BridgeMessage =
  | BridgeChatMessage
  | BridgeAssistantMessage
  | BridgeAssistantDeltaMessage
  | BridgeStatusMessage;

export function parseBridgeMessage(raw: unknown): BridgeMessage | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  const t = o.type;
  if (t === "status" && typeof o.text === "string") {
    return { type: "status", text: o.text };
  }
  if (
    t === "chat" &&
    typeof o.user === "string" &&
    typeof o.text === "string" &&
    typeof o.channel === "string"
  ) {
    return {
      type: "chat",
      user: o.user,
      text: o.text,
      channel: o.channel,
      ts: typeof o.ts === "number" ? o.ts : undefined,
    };
  }
  if (
    t === "assistant" &&
    typeof o.user === "string" &&
    typeof o.text === "string" &&
    typeof o.channel === "string"
  ) {
    return {
      type: "assistant",
      user: o.user,
      text: o.text,
      channel: o.channel,
      ts: typeof o.ts === "number" ? o.ts : undefined,
    };
  }
  if (
    t === "assistant_delta" &&
    typeof o.user === "string" &&
    typeof o.text === "string" &&
    typeof o.channel === "string"
  ) {
    return {
      type: "assistant_delta",
      user: o.user,
      text: o.text,
      channel: o.channel,
    };
  }
  return null;
}

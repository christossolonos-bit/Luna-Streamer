import { createContext, useContext, type ReactNode } from "react";
import { useChatBridge } from "./useChatBridge";

/** Result of the singleton chat bridge hook, shared with every child via context. */
export type ChatBridge = ReturnType<typeof useChatBridge>;

const ChatBridgeContext = createContext<ChatBridge | null>(null);

type ProviderProps = {
  children: ReactNode;
  enabled?: boolean;
};

/**
 * Wrap the app once at the root so the dock, captions, chat overlay, and
 * settings overlay all observe the SAME WebSocket / chat lines / TTS state.
 * Calling `useChatBridge` in multiple places would open multiple sockets and
 * keep multiple copies of the chat history in sync independently.
 */
export function ChatBridgeProvider({ children, enabled = true }: ProviderProps) {
  const bridge = useChatBridge(enabled);
  return <ChatBridgeContext.Provider value={bridge}>{children}</ChatBridgeContext.Provider>;
}

export function useBridge(): ChatBridge {
  const ctx = useContext(ChatBridgeContext);
  if (!ctx) {
    throw new Error("useBridge must be used inside <ChatBridgeProvider>.");
  }
  return ctx;
}

import { atom, map } from "nanostores";

// Message kinds (kept minimal — chat-side state only; tool call UI is
// driven by the `useChatStream` hook which writes into this store).
export type MessageRole = "user" | "assistant" | "system";
export interface ChatMessage {
  id: string;
  role: MessageRole;
  content: string;
  ts: number;
}

export const $messages = atom<ChatMessage[]>([]);
export const $streaming = atom<boolean>(false);
export const $pendingInput = atom<string>("");

export const $chatMeta = map<{ lastSessionId: string | null }>({
  lastSessionId: null,
});

export function appendMessage(msg: Omit<ChatMessage, "id" | "ts">): void {
  const full: ChatMessage = {
    ...msg,
    id: crypto.randomUUID(),
    ts: Date.now(),
  };
  $messages.set([...$messages.get(), full]);
}

export function clearMessages(): void {
  $messages.set([]);
}

export function resetChat(): void {
  clearMessages();
  $streaming.set(false);
  $pendingInput.set("");
  $chatMeta.set({ lastSessionId: null });
}
import { useState } from "react";
import { useStore } from "@nanostores/react";
import { $messages, $streaming, $pendingInput } from "../store/chat";
import { useChatStream } from "../hooks/useChatStream";
import { useSession } from "../hooks/useSession";
import { ToolCallCard } from "./ToolCallCard";

export function ChatPanel() {
  const messages = useStore($messages);
  const streaming = useStore($streaming);
  useStore($pendingInput);
  const { send, error } = useChatStream();
  const { activeId } = useSession();
  const [draft, setDraft] = useState("");

  const onSubmit = async (e: React.FormEvent): Promise<void> => {
    e.preventDefault();
    const text = draft.trim();
    if (!text || streaming) return;
    setDraft("");
    $pendingInput.set("");
    await send(text, activeId ?? undefined);
  };

  return (
    <div className="chat-panel">
      <header className="chat-header">
        <span className="chat-title">Chat</span>
        <span className="chat-session">
          {activeId ? `session: ${activeId.slice(0, 8)}` : "no active session"}
        </span>
        {error ? <span className="chat-error" role="alert">{error}</span> : null}
      </header>
      <ol className="message-list" aria-live="polite">
        {messages.length === 0 ? (
          <li className="message-empty">Type a message to start a new conversation.</li>
        ) : null}
        {messages.map((m: import("../store/chat").ChatMessage) => (
          <li key={m.id} className={`message message-${m.role}`}>
            <div className="message-role">{m.role}</div>
            <div className="message-content">
              <pre>{m.content}</pre>
            </div>
          </li>
        ))}
        {streaming ? (
          <li className="message message-assistant streaming">
            <div className="message-role">assistant</div>
            <div className="message-content">
              <ToolCallCard event={{ type: "message", data: { streaming: true } }} />
            </div>
          </li>
        ) : null}
      </ol>
      <form className="composer" onSubmit={onSubmit}>
        <textarea
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            $pendingInput.set(e.target.value);
          }}
          placeholder="Send a message..."
          rows={3}
          disabled={streaming}
          aria-label="message input"
        />
        <button type="submit" disabled={streaming || draft.trim().length === 0}>
          {streaming ? "Streaming..." : "Send"}
        </button>
      </form>
    </div>
  );
}
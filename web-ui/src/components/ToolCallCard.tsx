import { useState } from "react";
import type { StreamEvent } from "../hooks/useChatStream";

interface Props {
  event: StreamEvent;
}

// Collapsible card showing a tool call (or a generic event). Defaults
// to expanded for tool_call events (the user wants to see what's about
// to run), collapsed for everything else.
export function ToolCallCard({ event }: Props) {
  const [open, setOpen] = useState(event.type === "tool_call");
  const title = titleFor(event);
  const body = bodyFor(event);
  return (
    <div className={`tool-call-card tool-call-${event.type}`}>
      <button
        type="button"
        className="tool-call-header"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="tool-call-title">{title}</span>
        <span className="tool-call-toggle">{open ? "▾" : "▸"}</span>
      </button>
      {open ? <pre className="tool-call-body">{body}</pre> : null}
    </div>
  );
}

function titleFor(event: StreamEvent): string {
  switch (event.type) {
    case "tool_call":
      return `tool_call → ${String(event.data.name ?? "?")}`;
    case "tool_result":
      return `tool_result ← ${String(event.data.name ?? "?")}`;
    case "message":
      return "assistant message";
    case "final":
      return `final (${String(event.data.iterations ?? "?")} iterations)`;
    case "start":
      return "stream start";
    case "error":
      return `error: ${String(event.data.message ?? "")}`;
    default:
      return event.type;
  }
}

function bodyFor(event: StreamEvent): string {
  try {
    return JSON.stringify(event.data, null, 2);
  } catch {
    return String(event.data);
  }
}
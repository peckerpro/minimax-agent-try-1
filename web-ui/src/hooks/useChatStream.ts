import { useEffect, useRef, useState } from "react";
import { $streaming, appendMessage, $chatMeta } from "../store/chat";

export interface StreamEvent {
  type: "start" | "message" | "tool_call" | "tool_result" | "final" | "error";
  data: Record<string, unknown>;
}

export interface UseChatStreamResult {
  send: (message: string, sessionId?: string) => Promise<void>;
  isStreaming: boolean;
  lastEvent: StreamEvent | null;
  error: string | null;
}

export function useChatStream(): UseChatStreamResult {
  const [isStreaming, setIsStreaming] = useState(false);
  const [lastEvent, setLastEvent] = useState<StreamEvent | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  useEffect(() => {
    return () => {
      // Ensure pending streams are aborted when the component unmounts
      abortRef.current?.abort();
    };
  }, []);

  const send = async (message: string, sessionId?: string): Promise<void> => {
    setIsStreaming(true);
    setError(null);
    $streaming.set(true);
    appendMessage({ role: "user", content: message });

    const controller = new AbortController();
    abortRef.current = controller;

    try {
      const params = new URLSearchParams({
        message,
        ...(sessionId ? { session_id: sessionId } : {}),
      });
      const res = await fetch(`/api/chat/stream?${params.toString()}`, {
        method: "GET",
        signal: controller.signal,
        headers: { Accept: "text/event-stream" },
      });
      if (!res.ok || !res.body) {
        throw new Error(`SSE handshake failed: ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      while (true) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        // SSE messages are separated by blank lines
        const parts = buffer.split("\n\n");
        buffer = parts.pop() ?? "";
        for (const part of parts) {
          const evt = parseSseEvent(part);
          if (!evt) continue;
          setLastEvent(evt);
          if (evt.type === "final") {
            const sid = typeof evt.data.session_id === "string" ? evt.data.session_id : null;
            $chatMeta.set({ lastSessionId: sid });
          } else if (evt.type === "message") {
            const content = typeof evt.data.content === "string" ? evt.data.content : "";
            appendMessage({ role: "assistant", content });
          } else if (evt.type === "error") {
            const msg = typeof evt.data.message === "string" ? evt.data.message : "agent error";
            setError(msg);
            appendMessage({ role: "system", content: `error: ${msg}` });
          }
        }
      }
    } catch (err) {
      if ((err as Error).name === "AbortError") {
        // intentional abort on unmount — no toast
      } else {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        appendMessage({ role: "system", content: `stream failed: ${msg}` });
      }
    } finally {
      setIsStreaming(false);
      $streaming.set(false);
      abortRef.current = null;
    }
  };

  return { send, isStreaming, lastEvent, error };
}

function parseSseEvent(block: string): StreamEvent | null {
  let event = "message";
  const dataLines: string[] = [];
  for (const rawLine of block.split("\n")) {
    const line = rawLine.replace(/\r$/, "");
    if (!line) continue;
    if (line.startsWith("event:")) {
      event = line.slice(6).trim();
    } else if (line.startsWith("data:")) {
      dataLines.push(line.slice(5).trim());
    }
  }
  if (dataLines.length === 0) return null;
  const payload = dataLines.join("\n");
  try {
    return {
      type: (event as StreamEvent["type"]) || "message",
      data: JSON.parse(payload) as Record<string, unknown>,
    };
  } catch {
    return { type: "message", data: { raw: payload } };
  }
}
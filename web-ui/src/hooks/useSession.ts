import { useEffect, useState } from "react";
import api from "../api/client";
import type { SessionSummary } from "../api/types";
import { $sessions, $activeSessionId, setActiveSession, $sessionMeta } from "../store/session";

export interface UseSessionResult {
  sessions: SessionSummary[];
  activeId: string | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  select: (id: string | null) => void;
  resume: (id: string) => Promise<void>;
}

export function useSession(): UseSessionResult {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [activeId, setActiveId] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // mirror to nanostores for cross-component access
  useEffect(() => {
    setSessions([...$sessions.get()]);
    const unsub = $sessions.listen((next) => setSessions([...next]));
    return unsub;
  }, []);
  useEffect(() => {
    setActiveId($activeSessionId.get());
    const unsub = $activeSessionId.listen((next) => setActiveId(next));
    return unsub;
  }, []);

  const refresh = async (): Promise<void> => {
    setLoading(true);
    $sessionMeta.setKey("loading", true);
    try {
      const res = await api.get<SessionSummary[]>("/sessions/");
      $sessions.set(res.data);
      setError(null);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      $sessionMeta.setKey("error", msg);
    } finally {
      setLoading(false);
      $sessionMeta.setKey("loading", false);
    }
  };

  const select = (id: string | null): void => {
    setActiveSession(id);
  };

  const resume = async (id: string): Promise<void> => {
    try {
      await api.post(`/sessions/${encodeURIComponent(id)}/resume`);
      select(id);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(msg);
      $sessionMeta.setKey("error", msg);
    }
  };

  // Auto-refresh on mount; the sidebar reuses this hook too so we keep
  // a single fetch path.
  useEffect(() => {
    void refresh();
  }, []);

  return { sessions, activeId, loading, error, refresh, select, resume };
}
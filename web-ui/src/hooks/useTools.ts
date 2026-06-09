import { useCallback, useEffect, useState } from "react";
import api from "../api/client";
import type { ToolSummary } from "../api/types";

export interface UseToolsResult {
  tools: ToolSummary[];
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  enable: (name: string) => Promise<void>;
  disable: (name: string) => Promise<void>;
}

export function useTools(): UseToolsResult {
  const [tools, setTools] = useState<ToolSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async (): Promise<void> => {
    setLoading(true);
    try {
      const res = await api.get<ToolSummary[]>("/tools/");
      setTools(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, []);

  const enable = useCallback(
    async (name: string): Promise<void> => {
      await api.post(`/tools/${encodeURIComponent(name)}/enable`);
      await refresh();
    },
    [refresh],
  );

  const disable = useCallback(
    async (name: string): Promise<void> => {
      await api.post(`/tools/${encodeURIComponent(name)}/disable`);
      await refresh();
    },
    [refresh],
  );

  useEffect(() => {
    void refresh();
  }, [refresh]);

  return { tools, loading, error, refresh, enable, disable };
}
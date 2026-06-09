import { useEffect, useState } from "react";
import api from "../api/client";

// Lightweight memory browser — fetches recent episodic entries. The
// server returns whatever shape /api/sessions/ provides; we render as
// preformatted text so JSON / Markdown pastes remain readable.
export function MemoryPanel() {
  const [entries, setEntries] = useState<unknown[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const load = async (): Promise<void> => {
      setLoading(true);
      try {
        const res = await api.get<unknown[]>("/sessions/");
        setEntries(res.data);
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  return (
    <div className="memory-panel">
      <header className="panel-header">
        <h2>Memory (recent sessions)</h2>
      </header>
      {error ? <p className="panel-error" role="alert">{error}</p> : null}
      {loading ? <p>Loading...</p> : null}
      <pre className="memory-dump">{JSON.stringify(entries, null, 2)}</pre>
    </div>
  );
}
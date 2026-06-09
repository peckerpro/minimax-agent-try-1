import { useEffect, useState } from "react";
import api from "../api/client";

export function ConfigPanel() {
  const [, setConfig] = useState<Record<string, unknown>>({});
  const [draft, setDraft] = useState<string>("");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [savedAt, setSavedAt] = useState<number | null>(null);

  useEffect(() => {
    const load = async (): Promise<void> => {
      setLoading(true);
      try {
        const res = await api.get<{ config: Record<string, unknown> }>("/config/");
        setConfig(res.data.config);
        setDraft(JSON.stringify(res.data.config, null, 2));
        setError(null);
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setLoading(false);
      }
    };
    void load();
  }, []);

  const save = async (): Promise<void> => {
    setSaving(true);
    try {
      const parsed = JSON.parse(draft) as Record<string, unknown>;
      await api.put("/config/", { config: parsed });
      setConfig(parsed);
      setSavedAt(Date.now());
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="config-panel">
      <header className="panel-header">
        <h2>Config</h2>
        <button type="button" onClick={() => void save()} disabled={saving || loading}>
          {saving ? "Saving..." : "Save"}
        </button>
        {savedAt ? <span className="saved-at">saved {new Date(savedAt).toLocaleTimeString()}</span> : null}
      </header>
      {error ? <p className="panel-error" role="alert">{error}</p> : null}
      {loading ? <p>Loading...</p> : null}
      <textarea
        className="config-editor"
        value={draft}
        onChange={(e) => setDraft(e.target.value)}
        rows={20}
        spellCheck={false}
        aria-label="config yaml as JSON"
      />
    </div>
  );
}
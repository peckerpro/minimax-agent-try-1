import { useEffect, useState } from "react";
import api from "../api/client";
import type { SkillSummary } from "../api/types";

export function SkillsPanel() {
  const [skills, setSkills] = useState<SkillSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);

  const refresh = async (): Promise<void> => {
    setLoading(true);
    try {
      const res = await api.get<SkillSummary[]>("/skills/");
      setSkills(res.data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    void refresh();
  }, []);

  const onUpload = async (e: React.ChangeEvent<HTMLInputElement>): Promise<void> => {
    const file = e.target.files?.[0];
    if (!file) return;
    setUploading(true);
    try {
      const fd = new FormData();
      fd.append("file", file);
      await api.post("/skills/install", fd, {
        headers: { "Content-Type": "multipart/form-data" },
      });
      await refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setUploading(false);
      e.target.value = "";
    }
  };

  return (
    <div className="skills-panel">
      <header className="panel-header">
        <h2>Skills</h2>
        <label className="upload-button">
          {uploading ? "Uploading..." : "Install SKILL.md"}
          <input
            type="file"
            accept=".md"
            onChange={(e) => void onUpload(e)}
            disabled={uploading}
            hidden
          />
        </label>
      </header>
      {error ? <p className="panel-error" role="alert">{error}</p> : null}
      {loading ? <p>Loading...</p> : null}
      <ul className="skill-list">
        {skills.map((s) => (
          <li key={s.name} className="skill-item">
            <strong>{s.name}</strong>
            <p>{s.description}</p>
            {s.triggers ? <p className="skill-triggers">triggers: {s.triggers.join(", ")}</p> : null}
          </li>
        ))}
      </ul>
    </div>
  );
}
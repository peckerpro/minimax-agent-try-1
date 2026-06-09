import { useSession } from "../hooks/useSession";
import { resetChat } from "../store/chat";

export function Sidebar() {
  const { sessions, activeId, loading, error, refresh, select, resume } = useSession();
  return (
    <aside className="sidebar">
      <header className="sidebar-header">
        <span className="sidebar-title">hello-agent</span>
        <span className="sidebar-version">v0.2.0</span>
      </header>
      <div className="sidebar-actions">
        <button
          type="button"
          onClick={() => {
            resetChat();
            select(null);
          }}
        >
          + New chat
        </button>
        <button type="button" onClick={() => void refresh()} disabled={loading}>
          {loading ? "Refreshing..." : "Refresh"}
        </button>
      </div>
      {error ? <p className="sidebar-error" role="alert">{error}</p> : null}
      <nav className="session-list" aria-label="Sessions">
        {sessions.length === 0 ? (
          <p className="session-empty">No sessions yet.</p>
        ) : null}
        <ul>
          {sessions.map((s) => (
            <li
              key={s.id}
              className={s.id === activeId ? "session-item active" : "session-item"}
            >
              <button
                type="button"
                className="session-button"
                onClick={() => void resume(s.id)}
                title={s.title}
              >
                <span className="session-title">{s.title}</span>
                <span className="session-time">{formatTime(s.updated_at)}</span>
              </button>
            </li>
          ))}
        </ul>
      </nav>
    </aside>
  );
}

function formatTime(iso: string): string {
  try {
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return iso;
    return d.toLocaleString();
  } catch {
    return iso;
  }
}
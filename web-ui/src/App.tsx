import { Sidebar } from "./components/Sidebar";
import { ChatPanel } from "./components/ChatPanel";
import { SkillsPanel } from "./components/SkillsPanel";
import { MemoryPanel } from "./components/MemoryPanel";
import { ConfigPanel } from "./components/ConfigPanel";
import { useStore } from "@nanostores/react";
import { $activeTab } from "./store/session";

export default function App() {
  const activeTab = useStore($activeTab);
  return (
    <div className="app-shell">
      <Sidebar />
      <main className="main-pane">
        <nav className="tab-bar">
          <button
            type="button"
            className={activeTab === "chat" ? "tab active" : "tab"}
            onClick={() => $activeTab.set("chat")}
          >
            Chat
          </button>
          <button
            type="button"
            className={activeTab === "skills" ? "tab active" : "tab"}
            onClick={() => $activeTab.set("skills")}
          >
            Skills
          </button>
          <button
            type="button"
            className={activeTab === "memory" ? "tab active" : "tab"}
            onClick={() => $activeTab.set("memory")}
          >
            Memory
          </button>
          <button
            type="button"
            className={activeTab === "config" ? "tab active" : "tab"}
            onClick={() => $activeTab.set("config")}
          >
            Config
          </button>
        </nav>
        <section className="tab-content">
          {activeTab === "chat" && <ChatPanel />}
          {activeTab === "skills" && <SkillsPanel />}
          {activeTab === "memory" && <MemoryPanel />}
          {activeTab === "config" && <ConfigPanel />}
        </section>
      </main>
    </div>
  );
}
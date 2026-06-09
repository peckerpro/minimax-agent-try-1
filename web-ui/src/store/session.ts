import { atom, map } from "nanostores";
import type { SessionSummary } from "../api/types";

export type TabName = "chat" | "skills" | "memory" | "config";

export const $activeTab = atom<TabName>("chat");

export const $sessions = atom<SessionSummary[]>([]);
export const $activeSessionId = atom<string | null>(null);

export const $sessionMeta = map<{ loading: boolean; error: string | null }>({
  loading: false,
  error: null,
});

export function setActiveSession(id: string | null): void {
  $activeSessionId.set(id);
}
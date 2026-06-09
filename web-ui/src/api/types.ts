// Shared API types — kept loose (Record<string, unknown> where the
// backend hasn't formalized a schema yet) so the frontend doesn't break
// when the server adds new fields. Tighter types can come in v0.3.

export interface ChatRequest {
  message: string;
  session_id?: string;
}

export interface ChatResponse {
  content: string;
  session_id: string;
  iterations: number;
}

export interface SessionSummary {
  id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface SkillSummary {
  name: string;
  description: string;
  triggers?: string[];
}

export interface ToolSummary {
  name: string;
  description: string;
  enabled: boolean;
}

export interface ConfigResponse {
  config: Record<string, unknown>;
}

export type ToolResult = {
  tool_call_id: string;
  name: string;
  content: string;
  is_error: boolean;
};
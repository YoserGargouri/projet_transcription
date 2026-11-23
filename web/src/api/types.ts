// Shapes returned by the FastAPI backend (src/agentkit/server/api.py).

export interface User { id: string; email: string; name: string; created_at: string }
export interface WorkspaceSettings {
  tts_monthly_char_limit: number;
  pricing: { currency?: string; llm_input_per_million?: number | null; llm_output_per_million?: number | null; tts_per_thousand_chars?: number | null };
}
export interface Workspace { id: string; name: string; business_type: string; settings: WorkspaceSettings }
export interface Me { user: User; workspace: Workspace }

export interface TemplateWorkflow {
  id: string; description: string; action_type: string | null; action_label: string | null;
  slots: { name: string; type: string; pii: boolean }[];
}
export interface Template {
  id: string; name: string; description: string; language: string; llm_mode: "llm_first" | "rules_first";
  voice: boolean; tts_engine: string | null;
  persona: { name: string; greeting: string; style: string };
  scope: { description: string; allowed: string[]; forbidden: string[] };
  workflows: TemplateWorkflow[]; intents: { id: string; description: string }[];
  tools: { name: string; kind: string; description: string }[];
  knowledge_entries: number; catalogue_items: number; safety_scripts: number;
}
export interface AgentSettings {
  persona_name: string; greeting: string; style: string; llm_mode: "llm_first" | "rules_first";
  voice_engine: "elevenlabs" | "gtts" | null; language: string;
  channels: { web_chat: boolean; voice: boolean; phone: boolean };
}
export interface Agent {
  id: string; name: string; template: string; business_domain: string; business_type: string; description: string;
  created_at: string; updated_at: string; knowledge_entries: number; conversations: number; last_conversation: string | null;
  settings: AgentSettings; template_available: boolean; template_info?: Template;
}
export interface KnowledgeEntry {
  id: number; entry_id: string; category: string; question: string; answer: string; variants: string;
  source: "template" | "manual" | "import"; updated_at: string;
}

export interface TurnDetails {
  mode?: string; greeting?: boolean;
  llm?: { llm_used?: boolean; fallback?: string; intent?: string; understood?: boolean; sources?: string[]; asks_for?: string };
  llm_failure?: string; rules_hint?: string; knowledge_used?: string[]; knowledge_unsupported?: boolean;
  precheck?: { reason: string; options: string[] }; escalation?: { reason: string; detail: string };
  action?: { workflow: string; tool: string; action: string; status: string; duration_ms: number; error?: string };
  tool_result?: Record<string, unknown>; confirmation?: string; audio_quality?: string;
  timings?: { stt_s?: number; agent_s?: number; tts_s?: number; total_s?: number; tts_engine?: string; tts_cached?: boolean; stt_confidence?: number; quality?: string };
}
export interface FieldState { name: string; type: string; required: boolean; filled: boolean; value: string | null }
export interface AgentState {
  intent: string | null; workflow: string | null; workflow_description?: string; fields?: FieldState[];
  awaiting_confirmation?: boolean; candidates?: number; escalated: boolean;
}
export interface PlaygroundSession {
  conversation_id: string; greeting: string; created_at: string; llm_enabled: boolean; mode: string;
  voice_available: boolean; state: AgentState;
}
export interface TurnResponse {
  idx: number; reply: string; user_text: string; intent: string | null; llm_used: boolean; llm_failed: boolean;
  escalated: boolean; escalation_reason: string | null; latency_ms: number; tokens: number; details: TurnDetails;
  created_at: string; state: AgentState; transcript?: string; audio_url?: string;
}

export type Outcome = "action_completed" | "information_provided" | "escalated" | "in_progress" | "unresolved";
export type ActionStatus = "succeeded" | "pending" | "failed" | "requires_human";

export interface ConversationRow {
  id: string; agent_id: string | null; agent_name: string; channel: "chat" | "voice"; source: string; customer_ref: string;
  started_at: string; last_activity_at: string; ended_at: string | null; status: "active" | "ended"; outcome: Outcome;
  escalation_reason: string | null; turns: number; llm_calls: number; prompt_tokens: number; completion_tokens: number;
  tts_chars: number; stt_seconds: number; duration_s: number | null; actions_succeeded?: number; first_message?: string | null;
}
export interface Turn {
  id: number; idx: number; created_at: string; user_text: string; agent_text: string; intent: string | null; channel: string;
  llm_used: number; llm_failed: number; understood: number | null; escalated: number; latency_ms: number | null;
  prompt_tokens: number; completion_tokens: number; tts_chars: number; audio_url?: string; details: TurnDetails;
}
export interface ActionRow {
  id: string; agent_id: string | null; conversation_id: string | null; turn_idx: number | null; type: string; label: string;
  workflow: string | null; tool: string | null; tool_action: string | null; status: ActionStatus; created_at: string;
  updated_at: string; duration_ms: number | null; details: Record<string, unknown>; agent_name?: string; channel?: string;
}
export interface ConversationDetail extends ConversationRow { turns_list: Turn[]; actions: ActionRow[] }
export interface Paged<T> { total: number; page: number; page_size: number; items: T[] }

export interface DailyPoint {
  date: string; conversations: number; voice: number; chat: number; actions_succeeded: number; actions_failed: number;
  escalations: number; tokens: number; tts_chars: number; avg_latency_ms: number | null;
}
export interface Analytics {
  range: { from: string; to: string; agent_id: string | null };
  totals: {
    conversations: number; voice_conversations: number; chat_conversations: number; turns: number;
    handled_without_human: number; automation_rate: number | null; resolution_rate: number | null;
    escalations: number; escalation_rate: number | null; avg_duration_s: number | null; avg_latency_ms: number | null;
    avg_latency_chat_ms: number | null; avg_latency_voice_ms: number | null; p50_latency_ms: number | null; p90_latency_ms: number | null;
    llm_calls: number; llm_turns: number; llm_failed_turns: number; llm_usage_rate: number | null; understood_rate: number | null;
    prompt_tokens: number; completion_tokens: number; total_tokens: number; tts_chars: number; stt_seconds: number;
    actions_total: number; actions_succeeded: number; actions_failed: number; actions_pending: number; actions_requires_human: number;
    action_success_rate: number | null; avg_action_duration_ms: number | null;
  };
  daily: DailyPoint[];
  intents: { intent: string; count: number }[];
  outcomes: { outcome: Outcome; count: number }[];
  action_types: { type: string; label: string; count: number; succeeded: number }[];
  hours: { hour: number; count: number }[];
  escalation_reasons: { reason: string; count: number }[];
  estimated_cost: { llm: number; tts: number; total: number; currency: string } | null;
}
export interface Dashboard {
  analytics: Analytics; recent_conversations: ConversationRow[]; recent_actions: ActionRow[]; attention: ActionRow[];
  agents: { id: string; name: string; template: string }[];
}
export interface Integrations {
  llm: { configured: boolean; provider: string | null; host: string | null; model: string | null; fallback_models: string[]; timeout_s: string | null };
  elevenlabs: { configured: boolean; model: string | null; voice_configured: boolean; chars_this_month: number; monthly_limit: number };
  stt: { engines: string[] };
  email: { configured: boolean; mode: string | null };
  telephony: { configured: boolean };
}

const api = async <T>(path: string, init?: RequestInit): Promise<T> => {
  const response = await fetch(`/api${path}`, { headers: { "Content-Type": "application/json" }, ...init });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? `Request failed (${response.status})`);
  return response.json() as Promise<T>;
};

export const client = {
  decision: () => api<DecisionCenter>("/decision/today"),
  decisionFor: (profile: string) => api<DecisionResponse>(`/decision/recommendations/${profile}`),
  prices: () => api<{ prices: ModelPrice[] }>("/model-prices?limit=500"),
  changes: () => api<{ changes: PriceChange[] }>("/prices/changes?limit=50"),
  promotions: () => api<Promotion[]>("/promotions"),
  sources: () => api<Source[]>("/sources"),
  insights: () => api<Insight[]>("/insights?limit=30"),
  assets: () => api<UserAsset[]>("/assets"),
  saveAsset: (asset: AssetInput) => api<UserAsset>("/assets", { method: "POST", body: JSON.stringify(asset) }),
  deleteAsset: (id: number) => api<{ deleted: boolean }>(`/assets/${id}`, { method: "DELETE" }),
  briefing: () => api<Briefing>("/assistant/briefing"),
  chat: (messages: ChatMessage[]) => api<Briefing>("/assistant/chat", { method: "POST", body: JSON.stringify({ messages, profile: "daily_chat" }) }),
  scan: () => api<{ status: string; providers: string[] }>("/scans", { method: "POST" }),
  intelligence: () => api<{ status: string }>("/intelligence/scans", { method: "POST" }),
  registry: () => api<ProviderRegistry>("/provider-registry"),
};

export type Recommendation = { model: string; canonical_model_id: string | null; provider: string; provider_id: string; input_price: string | null; output_price: string | null; currency: string; context_length: number | null; speed_score: string; ability_score: string; stability_score: string; value_score: string; score: number | null; dimensions: Record<string, string>; asset_available: boolean; asset_reason?: string | null; data_confidence?: string; score_confidence?: string; interaction_mode?: "realtime" | "batch" | "agent" | "subscription" | "local"; is_free?: boolean; estimated_cost?: string | null; estimated_cost_currency?: string | null; why?: string; eligibility?: string; reason: string; source_url: string | null; updated_time: string };
export type DecisionMode = "best_quality" | "balanced" | "budget" | "free" | "my_assets";
export type DecisionResponse = { profile: string; mode: DecisionMode; recommendations: Recommendation[] };
export type Coverage = { discovered_providers: number; structured_providers: number; comparable_providers: number; uncovered_candidates: number; configured_providers: number; recommendation_confidence: "high" | "medium" | "low"; coverage_ratio: number; uncovered: { provider_id: string; name: string; status: string; reason: string; source: string | null; official_url: string | null }[] };
export type Provider = { id: number; provider_id: string; display_name: string; official_url: string | null; pricing_url: string | null; status: string; parser_status: string; discovery_source: string | null; has_pricing_page: boolean; has_model_api: boolean; login_required: boolean; data_confidence: string; priority_score: number };
export type ProviderRegistry = { providers: Provider[]; coverage: Coverage };
export type DecisionCenter = { score_formula: string; recommendation_confidence: "high" | "medium" | "low"; coverage: Coverage; recommendations: { task_id: string; task: string; recommendations: Recommendation[]; modes?: Record<DecisionMode, Recommendation[]>; mode_labels?: Record<DecisionMode, string> }[]; actions: string[] };
export type ModelPrice = { provider: string; model: string; canonical_model_id: string | null; input_price: string | null; output_price: string | null; context_length: number | null; currency: string; source_url: string | null; source_type: string; updated_time: string; validation_status: string; identity_status: string; confidence: string; invalid_reason: string | null };
export type PriceChange = { provider_id: string; provider_name: string; provider_model_id: string; provider_model_name: string; input_price: string | null; output_price: string | null; currency: string; change_type: "new" | "increased" | "decreased" | "unchanged"; input_price_delta: string | null; captured_at: string; source_url: string | null };
export type Promotion = { id: number; title: string; description: string | null; promotion_type: string; source: string; confidence: string; captured_at: string };
export type Source = { source_type: string; url: string; title: string | null; captured_at: string; fetch_success: boolean; error: string | null };
export type Insight = { id: number; title: string | null; source_type: string; url: string; summary: string; impact_level: "critical" | "high" | "medium" | "low"; action: string; captured_at: string; generated_by: string };
export type UserAsset = { id: number; provider: string; api_key_status: "active" | "inactive" | "unknown"; balance: string | null; currency: string | null; plan: string | null; available_models: string[]; has_account?: boolean; credit_exchange_rate?: string | null; subscription?: string | null; primary_or_backup?: "primary" | "backup"; notes?: string | null; enabled: boolean; updated_at: string };
export type AssetInput = Omit<UserAsset, "id" | "updated_at">;
export type Briefing = { text: string; source: string; model: string | null; error?: string; adjustment?: { updated: string[] } };
export type ChatMessage = { role: "user" | "assistant"; content: string };

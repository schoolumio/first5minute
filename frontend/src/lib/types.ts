export type Market = "MARKET_A" | "MARKET_B";
export type Category = "qualified" | "watchlist" | "below_threshold" | "excluded";
export type Quality = "high" | "medium" | "low" | "insufficient";

export interface Team { id: number; name: string; short_name: string | null; country: string | null; logo_url: string | null; is_demo: boolean }
export interface Competition {
  id: number; name: string; country: string | null; type: string; gender: string; logo_url: string | null;
  is_enabled: boolean; data_quality_tier: string; is_demo: boolean;
  eligibility_status?: "eligible" | "ineligible" | "unassessed"; eligibility_mode?: "auto" | "force_on" | "force_off";
  eligibility_reason?: string | null; coverage_pct?: number | null;
}
export interface Fixture {
  id: number; provider: string; competition: Competition; home_team: Team; away_team: Team; kickoff_at: string;
  status: string; round: string | null; venue: string | null;
  score: { home: number | null; away: number | null; home_ht: number | null; away_ht: number | null };
  timeline_status: string; timeline_precision: string | null; data_version: number; is_demo: boolean;
}
export interface Outcome {
  result: "won" | "lost" | "void" | "unresolved"; home_score_at_cutoff: number | null; away_score_at_cutoff: number | null;
  settled_at: string; revision: number; notes: string | null;
}
export interface Prediction {
  id: number; fixture_id: number; market: Market; probability: number; confidence: "high" | "medium" | "low";
  data_quality: Quality; category: Category; category_reasons: string[]; sample_home: number; sample_away: number;
  lambda_home: number | null; lambda_away: number | null; components: Record<string, unknown>;
  predicted_at: string; kickoff_at: string; input_data_version: string; is_current: boolean;
  model: { id: number; name: string; version: string; algorithm: string; calibration_status: string };
  outcome: Outcome | null; is_demo: boolean; fixture?: Fixture;
  best_odds?: { decimal_odds: number; bookmaker: string; captured_at: string; is_demo?: boolean; n_books?: number } | null; edge?: number | null;
}
export interface Page<T> { items: T[]; total: number; page: number; page_size: number; pages: number }
export interface Entitlements { plan: string; plan_name: string; features: Record<string, boolean | number | null> }
export interface User {
  id: number; email: string; full_name: string | null; country: string | null; timezone: string; role: "admin" | "user";
  email_verified: boolean; created_at: string | null; last_login_at: string | null;
  notification_prefs: Record<string, boolean>;
  responsible_gambling: { daily_stake_limit: number | null; monthly_stake_limit: number | null; self_excluded_until: string | null; reality_check_minutes: number | null };
  entitlements: Entitlements | null;
}
export interface SystemStatus {
  environment: string; data_mode: "demo" | "live"; football_provider: string; odds_provider: string;
  payments_enabled: boolean; database: string; demo_notice: string | null;
  last_runs: Record<string, { status: string; at: string } | null>;
}
export interface Plan {
  code: string; name: string; description: string | null; price_minor: number; price: number; currency: string;
  interval: string; rank: number; features: Record<string, boolean | number | null>; is_active: boolean;
}
export interface Window {
  matches: number; reliable_matches: number; scored_early_pct: number | null; conceded_early_pct: number | null;
  clean_window_pct: number | null; level_at_cutoff_pct: number | null; early_goals_for: number; early_goals_against: number;
  avg_goals_for: number | null; avg_goals_against: number | null;
}
export interface TeamProfile {
  team: Team; windows: Record<string, Window>; venue: (Window & { label: string }) | null;
  first_goal_timing: { bucket: string; count: number }[] | null;
  recent_matches: { fixture_id: number; kickoff_at: string; is_home: boolean; opponent: string | null; goals_for: number;
    goals_against: number; early_for: number | null; early_against: number | null; first_goal_minute: number | null; reliable: boolean }[];
}

export interface OddsRow {
  bookmaker: { id: number; code: string; name: string; is_demo: boolean }; market: Market; selection: string; decimal_odds: number;
  implied_probability: number; fair_odds: number | null; edge: number | null; is_available: boolean; is_stale: boolean; age_minutes: number;
  last_updated: string; checked_at: string; rule_mismatch: boolean; rule_note: string | null; can_open: boolean; is_demo: boolean;
}
export interface LimitStatus {
  daily: { limit: number | null; used: number; reached: boolean }; monthly: { limit: number | null; used: number; reached: boolean };
  self_excluded: boolean; self_excluded_until: string | null; reality_check_minutes: number | null;
}
export interface FixtureOdds {
  fixture_id: number; kickoff_at: string; odds_provider: string; provider_configured: boolean; max_age_minutes: number; odds: OddsRow[];
  markets: Partial<Record<Market, { probability: number; category: Category; fair_odds: number | null; edge: number | null;
    best: { decimal_odds: number; bookmaker: string; bookmaker_code: string; captured_at: string; is_demo: boolean; n_books: number } | null }>>;
  best_history: Partial<Record<Market, { t: string; best: number | null }[]>>;
  responsible_gambling: LimitStatus; self_excluded: boolean; message: string | null; notice: string;
}

export interface ConverterBookmaker {
  code: string; name: string; is_demo: boolean; website: string | null; can_decode: boolean; can_be_destination: boolean;
  can_generate: boolean; available: boolean; message: string | null; setup?: string;
}
export type ConversionStatus = "pending" | "matched" | "odds_changed" | "unmatched" | "unavailable";
export interface ConversionSelection {
  index: number; status: ConversionStatus; reason_code: string | null; reason: string | null; confidence: "high" | "medium" | null;
  interpreted_as: string | null;
  source: { home_team: string; away_team: string; competition: string | null; start_time: string | null; market_name: string; outcome: string; odds: string | null };
  destination: { home_team: string; away_team: string; competition: string | null; start_time: string | null; market_name: string | null; outcome: string | null; odds: string | null } | null;
  odds: { original: string | null; destination: string | null; change: "up" | "down" | "same" | null };
  analysis?: SelectionAnalysis;
}
export interface Conversion {
  id: string; state: "decoded" | "matched" | "generated" | "manual"; deduplicated: boolean; is_demo: boolean;
  source: { code: string; name: string; is_demo: boolean };
  destination: { code: string; name: string; is_demo: boolean; website: string | null; can_generate: boolean };
  counts: { original: number; matched: number; unmatched: number; unavailable: number; odds_changed: number };
  selections: ConversionSelection[];
  totals: { original_odds: string | null; destination_odds: string | null; destination_covers_all: boolean };
  booking: { status: "generated" | "manual" | "failed"; code: string | null; share_url: string | null; is_demo: boolean; message: string | null } | null;
  needs_decision: boolean; betslip_text: string | null; notice: string; warnings: string[];
}

export interface SelectionAnalysis {
  prediction_id: number; fixture_id: number; market: Market; market_label: string; probability: number; fair_odds: number | null;
  category: Category; confidence: "high" | "medium" | "low"; data_quality: Quality; sample: number; calibration_status: string;
  model: string; reasons: string[]; is_demo: boolean; bookmaker_odds?: string | null; edge?: number | null;
}
export interface TicketPreviewItem extends Partial<SelectionAnalysis> {
  prediction_id: number; available: boolean; reason: string | null; replaced_by: number | null;
  fixture?: { home_team: string; away_team: string; competition: string; kickoff_at: string };
}

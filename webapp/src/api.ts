/* Typed client for the FastAPI surface in serve/.
   Types mirror serve/adapter.py and serve/store.py exactly; if you change a
   field name there, TypeScript should be the thing that tells you. */

const BASE = "/api";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(BASE + path, {
    headers: { "Content-Type": "application/json" },
    ...init,
  });
  if (!r.ok) {
    let msg = r.statusText;
    try {
      msg = (await r.json()).detail ?? msg;
    } catch {
      /* keep statusText */
    }
    throw new Error(msg);
  }
  return r.json() as Promise<T>;
}

/* ---- types ------------------------------------------------------------- */

export type DisputeStatus =
  | "open" | "queued" | "escalated" | "accepted" | "won" | "lost";

export interface Customer {
  customer_id: string;
  name: string;
  email: string;
}

export interface EvidenceItem {
  kind: string;
  api_field: string | null;
  state: "verified" | "stale" | "missing";
  artifact_id: string | null;
  value: string | null;
  created_on: string | null;
}

export interface Ev {
  gross: number;
  cost: number;
  cost_label: string;
  resolve_rate: number | null;
  value: number;
  positive: boolean;
}

export interface Dispute {
  id: string;
  reason_code: string;
  network: string;
  category: string;
  description: string;
  amount: number;
  filed_on: string;
  customer: Customer;
  prior_disputes: number;
  address_match: boolean;
  new_device: boolean;
  p_win: number;
  recommendation: "contest" | "accept";
  outcome_if_contested: "submitted" | "escalated";
  blocked: boolean;
  ev: Ev;
  packet_present: string[];
  claims: { artifact_id: string; supported: boolean }[];
  claims_supported: number;
  claims_total: number;
  evidence: EvidenceItem[];
  completeness: number;
  status: DisputeStatus;
  decided_by: string | null;
}

export interface DisputeDetail extends Dispute {
  artifacts: {
    artifact_id: string; kind: string; api_field: string;
    created_day: number; created_on: string; present: boolean; value: string;
  }[];
  provenance: { code_provenance: string; rulebook_version: number; verified_on: string };
  customer_history: {
    in_queue: number;
    prior_before_queue: number;
    total_amount: number;
    derived: boolean;
    items: { id: string; amount: number; reason_code: string; status: DisputeStatus; is_current: boolean }[];
  };
}

export interface EvidenceGapItem {
  kind: string;
  state: "missing" | "stale";
  p_win: number;
  ev: number;
  completeness: number;
  unblocked: boolean;
  flipped: boolean;
}

export interface EvidenceGaps {
  current: {
    p_win: number; ev: number; completeness: number;
    blocked: boolean; recommendation: "contest" | "accept";
  };
  items: EvidenceGapItem[];
  complete: boolean;
  already_supplied: { kind: string; value: string }[];
}

export interface EvidenceResult {
  before: Dispute;
  after: Dispute;
  delta: {
    p_win: number; ev: number; completeness: number;
    unblocked: boolean; flipped: boolean;
  };
  supplied?: string[];
}

export interface DraftedClaim {
  text: string; artifact_id: string | null;
  kind?: string | null; field?: string | null; value?: string | null;
}

export interface StrippedClaim extends DraftedClaim {
  reason: "no_such_artifact" | "kind_mismatch" | "stale_artifact"
        | "value_mismatch" | "unverifiable_claim";
  actual_kind?: string | null;
  actual_value?: string | null;
}

export interface Packet {
  provider: string;
  model: string | null;
  fault_rate: number | null;
  draft_error: string | null;
  artifacts_retrieved: number;
  claims_drafted: number;
  kept: DraftedClaim[];
  stripped: StrippedClaim[];
  n_fabricated: number;
  n_value_mismatch: number;
  n_unverifiable: number;
  hallucination_rate: number;
  completeness: number;
  missing_evidence: string[];
  blocked: boolean;
  field_check: boolean;
  merchant_artifacts: number;
  depends_on_merchant_evidence: boolean;
  redraft: boolean;
  attempts: number;
  recovered: boolean;
  trace: PacketAttempt[] | null;
  cached: boolean;
}

export interface PacketAttempt {
  attempt: number;
  drafted?: number;
  kept?: number;
  stripped?: number;
  blocked?: boolean;
  error?: string | null;
  skipped?: string;
  discarded?: string;
}

export const STRIP_REASON: Record<string, string> = {
  no_such_artifact: "cited a record that does not exist",
  kind_mismatch: "described the record as the wrong kind",
  stale_artifact: "record is dated after the dispute",
  value_mismatch: "stated a value the record does not contain",
  unverifiable_claim: "named nothing that could be checked",
};

export interface Health {
  ok: boolean;
  disputes: number;
  dispute_source: string;
  model: { source: "learned" | "heuristic"; calibration?: string; n_train?: number;
           validation?: { auc: number; brier: number; ece: number }; error?: string };
  rulebook: { version: number; verified_on: string; codes: number };
  constants: Constants;
}

export interface Constants {
  contest_cost: number;
  human_review_cost: number;
  net_recovery_fraction: number;
  human_resolve_rate: number;
}

export interface LedgerRow {
  seq: number; at: string; kind: "debit" | "credit" | "topup";
  amount: number; dispute_id: string | null; note: string;
}

export interface Wallet {
  opening_balance: number; balance: number; spent: number; recovered: number;
  net: number; spent_today: number; daily_spend_cap: number;
  ledger: LedgerRow[]; constants: Constants;
}

export interface Policy {
  mode: "manual" | "delegated";
  min_p_win: number;
  max_amount: number;
  require_complete_packet: boolean;
  daily_spend_cap: number;
}

export interface Preview {
  auto: { id: string; amount: number; p_win: number; cost: number;
          days_left: number | null }[];
  held: { id: string; amount: number; p_win: number; reason: string;
          days_left: number | null }[];
  auto_count: number; held_count: number;
  projected_spend: number; projected_recovery: number;
  projected_net: number;
  binding_constraint: string | null;
  binding_label: string | null;
  budget_exhausted: boolean;
}

export interface CustomerRow extends Customer {
  disputes: number; amount: number; prior_before_queue: number;
  codes: string[]; open: number; lifetime_disputes: number; repeat: boolean;
}

export interface AuditRow {
  seq: number; at: string; event: string; dispute_id: string | null;
  policy_mode: string; rulebook_version: number; [k: string]: unknown;
}
export interface Extraction {
  kind: string;
  value: string | null;
  reference: string | null;
  created_day: number;
  tool: "heuristic" | "labelled" | "delimited" | "prose" | string;
  raw_extraction: string | null;
  provenance: string;
  extracted: boolean;
  source: string;
  router: string;
}

/* ---- calls ------------------------------------------------------------- */

export const api = {
  health: () => req<Health>("/health"),
  disputes: () => req<Dispute[]>("/disputes"),
  dispute: (id: string) => req<DisputeDetail>(`/disputes/${id}`),
  decide: (id: string, action: "contest" | "accept", actor: "merchant" | "agent" = "merchant") =>
    req<{ status: DisputeStatus; charged: number; wallet: Wallet }>(
      `/disputes/${id}/decision`,
      { method: "POST", body: JSON.stringify({ action, actor }) }
    ),
  evidenceGaps: (id: string) => req<EvidenceGaps>(`/disputes/${id}/evidence`),
  evidencePreview: (id: string, items: { kind: string; value: string }[]) =>
    req<EvidenceResult>(`/disputes/${id}/evidence/preview`,
      { method: "POST", body: JSON.stringify({ items }) }),
  evidenceSubmit: (id: string, items: { kind: string; value: string }[]) =>
    req<EvidenceResult>(`/disputes/${id}/evidence`,
      { method: "POST", body: JSON.stringify({ items }) }),
  packet: (id: string, faultRate?: number, redraft?: boolean) =>
    req<Packet>(`/disputes/${id}/packet?force=true`
      + (faultRate != null ? `&fault_rate=${faultRate}` : "")
      + (redraft ? "&redraft=true" : ""),
      { method: "POST" }),
      extract: (text: string, kind: string, router: "heuristic" | "model" = "heuristic") =>
    req<Extraction>("/extract",
      { method: "POST", body: JSON.stringify({ text, kind, router }) }),
  customers: () => req<{ derived: boolean; customers: CustomerRow[] }>("/customers"),
  wallet: () => req<Wallet>("/wallet"),
  topup: (amount: number) =>
    req<Wallet>("/wallet/topup", { method: "POST", body: JSON.stringify({ amount }) }),
  policy: () => req<{ policy: Policy; preview: Preview }>("/policy"),
  setPolicy: (p: Partial<Policy>) =>
    req<{ policy: Policy; preview: Preview }>("/policy", { method: "PUT", body: JSON.stringify(p) }),
  runAgent: () =>
    req<{ acted: { id: string; cost: number }[]; held: unknown[]; wallet: Wallet }>(
      "/agent/run", { method: "POST" }),
  audit: () => req<AuditRow[]>("/audit"),
  settle: () => req<{ settled: { id: string; won: boolean; credited: number }[]; wallet: Wallet }>(
    "/simulate/settle", { method: "POST" }),
  reset: () => req<{ ok: boolean }>("/simulate/reset", { method: "POST" }),
};

/* ---- formatting -------------------------------------------------------- */

export const inr = (n: number, dp = 0) =>
  "₹" + n.toLocaleString("en-IN", { minimumFractionDigits: dp, maximumFractionDigits: dp });

export const pct = (n: number) => Math.round(n * 100) + "%";

export const shortDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-IN", { day: "2-digit", month: "short" });

export const titleise = (s: string) =>
  s.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase());

export const STATUS_LABEL: Record<DisputeStatus, string> = {
  open: "Needs decision",
  queued: "Queued to submit",
  escalated: "Held for review",
  accepted: "Not contested",
  won: "Won",
  lost: "Lost",
};

export const STATUS_TONE: Record<DisputeStatus, string> = {
  open: "warn", queued: "info", escalated: "warn",
  accepted: "flat", won: "good", lost: "bad",
};
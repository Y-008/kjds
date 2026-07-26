export type EvidenceOpsFact = {
  id: string;
  label: string;
  value: string | number;
  unit: string;
  fact_type: string;
  source_ids: string[];
};

export type EvidenceOpsUnknown = {
  id: string;
  label: string;
  reason: string;
  next_action: string;
  synthetic_fill_allowed: false;
};

export type EvidenceOpsMission = {
  id: string;
  rank: number;
  stage_id: string;
  stage_step: string;
  title: string;
  status: "verified" | "in_progress" | "blocked" | "no_data";
  objective_relevant: boolean;
  rationale: string;
  agent: { id: string; name: string };
  workspace: string;
  progress: { current: number; target: number; percent: number };
  next_action: string;
  verification_condition: string;
  source_ids: string[];
  observed_facts: string[];
  human_required: true;
  automatic_execution: false;
  platform_write_allowed: false;
};

export type EvidenceOpsAgent = {
  agent_id: string;
  name: string;
  status: "needs_attention" | "waiting_for_upstream";
  work_item_count: number;
  current_focus: string;
  automatic_execution: false;
  selected_for_objective: boolean;
};

export type EvidenceOpsPlan = {
  contract_id: "kjds-evidenceops-copilot-plan-v1";
  product: {
    id: "evidenceops-copilot";
    name: string;
    version: "0.54.0";
    positioning: string;
  };
  objective: {
    text: string;
    type: "user_intent";
    is_business_fact: false;
    is_approval: false;
    is_execution_permit: false;
  };
  store_ref: string;
  status: "needs_evidence" | "ready_for_human_review";
  intent: {
    id: string;
    label: string;
    interpretation: string;
    matched_signals: string[];
    rule_match_count: number;
    inference_only: true;
    changes_business_fact: false;
  };
  source_snapshots: {
    operating_analytics: string;
    operating_workbench: string;
    source_as_of: string | null;
  };
  truth_ledger: {
    verified_facts: EvidenceOpsFact[];
    unknowns: EvidenceOpsUnknown[];
    synthetic_business_data_allowed: false;
  };
  missions: EvidenceOpsMission[];
  agent_team: EvidenceOpsAgent[];
  control_envelope: {
    plan_only: true;
    human_decision_required: true;
    external_write_allowed: false;
    automatic_execution: false;
    objective_can_promote_fact: false;
    model_output_can_promote_fact: false;
    approval_and_execution_separate: true;
    forbidden_actions: string[];
    continuation_rule: string;
  };
  plan_sha256: string;
};

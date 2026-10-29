PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS risks (
    risk_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL,
    scenario_name TEXT NOT NULL,
    risk_statement TEXT NOT NULL,
    inherent_tier TEXT NOT NULL,
    residual_tier TEXT NOT NULL,
    rationale_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    policy_id TEXT,
    policy_version TEXT,
    policy_outcome TEXT,
    sandbox_id TEXT
);

CREATE TABLE IF NOT EXISTS remediation_actions (
    action_id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL REFERENCES risks(risk_id) ON DELETE CASCADE,
    description TEXT NOT NULL,
    priority TEXT NOT NULL CHECK (priority IN ('low', 'medium', 'high', 'critical')),
    owner TEXT NOT NULL,
    due_date TEXT,
    status TEXT NOT NULL CHECK (status IN ('open', 'in_progress', 'completed')),
    completion_notes TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL REFERENCES risks(risk_id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    detail TEXT NOT NULL,
    occurred_at TEXT NOT NULL,
    prev_hash TEXT,
    hash TEXT,
    chain_origin TEXT,
    sandbox_id TEXT
);

CREATE TABLE IF NOT EXISTS sandboxes (
    sandbox_id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS schema_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS decisions (
    decision_id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL UNIQUE REFERENCES risks(risk_id) ON DELETE CASCADE,
    disposition TEXT NOT NULL CHECK (disposition IN ('approve', 'approve_with_conditions', 'escalate', 'reject')),
    conditions TEXT NOT NULL DEFAULT '',
    rationale TEXT NOT NULL,
    exception_rationale TEXT NOT NULL DEFAULT '',
    decider TEXT NOT NULL,
    policy_id TEXT NOT NULL,
    policy_version TEXT NOT NULL,
    rule_set_version TEXT NOT NULL,
    prohibited_at_decision TEXT NOT NULL CHECK (prohibited_at_decision IN ('prohibited', 'not_prohibited')),
    decided_at TEXT NOT NULL,
    handling_minutes INTEGER,
    rework_minutes INTEGER,
    manual_touches INTEGER,
    handoffs INTEGER,
    authenticated_effort_minutes INTEGER,
    cash_savings_dollars INTEGER
);

CREATE TABLE IF NOT EXISTS findings (
    finding_id INTEGER PRIMARY KEY AUTOINCREMENT,
    risk_id TEXT NOT NULL REFERENCES risks(risk_id) ON DELETE CASCADE,
    sandbox_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    severity TEXT NOT NULL CHECK (severity IN ('low', 'medium', 'high', 'critical')),
    vendor_name TEXT NOT NULL DEFAULT '',
    owner TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
    closing_note TEXT NOT NULL DEFAULT '',
    origin TEXT NOT NULL DEFAULT 'reviewer' CHECK (origin = 'reviewer'),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    closed_at TEXT
);

CREATE TABLE IF NOT EXISTS finding_mappings (
    finding_id INTEGER NOT NULL REFERENCES findings(finding_id) ON DELETE CASCADE,
    mapping_id TEXT NOT NULL,
    PRIMARY KEY (finding_id, mapping_id)
);

CREATE INDEX IF NOT EXISTS idx_actions_risk ON remediation_actions(risk_id);
CREATE INDEX IF NOT EXISTS idx_events_risk ON workflow_events(risk_id, event_id);
CREATE INDEX IF NOT EXISTS idx_findings_risk ON findings(risk_id);
CREATE INDEX IF NOT EXISTS idx_findings_sandbox ON findings(sandbox_id);

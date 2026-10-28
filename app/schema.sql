PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS risks (
    risk_id TEXT PRIMARY KEY,
    scenario_id TEXT NOT NULL UNIQUE,
    scenario_name TEXT NOT NULL,
    risk_statement TEXT NOT NULL,
    inherent_tier TEXT NOT NULL,
    residual_tier TEXT NOT NULL,
    rationale_json TEXT NOT NULL,
    created_at TEXT NOT NULL,
    policy_id TEXT,
    policy_version TEXT,
    policy_outcome TEXT
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
    occurred_at TEXT NOT NULL
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

CREATE INDEX IF NOT EXISTS idx_actions_risk ON remediation_actions(risk_id);
CREATE INDEX IF NOT EXISTS idx_events_risk ON workflow_events(risk_id, event_id);

# Public Demo ("Try it") Design

## Purpose

The whole hosted demo is open with no login. These public pages let anyone, including a hiring manager, run a vendor or AI tool review the way an analyst would in production. Every result comes from the same tested services the full application uses: the evidence validator, the risk engine, and the control mapper. There is no separate demo scoring.

The presentation idea, a guided scenario runner with an event log and a mock ticket payload, was inspired by irvinthev's GRC Cost of Assurance Dashboard, with permission. The code and logic here are separate and original.

## What a visitor can do

| Step | What the visitor sees | What runs underneath |
| --- | --- | --- |
| 1. Intake | Pick one of three synthetic vendors, or describe their own: name, data sensitivity, integration permissions, AI use, model training, exposure, retention and deletion, and the evidence provided for four claim topics | `app/services/intake_builder.py` turns the form into claims and evidence records dated relative to today |
| 2. Assessment | Inherent risk, evidence confidence, and residual risk shown separately, with escalation reasons, claim statuses, and draft control mappings | The real evidence validator, risk engine, and control mapper |
| 3. Event log | The ordered workflow steps for that assessment | Generated from the results for that page view |
| 4. Remediation ticket | A ServiceNow-style payload labeled as a mock | Built from escalations and evidence gaps. Never sent anywhere. |

## Evidence choices

Each claim topic offers six choices, each producing a real evidence record that the validator then judges under the evidence policy.

| Choice | Record created | Expected status |
| --- | --- | --- |
| Independent report, reviewed | SOC 2 Type II report, 120 days old, reviewed, all checks pass | verified |
| Vendor's own statement, reviewed | Vendor statement, 30 days old, reviewed | self_attested |
| Independent report, not reviewed yet | SOC 2 Type II report, 60 days old, no review | not_reviewed |
| Independent report, older than its freshness limit | SOC 2 Type II report, 500 days old, reviewed | expired |
| Configuration export that contradicts the claim | Configuration export, 7 days old, reviewer marked it contradicting | conflicting |
| Nothing provided | No record | missing |

## Status

Built and live: public intake and assessment pages, with nothing saved, and Nginx rate limiting on `/try/` and the rest of the site.

The signed-in password gate was later removed, so the full demo, including the shared synthetic risk register, is also open. A private per-visitor sandbox register remains a possible future improvement.

## Guardrails

| Risk | Guardrail |
| --- | --- |
| Shared data | The full demo is open, and its risk register is shared by everyone with the link. Pages say synthetic data only. The `/try/` pages never save anything. |
| Saving visitor input | The public routes never write to the database. A test confirms a public submission does not appear in the risk register. |
| Real vendor or personal data | The form says synthetic data only. The vendor name is limited to 80 printable characters and is escaped on output. |
| Oversized or forged posts | Form posts over 16 KB are rejected. Cross-site posts are rejected by the same-origin check. |
| Overstated results | Mappings stay labeled draft, the ticket is labeled a mock, and every result says human review is required. No dollar, time, or percentage figure appears that is not calculated from the result or shown as an adjustable assumption. |
| Abuse and floods | Nginx limits each visitor to 20 requests a minute on `/try/` and 120 a minute elsewhere, with overall caps, returning HTTP 429 beyond that. |

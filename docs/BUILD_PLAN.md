# GRC Assurance Engine — Build Plan

**Project status:** Phases 1–7 initial demo slice implemented. An illustrative org policy profile and a human decision record were added after that slice. Required contract clauses are checked against evidence. The public intake questionnaire is versioned. Questionnaire 1.1.0 adds optional vendor-direction context for a reviewer. Those fields are not scored, and the residual formula is unchanged. Trust-center citations can be pasted, or a reviewer can request one HTTP GET that stores the page for human review. A fetch is not verified evidence. File import does not fetch. A per-vendor reviewer package can be exported. A file importer on `/try/import` reads questionnaire CSV and `.xlsx` files and a simulated ServiceNow JSON or CSV ticket file. It previews the rows, then runs them through the existing intake path. It does not call ServiceNow. Preview and confirm do not save. A person can then save one synthetic row with a disposition and rationale. A bot JSON contract and CLI run the same intake path. Assess alone does not save. `persist: true` with a human disposition does. The dashboard reports observed register counts, elapsed intake-to-disposition time, optional self-reported handling minutes, optional self-reported rework minutes, and optional self-reported manual touches on a disposition, kept separate from the illustrative cost formula. Those figures are not a stopwatch and are not cash savings. The control-mapping library is listed at `/mappings`. Mapping set 0.2.0 includes a small draft NIST SP 800-53 set and draft ISO/IEC 27001 and ISO/IEC 42001 review prompts. Those entries remain draft. Multi-tenant policy storage is not implemented. `/walkthrough` is a guided path over the existing pages, including a custom vendor and the optional trust-center choice on `/try/`, the conflicting-permissions scenario, and `/try/import`. A browser cookie remembers the last stop for 12 hours. The guide does not score or save on its own.
**Project type:** GRC Engineering portfolio application  
**Development approach:** Local-first, phased implementation, test-driven business logic  
**Primary IDE:** Cursor  
**Initial data:** Synthetic demonstration data only

---

## 1. Project Objective

Build a small, explainable, testable application demonstrating how a GRC Engineer can automate and improve vendor and AI-tool risk assessment workflows.

The application will turn structured vendor questionnaire responses, integration details, and evidence records into traceable risk assessments, control mappings, findings, remediation actions, workflow metrics, and cost-of-assurance reporting.

The project is intended to demonstrate:

- Practical GRC process design
- Deterministic risk evaluation
- Evidence validation and traceability
- Control mapping and framework knowledge
- Risk register and remediation workflows
- Workflow instrumentation
- Transparent cost calculations
- Automated testing
- Secure development practices
- Technical documentation and engineering judgment

The project's value comes from demonstrating that decisions are explainable, repeatable, and testable—not merely from having an attractive interface.

This is a portfolio prototype. Do not describe it as a production-ready GRC platform, a certification tool, or a substitute for an organization's approved risk management process.

## 2. Problem Statement

Vendor and AI-tool assessments frequently arrive through inconsistent channels and formats, including spreadsheets, questionnaires, emails, and workflow systems.

Common problems include:

- Repeated manual entry
- Inconsistent classification
- Missing evidence
- Conflicting vendor responses
- Unclear applicability of controls
- Manual follow-up
- Poor traceability from claims to evidence
- Inconsistent risk register updates
- Limited visibility into review delays and rework
- Difficulty estimating the operational cost of assessments

The application will model a repeatable workflow for normalizing intake, evaluating risk, validating evidence, mapping requirements, creating findings, routing remediation, and reporting measurable process outcomes.

## 3. Scope of the Initial MVP

### In scope

1. Vendor and AI-tool assessment intake
2. Rules-based risk classification
3. Separate representation of inherent risk, evidence confidence, and residual risk
4. Evidence status validation
5. A deliberately limited control-mapping library
6. Risk register records
7. Remediation actions
8. Workflow event logging
9. Three repeatable demo scenarios
10. Simulated ServiceNow-style JSON or CSV export
11. A transparent cost-of-assurance model
12. Dashboard reporting
13. Automated testing and documentation

### Out of scope initially

- Live ServiceNow integration
- Automated ingestion of arbitrary vendor documents
- Production integrations with vendor security platforms
- Autonomous AI approval decisions
- LLM-generated risk scores
- Production identity management
- Multi-tenant enterprise functionality
- Immutable or tamper-proof audit storage
- Production-grade evidence attestation
- Claims of certification or complete compliance
- Speculative financial estimates for prevented incidents

New functionality should be proposed separately before it is added.

## 4. Technology Stack

Use the following technologies:

- Python for business logic
- Flask for HTTP routes and web application behavior
- SQLite for initial persistence
- pytest for automated testing
- HTML and CSS for the interface
- Minimal JavaScript for interactions
- Git for version control
- Cursor as the primary IDE

Use a virtual environment for Python dependencies.

Keep the dependency set small and compatible with the installed Python version. Verify actual package compatibility during setup rather than assuming every dependency supports the installed interpreter.

Develop and test locally before selecting a hosting platform.

## 5. Proposed Project Structure

```text
grc-assurance-engine/
├── .cursor/
│   └── rules/
│       └── grc-engineering.mdc
├── app/
│   ├── __init__.py
│   ├── db.py
│   ├── models.py
│   ├── routes/
│   │   ├── dashboard.py
│   │   ├── assessments.py
│   │   ├── risks.py
│   │   └── remediation.py
│   ├── services/
│   │   ├── risk_engine.py
│   │   ├── evidence_validator.py
│   │   ├── control_mapper.py
│   │   ├── workflow_metrics.py
│   │   └── cost_model.py
│   ├── data/
│   │   ├── risk_rules.json
│   │   ├── control_mappings.json
│   │   └── demo_scenarios.json
│   ├── templates/
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── assessments.html
│   │   ├── assessment_detail.html
│   │   ├── risk_register.html
│   │   ├── remediation.html
│   │   └── methodology.html
│   └── static/
│       ├── css/
│       │   └── styles.css
│       └── js/
│           └── dashboard.js
├── tests/
│   ├── conftest.py
│   ├── test_app.py
│   ├── test_risk_engine.py
│   ├── test_evidence_validator.py
│   ├── test_control_mapper.py
│   ├── test_workflow_metrics.py
│   ├── test_cost_model.py
│   └── test_scenarios.py
├── docs/
│   ├── BUILD_PLAN.md
│   ├── architecture.md
│   ├── risk-model.md
│   ├── control-mapping-methodology.md
│   ├── cost-model.md
│   └── deployment-readiness.md
├── instance/
├── .gitignore
├── AGENTS.md
├── requirements.txt
├── README.md
└── run.py
```

This is the target structure, not a requirement to create every file immediately. Create files when their phase begins. Adjust the design only when there is a clear technical reason, and document important changes.

The `instance/` directory is intended for local runtime data such as the SQLite database. Runtime databases and secrets must not be committed to Git.

## 6. Phase 1 — Application Foundation

### Objective

Create the smallest working Flask application and establish a reliable development and testing workflow.

### Deliverables

- Flask application initialization
- Application factory or an equally clear initialization pattern
- Health-check endpoint
- Basic navigation
- Empty dashboard states
- Initial SQLite configuration
- pytest configuration
- Minimal requirements file
- `.gitignore`
- README with Windows Git Bash setup instructions
- Local development entry point

### Acceptance criteria

- Python dependencies install successfully in an isolated virtual environment.
- The application starts locally.
- The health-check endpoint returns the documented response.
- The initial tests run and pass.
- A new developer can follow the README.
- Local databases, virtual environments, secrets, and generated files are excluded from Git.
- No risk or cost metrics are fabricated for the empty dashboard.

Do not implement risk evaluation or framework mappings in this phase.

## 7. Phase 2 — Risk Evaluation Engine

### Objective

Build an explainable rules-based engine that evaluates vendor and AI-tool risk independently of Flask, SQLite, and the frontend.

### Risk dimensions

The model must distinguish:

**Inherent risk**

The underlying exposure associated with the service, data sensitivity, access privileges, AI behavior, external exposure, and business impact before considering safeguards.

**Evidence confidence**

The degree to which the available information supports relevant claims and safeguard assessments.

**Residual risk**

The remaining risk after considering supported safeguards and their effectiveness.

These dimensions must remain distinct. Good documentation does not automatically make a high-exposure service low risk.

### Candidate inputs

- Vendor or service category
- Data sensitivity
- AI use and level of autonomy
- Integration permissions
- External or customer-facing exposure
- Data retention and deletion practices
- Evidence status
- Evidence conflicts
- Unresolved critical gaps

### Implementation requirements

- Define the model in `docs/risk-model.md` before implementing scoring.
- Keep weights, thresholds, rule identifiers, and mandatory escalation conditions in version-controlled configuration.
- Record the rule-set version used for each assessment.
- Return structured risk factors, explanations, missing information, conflicts, and escalation reasons.
- Make identical input and rule version produce identical output.
- Treat unknown information as unknown, not as proof of failure or proof of safety.
- Do not treat self-attestation as independently verified evidence.
- Allow mandatory review or approval blocking when a critical condition is present.
- Never approve a vendor solely because a numerical score is low.
- Do not use an external LLM to generate risk scores or unreviewed approval decisions.

The initial model is illustrative. It must not be represented as an industry-standard scoring methodology or as empirically calibrated.

### Acceptance criteria

Automated tests cover:

- A normal lower-risk case
- A high-risk case
- Missing evidence
- Conflicting information
- A threshold boundary
- Mandatory escalation
- Invalid input
- Repeatability under the same rules

## 8. Phase 3 — Evidence Validation and Control Mapping

**Status:** Evidence validation and the mapping service are implemented. Mapping set 0.2.0 is intentionally small: four NIST SP 800-53 Rev. 5 controls, four ISO/IEC 27001:2022 Annex A controls, and four ISO/IEC 42001:2023 Annex A controls. Applicability and rationale remain draft. Matched prompts appear on assessment results only when a claim topic matches. The full library is listed at `/mappings` with the stored review status, source reference, and mapping-set version. The ISO entries are draft portfolio review prompts. The page does not mark draft mappings as reviewed and does not claim conformity, certification, or cross-framework equivalence.

### Objective

Make the relationship between vendor claims, evidence, controls, and assessment results explicit and traceable.

### Evidence model

Evidence records should eventually support:

- Evidence identifier
- Related claim
- Artifact name and type
- Source
- Collection date
- Review date
- Evidence status
- Reviewer notes
- Optional file hash
- Related assessment and control mappings

Support these states where applicable:

- Verified
- Self-attested
- Missing
- Conflicting
- Expired
- Not yet reviewed

Evidence freshness must be configurable based on evidence type and policy. A hash can help detect file changes but does not independently prove authenticity, accuracy, completeness, or sufficiency.

### Control mapping model

Each mapping should contain:

- Framework name
- Framework version
- Control or requirement identifier
- Short description or title
- Applicability
- Mapping rationale
- Related claims and evidence
- Source reference
- Review status

### Initial frameworks

Build a small, reviewed mapping set covering selected relevant controls or requirements from:

- NIST SP 800-53
- ISO/IEC 27001
- ISO/IEC 42001

Verify identifiers and descriptions against appropriate authoritative sources. If a reference or mapping cannot be verified, mark it draft or unverified.

ISO/IEC 42001 mappings should be limited to justified AI management-system requirements. Do not suggest that the project implements the complete standard or certifies the vendor.

Mapping set 0.2.0 is the implemented subset. It remains draft. The ISO/IEC 42001 prompts join `audit_logging` and `privacy` only. `ai_use`, model training, and decisions affecting people stay assessment fields, not claim topics. See `docs/control-mapping-methodology.md`.

Do not use cross-framework mappings to claim that frameworks or requirements are automatically equivalent.

### Acceptance criteria

- A reviewer can trace a claim to its evidence and related mapping.
- Evidence status affects the assessment appropriately.
- Missing evidence is distinguishable from confirmed failure.
- Mapping rationale and source information are available.
- Unverified mappings remain visibly unverified.
- Automated tests cover the relevant evidence and mapping behaviors.

## 9. Phase 4 — Repeatable Demonstration Scenarios

**Status:** Fixed-date synthetic scenarios are displayed under `/demo` and can be saved to the local risk register. The original three cover an evidence-supported tool, a high-risk AI service, and conflicting claims. `prohibited-ai-decisions` shows a hard restriction that stays separate from the score.

Create deterministic synthetic fixtures in `app/data/demo_scenarios.json` or an equivalently appropriate fixture structure.

### Scenario A: Evidence-supported lower-risk vendor

Inputs include limited access, low-sensitivity data, relevant evidence, and no unresolved critical gaps.

Expected behavior:

- Explain the lower-risk outcome.
- Show the evidence and rules supporting the outcome.
- Avoid making an unconditional guarantee that the vendor is safe.

### Scenario B: High-risk AI vendor

Inputs include sensitive data, broad permissions, unclear retention, and missing evidence for important safeguards.

Expected behavior:

- Identify material inherent-risk factors.
- Show missing evidence and unresolved gaps.
- Trigger configured review or approval blocking.
- Create traceable findings and remediation actions.

### Scenario C: Conflicting vendor claims

Inputs include a reassuring questionnaire response but integration details indicating broader access than declared.

Expected behavior:

- Identify the inconsistency.
- Explain which claim and information sources conflict.
- Avoid silently trusting the questionnaire.
- Route the assessment for review.
- Preserve the conflict in the finding and event history.

### Scenario requirements

Each scenario must define:

- Input data
- Expected risk factors
- Expected assessment classification
- Expected evidence statuses
- Expected mappings
- Expected escalation behavior
- Expected findings and remediation
- Expected workflow events
- Expected metric outputs

### Acceptance criteria

- Each scenario can be run repeatedly.
- Scenarios call the same business logic used by the application.
- Automated tests verify expected results.
- Mandatory escalation cannot be bypassed by a low numerical score.
- Synthetic data is clearly identified.

## 10. Phase 5 — Risk Register and Remediation

**Status:** Scenario-derived risks, related follow-up actions, status updates, and local workflow events persist in SQLite. A confirmed general intake can be saved the same way, with the human disposition stored on its own row. Arbitrary finding authoring is not implemented.

### Objective

Connect assessment results to actionable risk and remediation records.

### Risk register

Support fields for:

- Risk identifier
- Related assessment
- Risk statement
- Affected data or asset
- Inherent risk
- Residual risk
- Supporting evidence or evidence gaps
- Related controls
- Owner
- Treatment plan
- Due date
- Status
- Disposition and rationale

### Remediation

Support:

- Action identifier
- Related risk or finding
- Required action
- Priority
- Owner
- Due date
- Status
- Required evidence
- Completion notes

### Workflow events

Record meaningful events for:

- Intake received
- Triage completed
- Evidence reviewed
- Finding created
- Remediation created or updated
- Human review completed
- Disposition recorded

Events should include timestamps and useful assessment/action identifiers.

A local database event log provides traceability but is not tamper-proof or immutable.

### Simulated ServiceNow workflow

Initially, produce a documented JSON ticket payload or CSV export. The export should contain enough information to demonstrate how a finding could be routed to a real workflow system.

Do not connect to a live ServiceNow instance or require credentials for the MVP.

### Acceptance criteria

- Risks and actions persist in SQLite.
- Findings can be traced to assessments and supporting information.
- Remediation status changes are recorded.
- The simulated export is testable and documented.
- The workflow history is distinguishable from the current state.

## 11. Phase 6 — Workflow Metrics and Cost of Assurance

**Status:** `app/services/workflow_metrics.py` counts saved assessments, open remediation, residual tiers, claim and clause evidence statuses, and current dispositions from the local register. It measures elapsed intake-to-disposition time only when both `intake_received` and `decision_recorded` exist. When a decision row stores optional self-reported handling minutes, the dashboard and methods page show the median of those rows. Blank rows stay out of that median. When a decision row stores optional self-reported rework minutes, those pages show that median separately. When a decision row stores optional self-reported manual touches, those pages show that count's median separately. Handoffs, a monthly rate, authenticated effort tracking, and cash savings remain unmeasured. The figures stay apart from `calculate_cost()`. The illustrative formula, including added review and maintenance assumptions, is unchanged. One-time development cost is excluded because no source input is available. See section 22.

### Objective

Measure operational effort and make cost assumptions explicit.

Capture, where possible:

- Assessment volume
- Manual handling time
- Manual touches
- Handoffs
- Evidence failures
- Rework time
- Intake-to-disposition cycle time
- Open remediation actions
- Evidence-status distribution
- Estimated labor cost
- Estimated labor capacity released

### Required distinctions

**Elapsed cycle time** is the time between workflow milestones.

**Human handling time** is the time spent performing work.

These are not interchangeable.

A person may optionally record self-reported minutes on a disposition. That number is observed handling time for the rows that have it. It is not elapsed cycle time, and it is not copied into the illustrative formula. Blank remains unmeasured. See section 22.

A person may optionally record a self-reported manual-touch count on the same disposition. That number is a count of human touchpoints for the rows that have it. It is not handling minutes, not rework minutes, not elapsed cycle time, and it is not copied into the illustrative formula. Blank remains unmeasured. See section 22.

**Labor capacity value** estimates the value of work time made available under stated assumptions.

**Cash savings** require evidence of an actual spending reduction or avoided expenditure and must not be inferred from time reduction alone.

Distinguish observed measurements from illustrative inputs. If an effort baseline is not measured, disclose that assumption.

### Illustrative calculation

Monthly capacity value:

`assessments per month × hours avoided per assessment × loaded hourly labor rate`

Example assumptions:

- 20 assessments per month
- 0.5 hours avoided per assessment
- $60 loaded hourly labor rate

Calculation:

`20 × 0.5 × $60 = $600 per month`

This is illustrative labor capacity value, not automatically actual cash savings.

The model should account for additional human review, rework, and ongoing maintenance effort where the necessary data or disclosed assumptions exist.

Do not monetize hypothetical avoided security incidents in the MVP.

### Acceptance criteria

- Cost calculations are reproducible.
- Each dashboard figure can be traced to a source record or labeled assumption.
- Observed values and modeled values are visibly differentiated.
- Labor time is distinguished from elapsed time.
- Capacity value is distinguished from cash savings.
- Unit tests cover arithmetic and relevant edge cases.

## 12. Phase 7 — Dashboard and User Experience

**Status:** Local demo landing, scenario detail, risk register, remediation, methods, the control-mappings library page (`/mappings`), and a guided walkthrough at `/walkthrough` are implemented for the synthetic fixtures. The walkthrough reuses those pages, including a custom vendor and the optional trust-center choice on the public form, the conflicting-permissions scenario, and file import, and stores only a step id in a browser cookie. On the intake, custom-vendor, and trust-center stops, Next waits until Run assessment succeeds for that stop. File import waits until confirm, and the decision stop waits until a decision is recorded. The save stop waits until the register action. Scenario pages, the dashboard, and methods still offer Next on arrival. Ready-made cards keep `?walk=` while a guide is open. The public form, file import, and JSON/CLI intake assess a vendor. Saving that assessment is opt-in. The dashboard shows observed volume, open remediation, residual-tier and evidence-status distributions, persisted disposition counts, elapsed intake-to-disposition cycle time from stored events, self-reported handling minutes when at least one decision includes them, and self-reported rework minutes as a separate median when at least one decision includes them, and self-reported manual touches as a separate median when at least one decision includes them. Handoffs, a monthly rate, authenticated effort, and cash savings remain unmeasured, and the page says so. The illustrative cost panel stays separate. Mapping set 0.2.0 includes draft ISO/IEC 27001 and ISO/IEC 42001 review prompts beside the NIST entries, and every current mapping remains draft.

### Objective

Create a clean interface for GRC analysts, engineers, and technical reviewers.

### Pages

- Dashboard
- Vendor assessments
- New assessment form
- Assessment detail
- Risk register
- Remediation
- Control mappings
- Methodology and assumptions
- Demonstration scenarios

### Dashboard metrics

- Assessment volume
- Risk distribution
- Review backlog
- Evidence health
- Cycle time
- Manual handling effort
- Rework
- Estimated cost and capacity value
- Open remediation actions

Use actual application data and service-layer calculations. Any synthetic demonstration dataset must be labeled.

Users should be able to investigate why a risk is elevated, which evidence is missing or conflicting, which requirements are mapped, and how cost metrics were calculated.

### Acceptance criteria

- Dashboard totals agree with stored records and service calculations.
- Risk and evidence explanations are discoverable.
- Forms validate input and show understandable errors.
- Empty states work.
- The interface is usable on desktop and mobile.
- The interface does not contain hardcoded production-looking metrics.

## 13. Test Strategy

Use pytest for automated validation throughout development.

Test business logic independently of Flask and the database where practical.

Maintain tests for:

- Application initialization and health check
- Risk rules and explanations
- Evidence validation
- Control mapping
- Workflow metrics
- Cost calculations
- Database persistence and record relationships
- Demo scenarios
- Input validation
- Mandatory escalation

Run relevant tests after each phase and the full test suite before declaring a phase complete.

Do not remove or weaken tests to make a change pass. Report actual test results and investigate failures.

## 14. Security and Privacy

- Use synthetic demonstration data only.
- Do not commit secrets, credentials, private evidence, or production records.
- Ignore the virtual environment, local database, `.env`, Python caches, and generated runtime files in Git.
- Validate untrusted inputs.
- Use safe database queries.
- Keep development debug mode away from public deployment.
- Do not upload evidence to external services without deliberate approval.
- Do not describe a basic local event log as immutable.
- Do not claim production security based solely on passing tests.
- Ask for approval before deployment, DNS changes, creating cloud resources, or making destructive changes.

## 15. Git and Change Management

Use `main` as the default branch.

Work in small, reviewable changes. Commit working milestones only after reviewing the diff, checking repository status, and running the relevant tests.

Suggested commit sequence:

1. `chore: establish Flask project foundation`
2. `test: add initial application tests`
3. `feat: add explainable risk evaluation engine`
4. `feat: add evidence validation`
5. `feat: add reviewed control mappings`
6. `test: add repeatable vendor assessment scenarios`
7. `feat: add risk register and remediation workflow`
8. `feat: add workflow metrics and cost model`
9. `feat: add assurance dashboard`
10. `docs: document architecture and demonstration methodology`

Adapt commit messages to actual changes. Never claim a feature exists just because a planned commit is listed here.

## 16. Deployment Plan

Develop and verify the application locally first.

After the application is reliable:

1. Review application configuration and security controls.
2. Run the full test suite.
3. Review Git history and confirm no secrets or private data are tracked.
4. Publish the repository to GitHub.
5. Select a host that supports the Flask backend and persistent application data.
6. Configure production environment variables and persistent storage.
7. Connect a dedicated subdomain through Cloudflare.
8. Verify HTTPS, persistence, access controls, routes, and error behavior.
9. Publish a portfolio walkthrough using synthetic data.

Do not assume that a static-site platform directly hosts the Python backend. Select the hosting architecture based on the application's actual requirements.

Do not expose assessment or risk-register data publicly without appropriate access controls.

No deployment, cloud resource creation, or DNS changes may happen without explicit approval.

## 17. Portfolio Deliverables

The completed portfolio project should include:

- Working local application
- Version-controlled source code
- Automated test suite and actual results
- Architecture documentation
- Risk-model documentation
- Control-mapping methodology
- Cost-model methodology
- Three repeatable synthetic scenarios
- Sample simulated workflow export
- README with installation instructions
- Screenshots or a short application walkthrough
- Known limitations and potential production improvements

The project narrative should explain the problem, design choices, implementation, evidence flow, test strategy, observed limitations, and reproducible results.

## 18. Definition of Done

The initial MVP is complete when:

- The app starts reliably.
- The three scenarios can be run repeatedly.
- Risk decisions are deterministic and explainable.
- Evidence gaps and conflicting claims are handled correctly.
- Framework mappings are traceable and labeled according to review status.
- Findings, risks, and remediation are connected.
- Workflow events can be examined.
- Cost metrics are reproducible.
- Automated tests pass.
- Documentation accurately describes the implementation.
- The application can be demonstrated without implying that it is production-ready or certified compliant.

## 19. File-based intake import

**Status:** Implemented on the public demo as a preview-then-confirm upload. Rows are assessed by the existing intake builder and are not stored.

### Objective

Let a visitor ingest synthetic vendor intake from a spreadsheet or from a ticket-shaped file without retyping the questionnaire, and without treating that file as a live ServiceNow connection.

### Behavior

- CSV uses the standard-library `csv` module. `.xlsx` uses `openpyxl`. JSON uses the standard library.
- Questionnaire columns match the public intake form, including trust-center choices and required contract-clause evidence.
- The ServiceNow shape maps `number`, `category`, custom `u_` fields, and attachment metadata into that same form. Ticket priority, state, and `opened_at` are context. They do not set a score or the evaluation date.
- The preview lists parsed values and validation problems. It does not show a risk tier. Confirmation runs `run_intake`. A file with any invalid or conflicting row is not partially imported.
- Missing columns, non-text cells, empty files, duplicate vendors, and disagreeing attachments are reported.

### Out of scope for this increment

Live ServiceNow API calls, attachment downloads, and arbitrary PDF or email ingestion. Saving an imported vendor is a later, separate confirmation. See section 21 and `docs/import-formats.md`.

## 20. Bot intake contract

**Status:** Implemented as a JSON document, a CLI (`python -m app.cli`), and `GET/POST /api/v1/intake/...`. The assessment is the `run_intake` result. Nothing is written to the risk register.

### Objective

Let a script or agent run the public intake, or preview an intake file the importer already accepts, and read the residual tier, explanations, escalations, and rule-set version from the risk engine.

### Behavior

- The request `form` uses the public intake fields. `model_training_on_customer_data` may be omitted when `ai_use` is `none`. Unknown fields are rejected. Non-text values are rejected.
- `as_of` is an optional `YYYY-MM-DD`. When it is omitted, the process or server date is used. Evidence ages are calculated from that date.
- File preview uses `parse_upload` and does not score. `assess-file` scores every row only when the file is valid. Ticket priority stays context.
- CLI exit codes are 0 for a produced assessment or an assessable preview, 2 for validation failure, and 1 for an unexpected engine error.
- The HTTP route follows `REQUIRE_AUTH`. The demo default is false.
- The illustrative-model limits are in the JSON document and in `docs/bot-contract.md`.

### Out of scope for this increment

A live ServiceNow call, a separate scoring path, and a production API. Saving the assessment is section 21.

## 21. Saved general intake

**Status:** Implemented as an opt-in after a successful assessment. Assess alone still does not write.

### Objective

Let a confirmed import, or an explicit API or CLI decision, put one synthetic vendor on the local risk register with the same trace a scenario save already keeps: the assessment, a follow-up action when the scenario rules would create one, workflow events, and a human disposition.

### Behavior

- `/try/import` preview and confirm do not write. The result page offers a checkbox and a save button for each row. The box must be checked. The person records a disposition, a short rationale, and a decider. Minutes spent reviewing are optional. Rework minutes are a separate optional field. Manual touches are a separate optional count.
- `POST /api/v1/intake/assess` writes only when `persist` is the boolean true and `decision` includes `disposition`, `rationale`, and `decider`. Omitted `persist` means assess only. A decision sent without `persist: true` is rejected and nothing is saved. Optional `handling_minutes`, optional `rework_minutes`, and optional `manual_touches` follow the same rules as the decision form.
- The CLI accepts the same JSON fields, or `--persist` with `--disposition`, `--rationale`, and `--decider`. Flags and JSON persist fields cannot be combined. `assess-file --persist` applies that one disposition to every row. If any row cannot take it, none are saved.
- Dispositions are approve, approve with conditions, escalate, and reject. The same rules as a scenario decision apply. Approving a prohibited result requires an exception rationale. Escalate and reject do not. An exception rationale is refused when it does not mean "proceed despite the restriction."
- The residual tier stays the engine result. A low tier does not become an approval. `automatic_approval` stays null. The decision row stores the person's disposition.
- The register row is labeled synthetic demonstration data. Its id is `intake-` plus a random suffix, so it does not collide with a scenario fixture. Saving the same vendor again adds another row.
- A database created before escalate existed keeps its decision rows. Startup rebuilds the disposition check so escalate can be stored.

### Out of scope for this increment

Authenticated effort tracking, a per-visitor register, an authenticated decider, and a live ServiceNow write. Optional self-reported handling minutes, optional self-reported rework minutes, and optional self-reported manual touches are described in section 22. Elapsed intake-to-disposition time is reported from workflow events when both milestones exist. The hosted demo's register is still shared by everyone with the link. Do not put real vendor data in it.

## 22. Observed workflow metrics

**Status:** Implemented in `app/services/workflow_metrics.py` (definition version 4) and shown on the dashboard and the methods page.

### Objective

Show what the local register can actually support, and keep those figures apart from the illustrative cost assumptions.

### Behavior

- Assessment volume is the number of rows in `risks`. An unsaved public try is absent. A `scenario_id` that starts with `intake-`, or a stored `intake_origin` of `general_intake`, counts as general intake. Other rows are scenario fixtures. The dashboard labels this saved assessment volume and labels persisted dispositions as saved human decisions, so a public `/try/` run is not read as a register disposition.
- Open remediation is the number of `remediation_actions` whose status is not `completed`. `in_progress` remains open.
- Residual tier counts use `risks.residual_tier`.
- Claim evidence counts use each stored claim's `evidence_status`. Clause evidence counts use the stored required-clause statuses and stay in their own list. A missing claim status is an evidence gap, not a confirmed control failure.
- Disposition counts use the current `decisions` row. `decision_recorded` events are counted separately, so a replacement does not add a second current disposition.
- Cycle time is the elapsed seconds from the earliest `intake_received` timestamp to the earliest `decision_recorded` timestamp on that same risk. The mean is rounded half up to two decimal places. A shared timestamp is a measured span of 0 elapsed seconds. A scenario with no intake event, a row with no disposition event, and a row whose timestamps are reversed or unreadable stay out of the average.
- The illustrative cost formula is still `calculate_cost()` from `app/data/cost_assumptions.json`. Observed volume is a count of saved rows, elapsed cycle time is a clock span, self-reported handling minutes are a third figure, self-reported rework minutes are a fourth, and self-reported manual touches are a fifth. None of those values is copied into that formula.
- `handling_minutes` is an optional field on the decision row. The scenario decision form, the import save form, and API or CLI persist accept it. Omit, null, and blank mean unmeasured and store null. A non-negative whole number of minutes is stored as that integer. Zero is a reported zero. Negative numbers, fractions, booleans, and other text are rejected and are not rewritten. A database created before the column existed gains it on startup. Older decision rows keep a null.
- `rework_minutes` is a separate optional field on the same decision row. It records self-reported minutes spent redoing work after a first pass. The scenario decision form, the import save form, and API or CLI persist accept it. Omit, null, and blank store null. A non-negative whole number is stored. Zero is a reported zero. Negative numbers, fractions, booleans, and other text are rejected and do not rewrite the row. Replacing a decision with a blank rework field clears a previously stored number. A database created before the column existed gains it on startup. Older decision rows keep a null. Rework minutes are not handling minutes.
- `manual_touches` is a separate optional field on the same decision row. It records a self-reported count of human touchpoints on that assessment. The scenario decision form, the import save form, and API or CLI persist accept it. Omit, null, and blank store null. A non-negative whole number is stored. Zero is a reported zero. Negative numbers, fractions, booleans, and other text are rejected and do not rewrite the row. Replacing a decision with a blank manual-touches field clears a previously stored number. A database created before the column existed gains it on startup. Older decision rows keep a null. Manual touches are not handling minutes and not rework minutes.
- When at least one current decision has a handling number, the observed panel shows self-reported human handling time. The headline figure is the median of those rows. For an even count, the median is the mean of the two middle values. The mean is rounded half up to two decimal places. Nulls stay out of both. When no decision has a number, the panel says the figure is not measured. It does not show a zero average. Rework minutes use the same median rules on their own card. Manual touches use the same median rules on their own card.
- When at least one current decision has a rework number, the observed panel shows self-reported rework time as that median. Nulls stay out. When none do, the card says the figure is not measured. The label says the figure is self-reported, not authenticated, not elapsed cycle time, not handling minutes, and not used by the cost model.
- When at least one current decision has a manual-touch count, the observed panel shows self-reported manual touches as that median. Nulls stay out. When none do, the card says the figure is not measured. The label says the figure is self-reported, not authenticated, not elapsed cycle time, not handling minutes, not rework minutes, and not used by the cost model.
- The minutes and the touch count are self-reported. The application does not run a timer, and it does not check the number against an identity system or a timesheet. Replacing a decision without a number clears the previous number for that field. The reviewer package includes each number when it is stored. It says handling time was not reported when `handling_minutes` is null, it says rework time was not reported when `rework_minutes` is null, and it says manual touches were not reported when `manual_touches` is null.

### Out of scope for this increment

Authenticated effort tracking, handoffs, a monthly assessment rate, cash savings, and monetized avoided incidents. The event log is still a local trace. It can be edited by someone with access to the database. A self-reported number can be edited the same way. It is not a tamper-proof timesheet.

## 23. Trust-center fetch

**Status:** Implemented as an optional step on the public intake form and the bot JSON/CLI assess path. File import stays paste-only.

### Objective

Let a reviewer supply a trust-center URL and have the application GET that page into an evidence artifact for human review, while pasted citations still work when fetch is not requested.

### Behavior

- The questionnaire field `fetch_trust_center` accepts `no` or `yes`. Omitted and `no` store the URL and do not open it. `yes` performs one HTTP GET with the standard library (`urllib`). There is no scraper, headless browser, or third-party trust-center API.
- A successful fetch stores the source URL, the fetch timestamp (the assessment date at 00:00 UTC), the HTTP status, a short summary, and an excerpt. The evidence validator statuses that record. The source is `vendor` and no review is recorded, so the status is `not_reviewed`. It cannot become `verified`.
- The fetch artifact is not one of the scored claims. It does not change evidence confidence, the residual tier, or automatic approval. `automatic_approval` stays null.
- An HTTP error, a timeout, a DNS failure, or too many redirects is a failed fetch. The result records the error, the validator status is `missing`, and the mock remediation ticket names the gap. It is not stored as a successful collection.
- A URL that is not `http` or `https`, that includes a username or password, or that points at a private, loopback, link-local, or metadata address is rejected before a connection. The same check runs on each redirect. Name resolution uses an injectable resolver in tests. The check does not pin DNS against a later address change.
- Tests inject the HTTP opener and the resolver. They do not use the live internet.
- Pasted SOC, security, and privacy choices are unchanged. A URL with no artifact choice and no fetch still creates no scored evidence record.

### Out of scope for this increment

Authenticated trust centers, PDF parsing, a headless browser, a paid trust API, and treating the fetched page as independent verification or certification. File import does not fetch. The hosted demo should stay on synthetic or fictional URLs.

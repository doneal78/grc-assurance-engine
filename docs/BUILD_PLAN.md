# GRC Assurance Engine — Build Plan

**Project status:** Phases 1–7 initial demo slice implemented. An illustrative org policy profile and a human decision record were added after that slice. Required contract clauses are checked against evidence. The public intake questionnaire is versioned. Trust-center citations are pasted evidence, not a live fetch. A per-vendor reviewer package can be exported. General intake that is saved, and observed metrics, remain out of scope. Multi-tenant policy storage is not implemented.
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

**Status:** Evidence validation and the initial NIST mapping service are implemented. The mapping set is intentionally small and all applicability/rationale decisions remain draft. Mapping results are not connected to the web interface yet.

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

**Status:** Scenario-derived risks, related follow-up actions, status updates, and local workflow events persist in SQLite. The initial workflow is intentionally limited to the three synthetic scenarios; general-purpose intake and finding authoring are not implemented.

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

**Status:** An independent cost service and dashboard/methodology example calculate illustrative labor capacity, including added review and ongoing maintenance assumptions. No observed handling-time or cycle-time measurement is implemented; the model does not claim cash savings. One-time development cost is excluded because no source input is available.

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

**Status:** Local demo landing, scenario detail, risk register, remediation, and methods pages are implemented for the synthetic fixtures. General-purpose assessment intake, observed workflow metrics, and full dashboard reporting remain unimplemented.

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

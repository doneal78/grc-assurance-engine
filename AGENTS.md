GRC Assurance Engine — Project Instructions

1. Project Purpose

Build a small, defensible GRC Engineering portfolio application for vendor and AI-tool risk intake, evidence validation, control mapping, risk management, remediation workflows, and cost-of-assurance measurement.

The goal is to demonstrate practical GRC Engineering skills through working software, repeatable tests, traceable decisions, and documented results—not simply a polished dashboard.

This project is initially a local portfolio prototype. Do not represent it as a production-ready GRC platform, a compliance certification tool, or a replacement for an organization's formal risk management process.

2. Technology Stack

Use the following technologies for the initial application:

Python

Flask

SQLite

pytest

HTML, CSS, and minimal JavaScript

Git for version control

Cursor as the primary IDE

Develop and test locally before considering deployment.

Keep dependencies minimal. Do not introduce a new framework, external service, cloud resource, or database platform without explaining the benefit and receiving approval before implementation.

3. Application Architecture

Separate the application into these responsibilities:

Web routes and presentation

Business logic and evaluation rules

Database access and persistence

Framework mapping data

Automated tests

Documentation

Keep risk scoring, evidence validation, framework mapping, workflow metrics, and cost calculations independent of Flask route handlers wherever practical.

The user interface must display results produced by the business logic. It must not independently invent risk scores, evidence statuses, financial metrics, or approval decisions.

Keep functions readable, focused, and straightforward to test.

4. Risk Evaluation Requirements

The risk engine must use explicit, deterministic rules.

Identical input data evaluated with the same rule-set version must produce identical results.

Keep these concepts separate:

Inherent risk: risk arising from the vendor, service, data, access, AI capabilities, and business context before considering safeguards.

Evidence confidence: how reliably the supplied information supports the relevant claims and safeguards.

Residual risk: the risk remaining after considering supported safeguards and their effectiveness.

Do not treat these concepts as interchangeable.

Every material risk decision must have an explanation identifying the factors and rules that contributed to the result.

Missing information must not silently count as a verified safeguard.

Missing evidence alone does not prove that a control has failed. Distinguish unknown, self-attested, verified, conflicting, expired, and confirmed-failure states.

A vendor must never be automatically approved solely because its numerical risk score is low. Configured critical conditions must be able to require human review or block automatic approval.

Record the rule-set version used for each assessment.

Keep scoring rules, weights, thresholds, and mandatory escalation conditions in version-controlled configuration rather than scattering unexplained numeric values throughout the code.

Do not use an external AI model or LLM to make unreviewed risk-scoring or approval decisions.

Label the initial risk model as an illustrative portfolio model until it has been validated against an approved organizational methodology.

5. Evidence Validation Requirements

Keep the following concepts distinct:

Vendor claim

Evidence artifact

Evidence validation result

Applicable control or requirement

Assessment conclusion

A vendor's statement must not automatically be treated as independently verified evidence.

Evidence records should eventually support a unique identifier, related claim, artifact name, source, evidence type, collection date, review date, status, reviewer notes, and an optional file hash.

A file hash can help detect changes to a file. It does not independently prove the file's authenticity, accuracy, completeness, or sufficiency.

Support appropriate evidence statuses, including:

Verified

Self-attested

Missing

Conflicting

Expired

Not yet reviewed

Evidence freshness requirements should be configurable based on evidence type and policy. Do not assume that every artifact has the same expiration period.

6. Control Mapping Requirements

Framework mappings must be traceable and reviewable.

Each mapping should support:

Framework name

Framework version

Control or requirement identifier

Title or short description

Applicability

Mapping rationale

Related claims and evidence

Source reference

Review status

Use authoritative sources to verify control identifiers and descriptions before labeling a mapping as reviewed.

If an identifier, description, applicability decision, or mapping rationale cannot be verified, label the mapping as draft or unverified. Never invent framework details to complete the dashboard.

Initial mapping coverage should be intentionally limited and may include relevant NIST SP 800-53 controls, ISO/IEC 27001 controls, and selected ISO/IEC 42001 requirements.

A cross-framework mapping does not automatically establish equivalence, complete conformity, or certification.

Do not claim that this prototype certifies a vendor or an organization against any framework.

7. Workflow and Risk Register Requirements

The application should eventually support traceability between:

Assessments

Vendor claims

Evidence records

Control mappings

Findings

Risks

Remediation actions

Workflow events

Final dispositions

Risk records should distinguish inherent risk from residual risk and retain the associated rationale.

Remediation actions should include an associated finding or risk, description, priority, owner, due date, status, and completion notes where appropriate.

Record important workflow events such as intake, triage, evidence review, finding creation, remediation, review, and disposition.

A local application event log is useful for traceability but must not be represented as immutable or tamper-proof.

Simulate external workflow integrations such as ServiceNow through documented JSON payloads or CSV exports before considering a live integration.

8. Cost-of-Assurance Requirements

The cost model must distinguish:

Observed measurements from modeled assumptions

Human handling time from elapsed cycle time

Labor capacity released from actual cash savings

Baseline effort from assisted-workflow effort

One-time development cost from recurring operating and maintenance cost

Where practical, measure assessment volume, handling time, manual touches, handoffs, evidence failures, rework, and intake-to-disposition cycle time.

Every financial result must be reproducible from its source records, model inputs, and documented formula.

A modeled labor capacity value must not be described as cash savings without evidence that an equivalent reduction in actual spending occurred.

Include review and maintenance effort when the available data or explicitly labeled assumptions support it.

Do not monetize hypothetical avoided security incidents in the initial MVP.

Do not claim measured savings when the application has only used illustrative inputs.

9. Testing Requirements

Use pytest for automated testing.

Business logic must be independently testable without starting a browser or depending on live third-party services.

Write tests for:

Expected positive cases

Negative cases

Missing information

Conflicting information

Expired or self-attested evidence

Threshold boundaries

Mandatory escalation

Invalid inputs

Persistence and relationships

Repeated scenario execution

Cost calculations

Relevant error conditions

Test expected behavior, not merely whether code runs.

Do not remove or weaken a failing test just to make the implementation pass.

Run the relevant tests after changing business logic and run the full test suite before declaring a phase complete.

Never claim tests passed unless they actually ran and passed. Report the commands and results accurately.

10. Security and Privacy

Use synthetic demonstration data only.

Do not commit API keys, access tokens, passwords, credentials, production data, private evidence, local database files, or secret environment files.

Validate user input and use safe database access patterns, including parameterized queries or equivalent safe APIs.

Keep development secrets out of source control.

Do not deploy the Flask development server publicly or expose debug mode in a public environment.

Do not upload evidence or potentially sensitive data to external AI services.

Ask for approval before deploying the application, changing DNS, creating cloud resources, performing destructive operations, or connecting integrations that require credentials.

Do not claim the application is secure or production-ready merely because basic tests pass.

11. Development Workflow

Work in small, reviewable phases.

Before making substantial changes:

Inspect the existing repository and relevant files.

Explain the planned change and why it is needed.

Identify the files expected to change.

Implement only the current phase or agreed feature.

Run the relevant tests and checks.

Review the code changes.

Summarize changed files, actual test results, limitations, and the next recommended step.

Preserve existing working functionality.

Do not rewrite unrelated parts of the application without a clear technical reason.

Do not install packages, create cloud resources, deploy, or perform consequential actions without appropriate approval.

12. Documentation Requirements

Keep the following documentation accurate as the project evolves:

README.md

docs/BUILD_PLAN.md

docs/architecture.md

docs/risk-model.md

docs/control-mapping-methodology.md

docs/cost-model.md

Document design decisions, assumptions, data sources, testing results, and known limitations.

Update documentation when the implemented behavior changes.

13. Portfolio Honesty

This project should demonstrate how GRC engineering can make assessment workflows more traceable, testable, consistent, and measurable.

Clearly identify:

Synthetic demonstration data

Illustrative risk rules

Draft or unverified framework mappings

Simulated integrations

Modeled financial estimates

Features that are not implemented

Security and operational limitations

Do not claim production effectiveness, completed compliance certification, validated financial savings, or proven risk reduction unless supported by appropriate evidence.

14. Working Style

Prefer clear, maintainable code over unnecessary complexity.

Explain meaningful architectural trade-offs.

Do not invent framework references, measurements, test results, or requirements.

If an important decision remains unresolved, present the alternatives and a recommendation before implementing it.

Keep the project small enough that a GRC Engineer can explain how each major component works, why its rules exist, how it was tested, and what its limitations are.
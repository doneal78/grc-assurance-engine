# GRC Assurance Engine

A small Flask portfolio application for evidence-first vendor and AI-tool risk review. It uses synthetic data only. It is an illustrative prototype, not a production GRC system, a certification tool, or a substitute for an organization's formal risk process.

The same inputs and the same rule-set version produce the same result. Inherent risk, evidence confidence, residual risk, and the policy outcome stay separate. A low residual tier is not an approval.

Observed figures use metrics definition 9 and come from saved rows. The cost panel is a separate modeled example from `calculate_cost()`. The table below says which result is measured and which is modeled.

ISO/IEC 27001 and ISO/IEC 42001 entries in mapping set 0.2.0 stay draft. Nothing in this project certifies a vendor or an organization.

The workflow event log is tamper-evident (SHA-256 hash chain), not tamper-proof. A person who can rewrite the database can rebuild the chain.

## What this demonstrates

- Evidence-first third-party and AI vendor risk review.
- Explainable, versioned rules.
- Draft NIST, ISO/IEC 27001, and ISO/IEC 42001 control mapping. The ISO entries stay draft.
- Human-in-the-loop decisions with a tamper-evident (SHA-256 hash chain) audit trail.

**Live demo:** <https://grc-assurance.davidoneal.dev/>

**Walkthrough:** <https://grc-assurance.davidoneal.dev/walkthrough/>

Start at `/try/` to run a vendor review without saving. The hosted demo is open, with no login, when the host is up. The current pin is recorded in [docs/deployment.md](docs/deployment.md).

## Metrics

| Metric | Source | Measured or modeled | Where defined |
| --- | --- | --- | --- |
| Saved assessment volume | `risks` rows in this browser's sandbox, plus rows with no sandbox id | Measured count. An unsaved `/try/` run is not included. | Definition 9, `app/services/workflow_metrics.py` |
| Open remediation | `remediation_actions` whose status is not `completed` | Measured count | Definition 9 |
| Persisted dispositions | Current `decisions` row | Measured count of human decisions | Definition 9 |
| Elapsed cycle time | Earliest `intake_received` to earliest `decision_recorded` on the same risk | Measured clock span when both events exist. Otherwise not measured. | Definition 9 |
| Monthly assessment rate | `decisions.decided_at` in a covered 30-day window | Measured count only when those timestamps cover 30 days. Otherwise not measured. | Definition 9 |
| Self-reported handling time | Optional `handling_minutes` on a decision | Measured median of reported rows. Optional. | Definition 9 |
| Self-reported rework time | Optional `rework_minutes` | Measured median. Optional. Separate from handling time. | Definition 9 |
| Self-reported manual touches | Optional `manual_touches` | Measured median. Optional. | Definition 9 |
| Self-reported handoffs | Optional `handoffs` | Measured median. Optional. | Definition 9 |
| Authenticated effort | Optional minutes a signed-in reviewer entered | Measured median when a number is stored. The public form does not ask. Not measured on the open demo unless a signed-in disposition stored minutes. | Definition 9 |
| Cash savings | Optional whole dollars a signed-in reviewer entered | Measured median when a number is stored. Not a wage times the other figures. Not measured on the open demo unless a signed-in disposition stored dollars. | Definition 9 |
| Avoided-incident value | `incident_cost` and `avoided_incident_count` in `app/data/cost_assumptions.json` | Modeled assumption. Not measured while either input is null. Not an input to `calculate_cost()`. | `avoided_incident_value()` in `app/services/cost_model.py` |
| Labor capacity | Versioned assumptions in `app/data/cost_assumptions.json` | Modeled example. It does not read the observed rows above. | `calculate_cost()`, model 0.1.0 |

The longer distinctions among these figures are in [docs/cost-model.md](docs/cost-model.md). Definition 9 is unchanged. `calculate_cost()` does not read the observed rows.

## Versions

| Version | Current | What it governs |
| --- | --- | --- |
| Walkthrough | 1.2.5 | The guided stop list and coaching copy in `app/services/walkthrough.py`. It does not score or save on its own. |
| Observed metrics | Definition 9 | Counts, clock spans, and medians in `app/services/workflow_metrics.py`. Separate from `calculate_cost()`. |
| Risk rules | 0.3.0 | Inherent score, residual tier, escalation rules, and missing-information handling in `app/data/risk_rules.json`. Illustrative. |
| Scenario set | 0.3.0 | The synthetic scenarios in `app/data/demo_scenarios.json`. |
| Evidence policy | 0.2.0 | Evidence status and freshness in `app/data/evidence_policy.json`. |
| Intake questionnaire | 1.1.0 | Public form questions in `app/data/intake_questionnaire.json`, including unscored direction context. |
| Org policy | `ORG-AI-USE` 1.1.0 | The hard restriction HR-001 and required clause CC-001 in `app/data/org_policy.json`. Illustrative, not an approved corporate policy. |
| Mapping set | 0.2.0 | The control-mapping library in `app/data/control_mappings.json`. NIST entries were checked against NIST's catalog. ISO/IEC 27001 and ISO/IEC 42001 entries stay draft. |
| Cost model | 0.1.0 | The illustrative labor-capacity assumptions in `app/data/cost_assumptions.json`. |
| Reviewer-package export | 1.0.0 | The JSON and Markdown handoff built by `app/services/intake_export.py`. |

## Reviewer package

The JSON and Markdown download is a handoff for one vendor: the answers, the evaluation, the policy outcome, the evidence summary, and the human decision when one is recorded. It is not an approval, and nothing in it is sent to ServiceNow. A scenario fixture has no intake questionnaire version. Markdown labels that `N/A (scenario fixture)`. JSON keeps `questionnaire` null and adds `questionnaire_note` with the same label. `export_version` stays 1.0.0.

## Requirements

Windows with Git Bash and Git, plus Python 3.12 or newer. Development uses Python 3.14. The hosted server runs Ubuntu 24.04's Python 3.12. The test suite runs on both.

## Setup (Git Bash)

```bash
cd ~/Documents/grc-assurance-engine
python -m venv .venv
source .venv/Scripts/activate
python -m pip install -r requirements.txt
```

## Run locally

```bash
python run.py
```

Then open <http://127.0.0.1:5000/>. The app listens on 127.0.0.1 only, with debug mode off. Stop it with Ctrl+C. Do not expose the development server to the internet.

## Demo walkthrough

Open **Walkthrough** in the header, or go to `/walkthrough`, and choose **Start at intake**. The guide is thirteen stops on the live pages. A cookie in this browser remembers the last stop for 12 hours. Start over clears that cookie and does not delete saved risks. Pages without `?walk=` stay free-form. The pages do the scoring. The notes only say what to notice.

1. **Intake** on `/try/`. Running a ready-made vendor does not save it.
2. **Your own vendor.** Use a made-up name. Run assessment does not save. **Change these answers** reopens the form.
3. **Trust center is optional.** Leave fetch at no and the URL is stored without being opened. Choosing fetch stores an excerpt for review. That excerpt is not verified evidence and does not approve the vendor.
4. **Evidence-supported vendor.** Inherent risk, evidence confidence, residual risk, and the policy outcome are separate. A low residual tier is not an approval.
5. **Contract clause contradicted.** CC-001 is conflicting. That status does not change the score, the residual tier, or the review path.
6. **Conflicting permissions claim.** The claim is conflicting, the residual tier stays high, and ESC-003 escalates the review.
7. **High-risk AI.** The score is provisional, the tier is undetermined, and the review route is escalated. Missing evidence is a gap, not a confirmed control failure.
8. **AI tool that decides eligibility.** The policy outcome is prohibited under HR-001 while residual risk can stay low. The low tier does not clear the restriction.
9. **Save is opt-in.** Saving writes a synthetic row in this browser's sandbox. Saving is not an approval.
10. **Decision and export.** Escalate or reject without an exception rationale, or approve a prohibited result only with one. Download the JSON or the summary. Nothing is sent to ServiceNow.
11. **File import** on `/try/import`. Preview has no score. Confirm runs the same engine and does not save. ServiceNow is not called.
12. **Dashboard.** Definition 9 figures for this browser's saved rows. The modeled cost panel stays on its assumptions. See the metrics table above and [docs/cost-model.md](docs/cost-model.md).
13. **Methods.** Rule set, org policy, clause check, formula, and glossary. Mappings stay draft.

The local demo does not require credentials. The hosted demo is open with no login. An optional HTTP Basic gate stays off unless `REQUIRE_AUTH` is true. The hosted site does not set that variable. See [docs/deployment.md](docs/deployment.md).

## Run the tests

```bash
python -m pytest
```

GitHub Actions runs this suite on Python 3.12 and 3.14 for every push and pull request. It does not deploy.

## Bot and script intake

```bash
python -m app.cli assess request.json
python -m app.cli preview vendor-intake.csv --as-of 2026-10-14
python -m app.cli assess-file servicenow-intake.json --as-of 2026-10-14
python -m app.cli assess request.json --persist --disposition escalate --rationale "Low tier is not an approval." --decider "GRC analyst"
```

`assess` reads a JSON request from a file or from stdin (`-`). `preview` does not score. `assess-file` scores every row only when the whole file is valid. `--persist` saves only when a disposition, rationale, and decider are present. Optional self-reported fields are described in [docs/bot-contract.md](docs/bot-contract.md) and [docs/cost-model.md](docs/cost-model.md). The CLI has no signed-in session, so it does not store authenticated effort or cash savings.

Exit 0 means an assessment was produced, or a preview can be assessed. Exit 2 means validation failed. Exit 1 means the engine raised an unexpected error.

`GET /api/v1/intake/contract` lists the live fields. `POST /api/v1/intake/assess` runs one request. With `REQUIRE_AUTH` left false, the routes do not ask for a password. The request is not saved unless `persist` is true and `decision` names a disposition, rationale, and decider. Public `/try/` and import still reject crafted signed-in fields.

## Health check

`GET /health` returns status 200 and `{"status": "ok", "service": "grc-assurance-engine", "database": "reachable"}` when the process is running and the configured SQLite file can be opened read-only so its catalog can be read. If that read fails, the same route returns status 503 and `{"status": "unavailable", "service": "grc-assurance-engine", "database": "unreachable"}`. The body does not include the filesystem path, the SQL, or the driver message. The check does not validate schema completeness, integrity, or backups.

## Project notes

The health endpoint lives in `app/routes/health.py`. It is an operational endpoint, not a page.

Runtime data belongs in the ignored `instance/` folder. Scenario fixtures and saved data are synthetic. Delete that local database file yourself if you want to reset a development copy. Startup adds columns for older databases and does not drop saved rows. A risk saved before the policy columns existed has no policy reference, and a decision cannot be recorded on it until the scenario is saved again. Workflow events gain `prev_hash`, `hash`, and `chain_origin` when those columns are missing. Rows already stored are hashed once and marked `chained_after_the_fact`. A later startup does not rehash an edited row. Risks gain `sandbox_id` when that column is missing. Rows with no sandbox id stay visible to every visitor. New browser saves use a signed cookie that is not a login. `/dashboard` and `/metrics` redirect to `/`.

## Data and limitations

Every provided record is synthetic. The org policy, the intake questionnaire, and the risk rules are illustrative. A response does not approve a vendor. A human disposition is stored only when the caller confirms a save, and it is a separate field from the residual tier. A trust-center URL is stored as a citation unless fetch is set to yes. That GET stores vendor-published material for review. It is not verified evidence. File import does not fetch. A ServiceNow file is a simulated ticket export. The application does not connect to ServiceNow.

A prohibited outcome is not a legal determination. A contract-clause status is an evidence result, not a legal conclusion. The workflow event log is tamper-evident (SHA-256 hash chain), not tamper-proof. The decider's name is not authenticated. What production use would still require is listed in [docs/architecture.md](docs/architecture.md).

Mapping a requirement to a control does not prove implementation or compliance. No part of this project claims conformity, certification, cross-framework equivalence, production readiness, or proven risk reduction. The ISO/IEC 27001 and ISO/IEC 42001 entries stay draft.

Observed counts and the modeled cost panel stay apart. See the metrics table and [docs/cost-model.md](docs/cost-model.md). The hosted demo uses synthetic data only. A confirmed import save and a persist request write into that browser's sandbox. The sandbox cookie is not a login. Seeded scenario pages stay visible to every visitor. Rows with no sandbox id stay visible to every visitor. That includes command-line saves and rows stored before sandboxes existed. The register page does not delete them.

## Hosted demo

The hosted demo is at <https://grc-assurance.davidoneal.dev> when the host is up. A push to `main` does not deploy. The host serves the commit last installed with `infra/deploy-app-revision.sh`. The pin, the 2026-10-30 restore drill, and the off-box SQLite copies are recorded in [docs/deployment.md](docs/deployment.md).

The host is a small portfolio demo, not a production service. Its Lightsail bundle is $7/month before snapshot storage or other charges. SQLite is suitable for this single-instance synthetic demo only. There is no login. The repository Nginx file limits `/try/` and `/api/` to 20 requests a minute per visitor and other pages to 120. The live host uses the file installed on the server.

## Credit

The guided scenario runner, event log, and mock ticket presentation were inspired, with permission, by irvinthev's [GRC Cost of Assurance Dashboard](https://irvinthev.github.io/grc-cost-of-assurance-dashboard/). The code, rules, and data in this repository are separate and original.

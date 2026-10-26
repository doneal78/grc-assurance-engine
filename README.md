# GRC Assurance Engine

A small Flask application for evidence-first vendor and AI-tool risk assessments. It is a portfolio project that uses synthetic data only. It is not a production system, and it has no live ServiceNow integration.

## Current status

The local Flask application has an app factory, a health-check endpoint, a responsive demo interface, and pytest coverage.

The risk engine in `app/services/risk_engine.py` evaluates assessments against the versioned illustrative rules in `app/data/risk_rules.json` and the single org policy in `app/data/org_policy.json`. It is a draft portfolio model, not a calibrated methodology, and the policy profile is illustrative rather than an approved corporate policy.

Intake asks whether the AI makes fully automated decisions about people's eligibility, safety, or similar outcomes with no human review. A yes answer produces a prohibited outcome that cites restriction HR-001 and policy `ORG-AI-USE` version 1.1.0. That outcome is separate from the score. The required contract clause in the starter profile, no vendor model training on company or customer data, is checked against vendor evidence. Verified, self-attested, missing, conflicting, expired, and not reviewed use the same evidence vocabulary as a claim. A gap is shown to the reviewer and does not block the decision. Another restriction or clause is added by extending those lists. On a saved risk, a person records approve, approve with conditions, escalate, or reject. Approving a prohibited result requires an exception rationale. Escalating or rejecting it does not. The prohibited flag stays on the assessment. The engine does not make that decision. A low residual tier is not an approval.

The public form follows intake questionnaire 1.0.0. Model training is asked only when AI use is not none. A trust-center URL can be stored with pasted SOC, privacy, and security choices. Those choices become evidence records. The application does not fetch the URL, and the URL does not approve the vendor. A reviewer can download one vendor as JSON and as a text summary from the public result, a demo scenario, or a saved risk. The download includes the decision when one is recorded. It is a handoff, not a disposition.

`/try/import` reads a questionnaire CSV or `.xlsx` file, or a simulated ServiceNow JSON or CSV ticket file, then shows a preview before running the same intake path. The ServiceNow file is not a live connector. Preview and confirm do not save. The result page can save one synthetic vendor when a person checks the box and records a disposition and rationale. See [docs/import-formats.md](docs/import-formats.md). Reading `.xlsx` uses `openpyxl`. CSV and JSON stay in the Python standard library.

A script can run that same intake without the browser. `python -m app.cli assess request.json` and `POST /api/v1/intake/assess` return the risk engine's residual tier, explanations, escalations, and rule-set version. Nothing is written unless the caller sets `persist` to true and supplies a human disposition, rationale, and decider. See [docs/bot-contract.md](docs/bot-contract.md).

Phase 3 is implemented as framework-independent services. The evidence validator in `app/services/evidence_validator.py` derives claim evidence status using configurable freshness limits in `app/data/evidence_policy.json`. The control mapper in `app/services/control_mapper.py` joins explicitly tagged claims to a small NIST SP 800-53 mapping library in `app/data/control_mappings.json`; the mappings are draft pending human review. **Control mappings** lists that library. Assessment pages show only the topics that matched. ISO/IEC 27001 and ISO/IEC 42001 are not in the library. See `docs/evidence-model.md` and `docs/control-mapping-methodology.md`.

The local web interface includes repeatable synthetic scenarios that run the same risk, evidence, policy, and mapping services and show explanations and trace links. One scenario is an eligibility tool whose score stays moderate while the policy outcome is prohibited. A scenario can be added to the local SQLite risk register with a follow-up action, a human decision, and workflow history. The dashboard counts that register: saved assessments, open remediation, residual tiers, evidence statuses, dispositions, and elapsed intake-to-disposition time when both workflow events exist. A separate panel keeps the reproducible modeled labor-capacity example. The modeled panel is an illustrative formula. The elapsed cycle time is a clock span, and human handling time stays unmeasured. See `docs/BUILD_PLAN.md` and `docs/cost-model.md`.

## Requirements

Windows with Git Bash and Git, plus Python 3.12 or newer. Development uses Python 3.14; the hosted server runs Ubuntu 24.04's Python 3.12, and the test suite runs on both.

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

Then open http://127.0.0.1:5000/ in a browser. The app listens on 127.0.0.1 only, with debug mode off. Stop it with Ctrl+C. Do not expose the development server to the internet.

## Demo walkthrough

1. Open **Demo scenarios** and choose a synthetic case, including **AI tool that decides eligibility**.
2. Review the inherent score/tier, confidence, residual result, policy outcome, explanation, evidence statuses, escalations, and draft control prompts. On the eligibility case, the score and the prohibited outcome are separate, and HR-001 cites the policy version.
3. For the high-risk, conflicting, or prohibited case, choose **Add to risk register**, assign an action owner/due date, and update its status. On the prohibited case, record a decision. Approval requires an exception rationale. Rejection does not. The prohibited outcome remains. The risk record, decision, and local workflow events stay in the ignored SQLite database under `instance/`. Open the dashboard afterward. The observed panel counts that saved scenario, and cycle time stays unmeasured until a general intake is saved with both an intake event and a disposition event. The cost panel underneath still uses the illustrative assumptions.
4. Open **Contract clause contradicted** and compare it with the evidence-supported vendor. CC-001 is conflicting in one case and verified in the other. The score does not move because of that status.
5. Open **Control mappings** to browse the draft NIST SP 800-53 library, including review status and the catalog source link. Then open **Methods** to review the rule set, the org policy, how required contract clauses are checked, mapping limitations, the observed-metric definitions, and the modeled cost formula. The observed counts stay out of that formula.
6. Open **Public demo**, then **import a questionnaire file**. Download a sample, preview it, and confirm. The preview has no score. The result page uses the risk engine. Confirm does not save. Check **Save this synthetic vendor**, leave the disposition on escalate or choose another, and record a rationale. The risk register then shows that vendor. The residual tier and the disposition are separate. ServiceNow is not called.

The local demo does not require credentials, network services, or private evidence. The hosted demo is open with no login. The application still has an optional HTTP Basic gate, and it stays off unless `REQUIRE_AUTH` is set to true. The hosted site does not set that variable. See [docs/deployment.md](docs/deployment.md).

## Run the tests

```bash
python -m pytest
```

GitHub Actions runs this suite on Python 3.12 and 3.14 for every push and pull request.

## Bot and script intake

```bash
python -m app.cli assess request.json
python -m app.cli preview vendor-intake.csv --as-of 2026-10-14
python -m app.cli assess-file servicenow-intake.json --as-of 2026-10-14
python -m app.cli assess request.json --persist --disposition escalate --rationale "Low tier is not an approval." --decider "GRC analyst"
```

`assess` reads a JSON request from a file or from stdin (`-`). The request `form` uses the same fields as the public intake form. `preview` parses a CSV, `.xlsx`, or simulated ServiceNow file and does not score it. `assess-file` scores every row only when the whole file is valid. `--persist` saves only when a disposition, rationale, and decider are present. The same flags on `assess-file` apply that one disposition to every row, or save none.

Exit 0 means an assessment was produced, or a preview can be assessed. Exit 2 means validation failed. Exit 1 means the engine raised an unexpected error. The JSON document is written to stdout.

`GET /api/v1/intake/contract` lists the live fields. `POST /api/v1/intake/assess` with `Content-Type: application/json` runs one request. With `REQUIRE_AUTH` left false, which is the demo default, the routes do not ask for a password. The request is not saved unless `persist` is true and `decision` names a disposition, rationale, and decider. Assess alone does not write. The contract, examples, and limitations are in [docs/bot-contract.md](docs/bot-contract.md).

## Health check

`GET /health` returns status 200 and `{"status": "ok", "service": "grc-assurance-engine", "database": "reachable"}` when the process is running and the configured SQLite file can be opened read-only so its catalog can be read. If that read fails, the same route returns status 503 and `{"status": "unavailable", "service": "grc-assurance-engine", "database": "unreachable"}`. The body does not include the filesystem path, the SQL, or the driver message. The check does not validate schema completeness, integrity, or backups, and it does not show that the host is production-ready.

## Project notes

The health endpoint lives in `app/routes/health.py`, a file not listed in the original build plan. It is kept separate from the dashboard because it is an operational endpoint, not a page.

Runtime data belongs in the `instance/` folder, which Git ignores. The app initializes a local SQLite database for saved synthetic risks, remediation actions, human decisions, and workflow events. Scenario fixtures and saved data are synthetic; delete the ignored local database manually if you want to reset your demo records. A database created before the policy columns existed gains those columns on startup. Rows saved before the policy check have no policy reference, and a decision cannot be recorded on them until the scenario is saved again. A decisions table created before escalate existed is rebuilt on startup. The rows already stored are kept.

## Data and limitations

Every provided record is synthetic. The org policy, the intake questionnaire, and the risk rules are illustrative. The JSON API and CLI are a portfolio contract for that same illustrative model. A response does not approve a vendor. A human disposition is stored only when the caller confirms a save, and it is a separate field from the residual tier. A trust-center URL in the demo is not retrieved, and a pasted citation is not a live assurance feed. A ServiceNow import file is a simulated ticket export. The application does not connect to ServiceNow, and it does not open attachment bytes. A prohibited outcome is not a legal determination, and an exception rationale does not clear it. A contract-clause status is an evidence result, not a legal conclusion that the clause is in force. The dashboard shows two separate figures. Observed counts and elapsed cycle time come from saved risks and workflow events. The cost-of-assurance panel stays a modeled example from labeled assumptions. Elapsed cycle time is a clock span between events. Human handling time stays unmeasured, and neither figure is cash savings. A decision timestamp records when the decision was stored. The decision log is not tamper-proof, and the decider's name is not authenticated. Mapping a requirement to a control does not prove compliance, and no part of this project claims certification, production readiness, or proven risk reduction. The hosted demo is open with no login and uses synthetic data only; it is not production-ready. A confirmed import save and a persist request write to that shared register.

## Hosted demo

The hosted demo is live and open at https://grc-assurance.davidoneal.dev, with no login. Start at https://grc-assurance.davidoneal.dev/try/ to run a vendor review without changing anything. The Flask application runs on an AWS Lightsail Ubuntu instance provisioned by CloudFormation, with Nginx and Gunicorn serving it and SQLite storing synthetic saved risks on the instance. Cloudflare proxies the hostname and connects to the origin over HTTPS in Full (strict) mode. Daily Lightsail snapshots provide recovery points. See [docs/deployment.md](docs/deployment.md) for the current state, the setup procedure, and known gaps.

The host is a small portfolio demo, not a production service. Its Lightsail bundle is $7/month before snapshot storage or other charges. SQLite is suitable for this single-instance synthetic demo only. All data must remain synthetic. There is no login, so the risk register is shared by everyone with the link. The repository Nginx file limits `/try/` and `/api/` to 20 requests a minute per visitor and other pages to 120. The live host uses the file installed on the server.

## Walking through the demo

1. Open `/try/` and run the evidence-supported vendor. Point out that inherent risk, evidence confidence, residual risk, and the policy outcome are shown separately. CC-001 is verified from the reviewed contract excerpt. Run **Contract clause contradicted** and show that the same score stays in place while the clause status is conflicting.
2. Run the high-risk AI vendor. Show which escalation rules fired and why a low score could never skip that review.
3. Run the AI tool that decides eligibility, or submit a custom vendor with that question answered yes. The score is still calculated, and the policy outcome is prohibited under HR-001. Answering unknown is not treated as no, and it is not treated as prohibited.
4. Submit a custom vendor with contradicting evidence or an unknown answer, and show the result change to conflicting or undetermined instead of looking safe.
5. Show the workflow event log and the mock remediation ticket, and explain that nothing is sent anywhere. The public page does not save a decision. Download the reviewer package. A scenario fixture says no trust center was cited. A custom vendor with a fictional URL says the URL was not fetched.
6. On a custom vendor, leave AI use as none and show that model training is not asked. Set AI use to assistive and show that the training question appears. A trust-center URL alone, with every artifact left "not listed," does not verify a claim.
7. Open a scenario under Demo scenarios, add it to the risk register, and work its remediation action. Completing an action requires notes. On the eligibility risk, record a decision. Approval requires an exception rationale. The prohibited outcome stays visible. The saved risk can download the same package, including that decision. The dashboard's observed panel reads that same register. The modeled cost numbers stay on the illustrative assumptions when a row is saved.
8. From `/try/import`, preview the sample ServiceNow JSON. Point out that ticket priority is context and the residual tier appears only after confirm, from the risk engine. Confirm does not save the vendor. Saving requires the checkbox, a disposition, and a rationale. The register then shows the disposition beside the engine tier.

## Credit

The guided scenario runner, event log, and mock ticket presentation were inspired, with permission, by irvinthev's [GRC Cost of Assurance Dashboard](https://irvinthev.github.io/grc-cost-of-assurance-dashboard/). The code, rules, and data in this repository are separate and original.

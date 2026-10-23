# GRC Assurance Engine

A small Flask application for evidence-first vendor and AI-tool risk assessments. It is a portfolio project that uses synthetic data only. It is not a production system, and it has no live ServiceNow integration.

## Current status

The local Flask application has an app factory, a health-check endpoint, a responsive demo interface, and pytest coverage.

The risk engine in `app/services/risk_engine.py` evaluates assessments against the versioned illustrative rules in `app/data/risk_rules.json` and the single org policy in `app/data/org_policy.json`. It is a draft portfolio model, not a calibrated methodology, and the policy profile is illustrative rather than an approved corporate policy.

Intake asks whether the AI makes fully automated decisions about people's eligibility, safety, or similar outcomes with no human review. A yes answer produces a prohibited outcome that cites restriction HR-001 and policy `ORG-AI-USE` version 1.1.0. That outcome is separate from the score. The required contract clause in the starter profile, no vendor model training on company or customer data, is checked against vendor evidence. Verified, self-attested, missing, conflicting, expired, and not reviewed use the same evidence vocabulary as a claim. A gap is shown to the reviewer and does not block the decision. Another restriction or clause is added by extending those lists. On a saved risk, a person records approve, approve with conditions, or reject. Approving a prohibited result requires an exception rationale, and the prohibited flag stays on the assessment. The engine does not make that decision.

Phase 3 is implemented as framework-independent services. The evidence validator in `app/services/evidence_validator.py` derives claim evidence status using configurable freshness limits in `app/data/evidence_policy.json`. The control mapper in `app/services/control_mapper.py` joins explicitly tagged claims to a small NIST SP 800-53 mapping library in `app/data/control_mappings.json`; the mappings are draft pending human review. See `docs/evidence-model.md` and `docs/control-mapping-methodology.md`.

The local web interface includes repeatable synthetic scenarios that run the same risk, evidence, policy, and mapping services and show explanations and trace links. One scenario is an eligibility tool whose score stays moderate while the policy outcome is prohibited. A scenario can be added to the local SQLite risk register with a follow-up action, a human decision, and workflow history. The dashboard includes a reproducible modeled labor-capacity example; it is not a measured saving. See `docs/BUILD_PLAN.md` for features that remain out of scope.

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
3. For the high-risk, conflicting, or prohibited case, choose **Add to risk register**, assign an action owner/due date, and update its status. On the prohibited case, record a decision. Approval requires an exception rationale. Rejection does not. The prohibited outcome remains. The risk record, decision, and local workflow events stay in the ignored SQLite database under `instance/`.
4. Open **Contract clause contradicted** and compare it with the evidence-supported vendor. CC-001 is conflicting in one case and verified in the other. The score does not move because of that status.
5. Open **Methods** to review the rule set, the org policy, how required contract clauses are checked, mapping limitations, and the modeled cost formula.

The local demo does not require credentials, network services, or private evidence. The hosted demo is open with no login. The application still has an optional HTTP Basic gate, and it stays off unless `REQUIRE_AUTH` is set to true. The hosted site does not set that variable. See [docs/deployment.md](docs/deployment.md).

## Run the tests

```bash
python -m pytest
```

GitHub Actions runs this suite on Python 3.12 and 3.14 for every push and pull request.

## Health check

`GET /health` returns status 200 and `{"status": "ok", "service": "grc-assurance-engine"}` when the application is running. It does not check the database or any other dependency yet.

## Project notes

The health endpoint lives in `app/routes/health.py`, a file not listed in the original build plan. It is kept separate from the dashboard because it is an operational endpoint, not a page.

Runtime data belongs in the `instance/` folder, which Git ignores. The app initializes a local SQLite database for saved synthetic risks, remediation actions, human decisions, and workflow events. Scenario fixtures and saved data are synthetic; delete the ignored local database manually if you want to reset your demo records. A database created before the policy columns existed gains those columns on startup. Rows saved before the policy check have no policy reference, and a decision cannot be recorded on them until the scenario is saved again.

## Data and limitations

Every provided record is synthetic. The org policy and the risk rules are illustrative. A prohibited outcome is not a legal determination, and an exception rationale does not clear it. A contract-clause status is an evidence result, not a legal conclusion that the clause is in force. The cost-of-assurance panel is modeled from labeled assumptions and does not report observed performance or actual cash savings. Workflow timestamps, including a decision timestamp, are not handling-time measurements. The decision log is not tamper-proof, and the decider's name is not authenticated. Mapping a requirement to a control does not prove compliance, and no part of this project claims certification, production readiness, or proven risk reduction. The hosted demo is open with no login and uses synthetic data only; it is not production-ready.

## Hosted demo

The hosted demo is live and open at https://grc-assurance.davidoneal.dev, with no login. Start at https://grc-assurance.davidoneal.dev/try/ to run a vendor review without changing anything. The Flask application runs on an AWS Lightsail Ubuntu instance provisioned by CloudFormation, with Nginx and Gunicorn serving it and SQLite storing synthetic saved risks on the instance. Cloudflare proxies the hostname and connects to the origin over HTTPS in Full (strict) mode. Daily Lightsail snapshots provide recovery points. See [docs/deployment.md](docs/deployment.md) for the current state, the setup procedure, and known gaps.

The host is a small portfolio demo, not a production service. Its Lightsail bundle is $7/month before snapshot storage or other charges. SQLite is suitable for this single-instance synthetic demo only. All data must remain synthetic. There is no login, so the risk register is shared by everyone with the link, and Nginx rate limits every page.

## Walking through the demo

1. Open `/try/` and run the evidence-supported vendor. Point out that inherent risk, evidence confidence, residual risk, and the policy outcome are shown separately. CC-001 is verified from the reviewed contract excerpt. Run **Contract clause contradicted** and show that the same score stays in place while the clause status is conflicting.
2. Run the high-risk AI vendor. Show which escalation rules fired and why a low score could never skip that review.
3. Run the AI tool that decides eligibility, or submit a custom vendor with that question answered yes. The score is still calculated, and the policy outcome is prohibited under HR-001. Answering unknown is not treated as no, and it is not treated as prohibited.
4. Submit a custom vendor with contradicting evidence or an unknown answer, and show the result change to conflicting or undetermined instead of looking safe.
5. Show the workflow event log and the mock remediation ticket, and explain that nothing is sent anywhere. The public page does not save a decision.
6. Open a scenario under Demo scenarios, add it to the risk register, and work its remediation action. Completing an action requires notes. On the eligibility risk, record a decision. Approval requires an exception rationale. The prohibited outcome stays visible.

## Credit

The guided scenario runner, event log, and mock ticket presentation were inspired, with permission, by irvinthev's [GRC Cost of Assurance Dashboard](https://irvinthev.github.io/grc-cost-of-assurance-dashboard/). The code, rules, and data in this repository are separate and original.

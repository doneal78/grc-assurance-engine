# GRC Assurance Engine

A small Flask application for evidence-first vendor and AI-tool risk assessments. It is a portfolio project that uses synthetic data only. It is not a production system, and it has no live ServiceNow integration.

## Current status

The local Flask application has an app factory, a health-check endpoint, a responsive demo interface, and pytest coverage.

The risk engine in `app/services/risk_engine.py` evaluates assessments against the versioned illustrative rules in `app/data/risk_rules.json`, and is used by the scenario walkthrough. It is a draft portfolio model, not a calibrated methodology.

Phase 3 is implemented as framework-independent services. The evidence validator in `app/services/evidence_validator.py` derives claim evidence status using configurable freshness limits in `app/data/evidence_policy.json`. The control mapper in `app/services/control_mapper.py` joins explicitly tagged claims to a small NIST SP 800-53 mapping library in `app/data/control_mappings.json`; the mappings are draft pending human review. See `docs/evidence-model.md` and `docs/control-mapping-methodology.md`.

The local web interface includes three repeatable synthetic scenarios that run the same risk, evidence, and mapping services and show explanations and trace links. A scenario can be added to the local SQLite risk register with a follow-up action and workflow history. The dashboard includes a reproducible modeled labor-capacity example; it is not a measured saving. See `docs/BUILD_PLAN.md` for features that remain out of scope.

## Requirements

Windows with Git Bash, Python 3.14, and Git.

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

1. Open **Demo scenarios** and choose one of the three synthetic cases.
2. Review the inherent score/tier, confidence, residual result, explanation, evidence statuses, escalations, and draft control prompts.
3. For the high-risk or conflicting case, choose **Add to risk register**, assign an action owner/due date, and update its status. The risk record and local workflow events stay in the ignored SQLite database under `instance/`.
4. Open **Methods** to review rule versions, mapping limitations, and the modeled cost formula.

The local demo does not require credentials, network services, or private evidence. The hosted demo requires HTTP Basic credentials before any application page is served.

## Run the tests

```bash
python -m pytest
```

## Health check

`GET /health` returns status 200 and `{"status": "ok", "service": "grc-assurance-engine"}` when the application is running. It does not check the database or any other dependency yet.

## Project notes

The health endpoint lives in `app/routes/health.py`, a file not listed in the original build plan. It is kept separate from the dashboard because it is an operational endpoint, not a page.

Runtime data belongs in the `instance/` folder, which Git ignores. The app initializes a local SQLite database for saved synthetic risks, remediation actions, and workflow events. Scenario fixtures and saved data are synthetic; delete the ignored local database manually if you want to reset your demo records.

## Data and limitations

Every provided record is synthetic. The cost-of-assurance panel is modeled from labeled assumptions and does not report observed performance or actual cash savings. Workflow timestamps are not handling-time measurements. Mapping a requirement to a control does not prove compliance, and no part of this project claims certification, production readiness, or proven risk reduction. The hosted demo has an optional shared-password gate; this does not make it production-ready.

## Hosted demo

The hosted demo runs the Flask application on an AWS Lightsail Ubuntu instance provisioned by CloudFormation. Nginx and Gunicorn serve the responsive interface, SQLite stores synthetic saved risks on the instance, daily Lightsail snapshots provide a recovery point, and Cloudflare manages the custom-domain DNS and proxy. The instance starts in a closed setup state; the demo password gate must be configured before Nginx proxies requests to Flask. See [docs/deployment.md](docs/deployment.md) for the deployment and operating procedure.

The AWS host is a small portfolio demo, not a production service. Its current Lightsail bundle is $7/month before snapshot storage or other account charges. SQLite is suitable for this single-instance synthetic demo only. All data must remain synthetic; the password gate is shared HTTP Basic authentication, not user management or MFA.

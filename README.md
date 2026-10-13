# GRC Assurance Engine

A small Flask application for evidence-first vendor and AI-tool risk assessments. It is a portfolio project that uses synthetic data only. It is not a production system, and it has no live ServiceNow integration.

## Current status

Phase 1, the application foundation, is in progress. What exists today is an application factory, a health-check endpoint, a dashboard page that shows an honest empty state, minimal styling, and a pytest suite.

Intake, evidence review, requirement mapping, risk rules, remediation, and metrics are planned in `docs/BUILD_PLAN.md`. None of them are built yet.

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

## Run the tests

```bash
python -m pytest
```

## Health check

`GET /health` returns status 200 and `{"status": "ok", "service": "grc-assurance-engine"}` when the application is running. It does not check the database or any other dependency yet.

## Project notes

The health endpoint lives in `app/routes/health.py`, a file not listed in the original build plan. It is kept separate from the dashboard because it is an operational endpoint, not a page.

Runtime data belongs in the `instance/` folder, which Git ignores. No database is created yet. The configured database path is a placeholder for Phase 2.

## Data and limitations

Every record in this project is synthetic. The dashboard only shows figures calculated from imported records, and it shows an empty state when there are none. Mapping a requirement to a control does not prove compliance, and no part of this project claims certification or production readiness.

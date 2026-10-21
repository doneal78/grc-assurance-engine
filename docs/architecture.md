# Architecture

## Current application

The application uses the Flask factory in `app/__init__.py` to register web blueprints. Routes render templates and pass them the results of plain-Python service functions. The business logic does not depend on Flask, a database, a browser, or live third-party services.

| Responsibility | Current location | Notes |
| --- | --- | --- |
| HTTP routes | `app/routes/` | Health, dashboard, and synthetic scenario pages. |
| Business logic | `app/services/` | Risk evaluation, evidence validation, control mapping, scenario orchestration, local workflow persistence, and cost calculations. |
| Database | `app/db.py`, `app/schema.sql` | SQLite schema and request-scoped connections for risks, remediation actions, and workflow events. `DATABASE_PATH` can place the file on a persistent host volume. |
| Versioned rules/data | `app/data/` | Risk rules, evidence freshness policy, mappings, and fixed-date demo scenarios. |
| Presentation | `app/templates/`, `app/static/` | Server-rendered HTML and responsive CSS. |
| Automated checks | `tests/` | pytest tests include service-level business logic and Flask route behavior. |
| Documentation | `docs/` | Design, assumptions, and limitations. |

The scenario runner composes evidence validation, risk evaluation, and mapping in that order. It passes the derived claim evidence results into the risk engine and mapping service. A missing or conflicting status is never replaced by a UI-generated conclusion. Scenario data is loaded from version-controlled JSON and evaluated on an explicit fixed date. A user can save a synthetic scenario result to SQLite; the persistence service stores the risk rationale and references, creates a follow-up action for escalations or evidence gaps, and records local workflow events using parameterized SQL.

## Current limitations

Scenario runs are deterministic examples, not vendor records. There is no real assessment intake, general-purpose finding management, metrics, or external integration. The optional HTTP Basic gate can require a shared password when `REQUIRE_AUTH` is enabled. The hosted demo leaves it off. It is not an identity system or production access-control design. The workflow log can be modified by someone with access to the database and is not tamper-proof. The local Flask development server must not be exposed publicly.

## Design choices

- Standard-library JSON and SQLite are preferred for the prototype to keep dependencies small.
- Flask remains at the route and presentation boundary; core functions can be tested directly.
- Static JSON makes every demonstration input inspectable and repeatable.
- Mapping results retain source, version, claim, and evidence references while remaining visibly draft.
- No external AI service participates in scoring or approval decisions.

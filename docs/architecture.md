# Architecture

## Current application

The application uses the Flask factory in `app/__init__.py` to register web blueprints. Routes render templates and pass them the results of plain-Python service functions. The business logic does not depend on Flask, a database, a browser, or live third-party services.

| Responsibility | Current location | Notes |
| --- | --- | --- |
| HTTP routes | `app/routes/` | Health, dashboard, and synthetic scenario pages. |
| Business logic | `app/services/` | Risk evaluation, the single org-policy check, evidence validation, control mapping, scenario orchestration, local workflow persistence, human decisions, cost calculations, the reviewer package, and file import. |
| Database | `app/db.py`, `app/schema.sql` | SQLite schema and request-scoped connections for risks, remediation actions, human decisions, and workflow events. `DATABASE_PATH` can place the file on a persistent host volume. Startup adds policy columns to a risk table created before those columns existed. |
| Versioned rules/data | `app/data/` | Risk rules, the single org policy profile, the public intake questionnaire, evidence freshness policy, mappings, and fixed-date demo scenarios. |
| Presentation | `app/templates/`, `app/static/` | Server-rendered HTML and responsive CSS. |
| Automated checks | `tests/` | pytest tests include service-level business logic and Flask route behavior. |
| Documentation | `docs/` | Design, assumptions, and limitations. |

`app/services/intake_importer.py` turns a CSV, `.xlsx`, or simulated ServiceNow JSON/CSV file into the same form dictionary the public intake page posts. `openpyxl` reads workbooks. CSV and JSON stay in the standard library. The preview does not call the risk engine. After confirmation, `build_intake` and `run_intake` do. The route does not insert a risk row. Ticket fields such as priority are returned as context and are not scored. See `docs/import-formats.md`.

The scenario runner composes evidence validation, risk evaluation, and mapping in that order. It passes the derived claim evidence results into the risk engine and mapping service. The same validation call checks required contract clauses and passes those statuses through. A missing or conflicting status is never replaced by a UI-generated conclusion. Scenario data is loaded from version-controlled JSON and evaluated on an explicit fixed date. Risk evaluation also reads `app/data/org_policy.json` and attaches that policy's id, version, outcome, and the evidence status of each required contract clause. A user can save a synthetic scenario result to SQLite; the persistence service stores the risk rationale and references, creates a follow-up action for escalations, a matched hard restriction, or evidence gaps, and records local workflow events using parameterized SQL.

A saved risk can then store one human decision: approve, approve with conditions, or reject. The workflow service copies the policy reference and rule set version from the saved assessment, requires an exception rationale before an approval of a prohibited result, and writes a `decision_recorded` event. Replacing a decision updates that row and writes another event. The prohibited outcome on the assessment is not edited. See `docs/risk-model.md` for why an exception is allowed.

## Current limitations

Scenario runs are deterministic examples, not vendor records. File import on `/try/import` is a preview of synthetic rows. It is not saved intake, and the ServiceNow shape is not a live integration. There is no general-purpose finding management or observed metrics. The optional HTTP Basic gate can require a shared password when `REQUIRE_AUTH` is enabled. The hosted demo leaves it off. It is not an identity system or production access-control design. The workflow log can be modified by someone with access to the database and is not tamper-proof. The local Flask development server must not be exposed publicly.

## Design choices

- Standard-library JSON, CSV, and SQLite are preferred for the prototype. `openpyxl` is the one added library, and it only reads `.xlsx` workbooks.
- Flask remains at the route and presentation boundary; core functions can be tested directly.
- Static JSON makes every demonstration input inspectable and repeatable.
- Mapping results retain source, version, claim, and evidence references while remaining visibly draft.
- No external AI service participates in scoring or approval decisions.
- One org policy file is enough. There is no tenant selector.
- The policy outcome is calculated in the risk engine. Templates display it. They do not decide it.
- Required contract clauses are data in the org policy. The evidence validator derives each clause status. The risk engine records that status and does not score it. A gap does not block the human decision.
- A prohibited result can be approved only with an exception rationale because a person, not the score, makes the disposition. The restriction stays on the record. There is no configured non-overridable ban.
- The decider is a name or role typed into the form. Nothing checks it against a directory or against the restriction's owner role.
- The public intake questionnaire is versioned data. It chooses prompts and which trust-center citation becomes an evidence record. The risk engine still scores. A trust-center URL is stored and not fetched. The reviewer package is JSON and plain text built from the assessment result. It does not approve the vendor.
- File import reuses that questionnaire. A spreadsheet column and a ServiceNow `u_` field are two ways to fill in the same form. The importer does not keep a second scoring model.

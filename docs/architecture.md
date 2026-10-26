# Architecture

## Current application

The application uses the Flask factory in `app/__init__.py` to register web blueprints. Routes render templates and pass them the results of plain-Python service functions. The business logic does not depend on Flask, a database, a browser, or live third-party services.

| Responsibility | Current location | Notes |
| --- | --- | --- |
| HTTP routes | `app/routes/` | Health, dashboard, synthetic scenario pages, the control-mapping library at `/mappings`, and the JSON intake API under `/api/v1`. |
| Business logic | `app/services/` | Risk evaluation, the single org-policy check, evidence validation, control mapping, scenario orchestration, local workflow persistence, human decisions, observed workflow metrics, cost calculations, the reviewer package, file import, the optional trust-center GET, and the bot intake contract. |
| Database | `app/db.py`, `app/schema.sql` | SQLite schema and request-scoped connections for risks, remediation actions, human decisions, and workflow events. `DATABASE_PATH` can place the file on a persistent host volume. Startup adds policy columns to a risk table created before those columns existed. `GET /health` opens that file read-only and reports whether its catalog can be read. |
| Versioned rules/data | `app/data/` | Risk rules, the single org policy profile, the public intake questionnaire, evidence freshness policy, mappings, and fixed-date demo scenarios. |
| Presentation | `app/templates/`, `app/static/` | Server-rendered HTML and responsive CSS. |
| Automated checks | `tests/` | pytest tests include service-level business logic and Flask route behavior. |
| Documentation | `docs/` | Design, assumptions, and limitations. |

`app/services/intake_importer.py` turns a CSV, `.xlsx`, or simulated ServiceNow JSON/CSV file into the same form dictionary the public intake page posts. `openpyxl` reads workbooks. CSV and JSON stay in the standard library. The preview does not call the risk engine. After confirmation, `build_intake` and `run_intake` do. Confirm does not insert a risk row. A separate save posts the same confirmation for one row and calls `register_intake`. Ticket fields such as priority are returned as context and are not scored. See `docs/import-formats.md`.

`app/services/bot_intake.py` accepts that same form as a JSON object, or a file the importer already parses. `app/cli.py` (`python -m app.cli`) and `app/routes/api.py` return the document it builds from `run_intake`. The residual tier, factor list, escalation records, and rule-set version are copied from the risk engine. Those callers insert a risk row only when persist is requested and the human disposition passes the same checks as a decision on a saved scenario. See `docs/bot-contract.md`.

A requested trust-center fetch performs one outbound HTTP GET. File import does not fetch. Tests stub the opener and the resolver. The address check refuses private and metadata targets. It does not pin DNS against a later address change.

The scenario runner composes evidence validation, risk evaluation, and mapping in that order. It passes the derived claim evidence results into the risk engine and mapping service. The same validation call checks required contract clauses and passes those statuses through. A missing or conflicting status is never replaced by a UI-generated conclusion. Scenario data is loaded from version-controlled JSON and evaluated on an explicit fixed date. Risk evaluation also reads `app/data/org_policy.json` and attaches that policy's id, version, outcome, and the evidence status of each required contract clause. A user can save a synthetic scenario result to SQLite; the persistence service stores the risk rationale and references, creates a follow-up action for escalations, a matched hard restriction, or evidence gaps, and records local workflow events using parameterized SQL.

A saved risk can then store one human decision: approve, approve with conditions, escalate, or reject. The workflow service copies the policy reference and rule set version from the saved assessment, requires an exception rationale before an approval of a prohibited result, and writes a `decision_recorded` event. Escalate is a person's choice to send the case on. It is not an approval and it does not require an exception rationale. Replacing a decision updates that row and writes another event. The prohibited outcome on the assessment is not edited. See `docs/risk-model.md` for why an exception is allowed. General intake uses the same insert, then writes the decision in that same transaction. The intake's scenario id is `intake-` plus a random suffix so the scenario unique key still holds. That save writes `intake_received` before `risk_created`, then `decision_recorded`. A scenario save writes `risk_created` and does not write `intake_received`.

`app/services/workflow_metrics.py` reads those rows. It counts assessments, open remediation, residual tiers, claim evidence, clause evidence, and current dispositions. Cycle time is the elapsed seconds from the earliest `intake_received` timestamp to the earliest `decision_recorded` timestamp on the same risk. The function does not write, and it does not call the cost model. The dashboard and the methods page pass `calculate_cost()` and `observed_metrics()` to the templates as two separate values. See `docs/cost-model.md`.

## Current limitations

Scenario runs are deterministic examples, not vendor records. File import on `/try/import` previews synthetic rows and assesses them on confirm. The ServiceNow shape is not a live integration. A row is stored only after a separate save. The bot contract returns one assessment or a file batch. It stores them only when persist is true and a person supplies a disposition. There is no general-purpose finding management. Observed metrics cover the saved register only: volume, open remediation, distributions, disposition counts, and elapsed intake-to-disposition time. Human handling time is still unmeasured. The cost panel remains the illustrative formula. The optional HTTP Basic gate can require a shared password when `REQUIRE_AUTH` is enabled. The hosted demo leaves it off, so a persist call and an import save write to the shared register. It is not an identity system or production access-control design. The workflow log can be modified by someone with access to the database and is not tamper-proof. The local Flask development server must not be exposed publicly. A trust-center fetch collects a public page for review. It is not independent verification, and the address check is not a complete SSRF sandbox.

## Design choices

- Standard-library JSON, CSV, and SQLite are preferred for the prototype. `openpyxl` is the one added library, and it only reads `.xlsx` workbooks.
- Flask remains at the route and presentation boundary; core functions can be tested directly.
- Static JSON makes every demonstration input inspectable and repeatable.
- Mapping results retain source, version, claim, and evidence references while remaining visibly draft. `/mappings` lists the whole library from `list_library`. ISO/IEC 27001 and ISO/IEC 42001 are not in that library.
- No external AI service participates in scoring or approval decisions.
- One org policy file is enough. There is no tenant selector.
- The policy outcome is calculated in the risk engine. Templates display it. They do not decide it.
- `GET /health` reports SQLite reachability. The check is a read-only open and a catalog read. It does not rate the data, the schema, or the host.
- Required contract clauses are data in the org policy. The evidence validator derives each clause status. The risk engine records that status and does not score it. A gap does not block the human decision.
- A prohibited result can be approved only with an exception rationale because a person, not the score, makes the disposition. The restriction stays on the record. There is no configured non-overridable ban.
- The decider is a name or role typed into the form. Nothing checks it against a directory or against the restriction's owner role.
- The public intake questionnaire is versioned data. It chooses prompts and which trust-center citation becomes an evidence record. The risk engine still scores. A trust-center URL is stored as a citation unless the form sets `fetch_trust_center` to yes. That choice performs one HTTP GET in `app/services/trust_center_fetch.py` and stores an excerpt for review. The evidence validator marks the fetch `not_reviewed`. It is not a scored claim and it does not approve the vendor. File import does not fetch. The reviewer package is JSON and plain text built from the assessment result. It does not approve the vendor.
- File import reuses that questionnaire. A spreadsheet column and a ServiceNow `u_` field are two ways to fill in the same form. The importer does not keep a second scoring model.
- The bot contract is a third way to submit that form. `app/cli.py` and `/api/v1/intake/assess` call `build_intake` and `run_intake`. They do not keep a second scoring model, and they do not approve the vendor.
- Observed metrics are counted from persisted rows and event timestamps. The cost service keeps its own assumption file. The pages render both results and do not copy one into the other.

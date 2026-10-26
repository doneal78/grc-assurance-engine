# Bot intake contract

A script or agent can run the same vendor intake as the public form and receive the risk engine's result as JSON. The calculation lives in `app/services/bot_intake.py`. It calls `build_intake` and `run_intake`. The CLI and the HTTP route copy that result. They do not calculate a tier. They write a risk only when the caller sets persist and supplies a human disposition.

This is a portfolio demo. It is not a production GRC API, an identity system, or a certification. The rule set is an illustrative portfolio model. `automatic_approval` is always null. A low residual tier does not approve the vendor. Human review remains required, and a configured restriction such as HR-001 still requires a person. The disposition, when one is saved, is a separate object from the residual tier.

No external AI model scores or approves the vendor.

## Commands

```bash
python -m app.cli assess request.json
python -m app.cli assess - < request.json
python -m app.cli preview tests/fixtures/imports/vendor_intake.csv --as-of 2026-10-14
python -m app.cli assess-file tests/fixtures/imports/servicenow_intake.json --as-of 2026-10-14
python -m app.cli assess request.json --persist --disposition escalate --rationale "Low tier is not an approval." --decider "GRC analyst"
```

`assess` reads one JSON request from a file or from stdin. A terminal with nothing piped to `assess` exits 2 and asks for a file or a pipe. `preview` and `assess-file` read a questionnaire CSV, a `.xlsx` workbook, or a simulated ServiceNow JSON or CSV file. Those parsers are the ones documented in [import-formats.md](import-formats.md). `preview` does not call the risk engine. `assess-file` calls it only when every row is valid. A file with any invalid or conflicting row produces a preview and no assessment.

`--persist` on `assess` or `assess-file` saves the result. It requires `--disposition`, `--rationale`, and `--decider`. Optional `--conditions` and `--exception-rationale` follow the saved-risk rules. If the JSON body already contains `persist` or `decision`, the flags are rejected and nothing is saved. Use one or the other. `assess-file --persist` stores every row with that same disposition. If one row cannot accept it, none are stored. `preview` cannot persist.

`--as-of` sets the evaluation date for a file. The JSON request carries its own `as_of`. When the date is omitted, the process date is used. Evidence ages are calculated from that date, the same way the public form uses the server date.

Exit codes:

| Code | Meaning |
| --- | --- |
| 0 | An assessment was produced, or a file preview can be assessed |
| 2 | The request or file failed validation. stdout is a JSON error, or a preview with `can_assess` false |
| 1 | The engine raised an unexpected error. stdout is a JSON error with `"error": "engine"` |

Usage help from a missing command also exits 2. Help text goes to stderr. Result documents go to stdout.

## HTTP

| Method | Path | Body |
| --- | --- | --- |
| GET | `/api/v1/intake/contract` | Live field list, versions, and limitations |
| POST | `/api/v1/intake/assess` | The JSON request below, `Content-Type: application/json` |

There is no HTTP upload for CSV or `.xlsx`. Use the CLI for files. The JSON body uses the same 16 KB cap as an ordinary form post.

`REQUIRE_AUTH` defaults to false, which is also the hosted demo setting, so these routes answer without a password. When `REQUIRE_AUTH` is true they use the same HTTP Basic credentials as the rest of the application. The public `/try/` pages stay open in that mode. This API does not.

A browser request whose `Origin` or `Referer` host does not match the site is rejected with 403, including a persist request. A script that sends neither header is accepted. That script can save a synthetic risk when persist is true. A same-origin `Origin` is accepted.

| Status | When |
| --- | --- |
| 200 | Assessment document |
| 400 | Validation problem. Body is `grc.intake.error` |
| 401 | `REQUIRE_AUTH` is true and the credentials are missing or wrong |
| 403 | Cross-site browser request |
| 413 | Body larger than the form cap |
| 415 | Body is not `application/json` |
| 500 | Unexpected engine error. Body is `grc.intake.error` with `"error": "engine"` |

On the hosted demo, Nginx's general site limit applies to `/api/` (120 requests a minute per visitor in `infra/nginx-site.conf`). `/try/` has a tighter limit. This repository does not add a separate API limit. The live host uses the nginx file installed there.

`GET /api/v1/intake/contract` is generated from the questionnaire, the rule set, and the org policy. Use it when a field list in this page and the running app might differ.

## Assess request

```json
{
  "contract_version": "1.0.0",
  "as_of": "2026-10-14",
  "form": {
    "vendor_name": "Northwind Notes",
    "data_sensitivity": "internal",
    "integration_permissions": "read_only",
    "ai_use": "none",
    "external_exposure": "internal_only",
    "retention_deletion": "documented",
    "decisions_affecting_people": "no",
    "evidence_integration_permissions": "independent_verified",
    "trust_center_url": "",
    "trust_soc2": "independent_verified",
    "trust_security": "independent_verified",
    "trust_privacy": "independent_verified",
    "evidence_clause_CC-001": "independent_verified"
  }
}
```

`contract_version` may be omitted. When it is present it must be `1.0.0`. Unknown request fields and unknown form fields are rejected and are not dropped. A reviewer package (`kind` of `vendor_intake_package`) or a simulated ServiceNow file is rejected here. Pass the file to `preview` or `assess-file`.

Form keys are the public intake fields. Values are text. Numbers and booleans are rejected rather than turned into text, matching the file importer. Allowed values are the rule set and the org policy. `model_training_on_customer_data` may be omitted when `ai_use` is `none`, because the public form does not submit that disabled field. Any other omitted field is a validation error. An empty `vendor_name` is a validation error.

`trust_center_url` may be an empty string. The URL is not fetched.

Sending `residual_tier` or any other extra field fails validation. The response tier comes from the risk engine after a valid form is accepted.

`persist` may be omitted. Omitted and false both assess only. The value must be a JSON boolean. A decision object sent while persist is omitted or false is a validation error, and nothing is saved, so a caller cannot think a disposition was recorded.

When `persist` is true, `decision` is required:

| Field | Required | Rule |
| --- | --- | --- |
| `disposition` | yes | `approve`, `approve_with_conditions`, `escalate`, or `reject` |
| `rationale` | yes | 1 to 1000 characters after trimming |
| `decider` | yes | 1 to 100 characters after trimming. A name or role. It is not authenticated |
| `conditions` | only for approve with conditions | Empty for every other disposition |
| `exception_rationale` | only to approve a prohibited result | Refused on escalate, reject, or a result that is not prohibited |

An invalid disposition is rejected before a risk row is written. Approving a prohibited result without an exception rationale is also rejected, and the register is unchanged. Escalate means a person is sending the case on. It is not an approval, including when the residual tier is low.

## Assessment document

`contract` is `grc.intake.assessment`. These fields are copied from the `run_intake` result:

| Field | Source |
| --- | --- |
| `rule_set_version` | `risk.rule_set_version` |
| `residual.tier` and `residual.reason` | `risk.residual` |
| `inherent` | `risk.inherent`, including the score, tier, provisional flag, and factor list |
| `evidence_confidence` | `risk.evidence_confidence` |
| `escalations` | `risk.escalations`, including each rule id, reason, assessment, owner role, required output, and next step |
| `missing_information` | `risk.missing_information` |
| `conflicts` | claim id, topic, and evidence status from `risk.conflicts` |
| `review_path` | `risk.review_path` |
| `policy_outcome` | `risk.policy_outcome`, including HR-001 when it matches |
| `required_contract_clauses` | clause id, title, text, evidence status, and status reason |
| `claims` | claim id, topic, statement, evidence status, status reason, and evidence-record status |
| `mappings` | mapper id, framework, control, rationale, and `review_status` |

`persisted` is false unless this request saved the vendor. `risk_id` and `decision` are null when nothing was saved. When a save succeeds, `risk_id` is the register id and `decision` copies the stored disposition, rationale, decider, policy reference, rule set version, and `prohibited_at_decision`. `decision.separate_from_score` is true. The residual tier is not copied into the disposition. `human_review_required` is true. `automatic_approval` is null. `synthetic_data` is taken from the intake result. `trust_center.fetched` is copied from that result and is false for this intake path.

The explanations are the engine's own text: `residual.reason`, each inherent factor, each escalation's `reason`, each claim and clause `status_reason`, and each matched restriction. The route does not write a second narrative or a second score.

A file assessment is `grc.intake.assessment_batch`. Each item is an assessment document plus `source_row`, `ticket_number`, and `import_format` when the importer supplied them. Ticket `priority`, `state`, and `opened_at` stay on the preview as context. They do not set the residual tier or `as_of`.

For the request above, rule set `0.3.0` on `2026-10-14` returns residual tier `low`, reason `Already at the lowest tier.`, inherent score `20`, no escalations, policy outcome `not_prohibited`, and CC-001 evidence status `verified`. That output is the current illustrative model. It is not an approval.

A yes answer on `decisions_affecting_people` returns policy outcome `prohibited`, restriction `HR-001`, and review path `escalated_review`. The inherent score and residual tier stay the values the engine calculated for the other answers. An `unknown` answer fires ESC-009, leaves the policy outcome `not_prohibited`, and makes the residual tier `undetermined`. Unknown is not treated as no.

## Validation document

```json
{
  "contract": "grc.intake.error",
  "contract_version": "1.0.0",
  "error": "validation",
  "persisted": false,
  "assessed": false,
  "problems": ["Missing form fields: vendor_name."]
}
```

`problems` lists what failed. A preview that cannot be assessed uses `grc.intake.import_preview` with `scored` false and `can_assess` false instead of this error, so the row messages are still available. An engine failure uses the same error document with `"error": "engine"` and a one-line problem. The CLI does not print a traceback on stdout.

## Limits

- One vendor per `assess` request. A file may contain up to 20 vendor rows, which is the importer's limit.
- JSON assess bodies over 16 KB are rejected. Import files over 256 KB are rejected by the importer.
- Duplicate JSON keys are rejected. The repeated value is not kept.
- A human decision is recorded only with persist true. Approve, approve with conditions, escalate, and reject are that disposition. The web form on a saved risk uses the same four. Assess without persist does not save one.
- `assess-file --persist` uses one disposition for the whole file. It does not ask for a different decision per row. The import result page does, one vendor at a time.
- The saved row is synthetic demonstration data in the local SQLite register. Saving the same request again adds another row. The decider text is not checked against a directory.
- Draft control mappings are review prompts. A mapping does not show that a control is implemented or that a framework is met.
- The local event log and the mock remediation ticket on the web page are separate views of an assessment. They are not part of this JSON document.
- The CLI and the API do not call ServiceNow and do not open attachment bytes or trust-center pages.

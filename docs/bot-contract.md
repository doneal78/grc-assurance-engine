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

`infra/nginx-site.conf` limits `/api/` to 20 requests a minute per visitor and 5 requests a second across visitors. That is the same per-visitor budget as `/try/`. Other pages stay at 120 requests a minute per visitor. The live host uses the Nginx file installed there. Copying this repository file and reloading Nginx is a separate manual step, so the running demo keeps its previous limit until that happens.

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
    "evidence_clause_CC-001": "independent_verified",
    "vendor_direction": "stable",
    "residual_direction": "unchanged",
    "direction_note": "Synthetic context: same scope as the last review. Not a score."
  }
}
```

`contract_version` may be omitted. When it is present it must be `1.0.0`. Unknown request fields and unknown form fields are rejected and are not dropped. A reviewer package (`kind` of `vendor_intake_package`) or a simulated ServiceNow file is rejected here. Pass the file to `preview` or `assess-file`.

Form keys are the public intake fields. Values are text. Numbers and booleans are rejected rather than turned into text, matching the file importer. Allowed values are the rule set and the org policy. `model_training_on_customer_data` may be omitted when `ai_use` is `none`, because the public form does not submit that disabled field. `fetch_trust_center` may be omitted, and that means do not fetch. Any other omitted field is a validation error. An empty `vendor_name` is a validation error.

`trust_center_url` may be an empty string. `fetch_trust_center` is optional. Omitted and `no` store the URL and do not fetch it. `yes` performs one HTTP GET of that URL. The response is vendor-published material for human review. The evidence status on a successful fetch is `not_reviewed`. It is not a scored claim, it is not `verified`, and it does not approve the vendor. An HTTP error or a timeout is `fetch.outcome` `failed` and evidence status `missing`. A private, link-local, or metadata target is rejected and nothing is fetched. File import does not include this field and does not fetch.

`vendor_direction`, `residual_direction`, and `direction_note` are optional. Omitted and blank both mean not provided. They are context for a person. They are not scored. They do not change inherent risk, residual risk, evidence confidence, escalations, the policy outcome, dispositions, or control mappings. Allowed direction values are on `GET /api/v1/intake/contract` under `direction_context`. `unknown` means the requester does not know the direction. It is not a missing scoring answer. The note is one line of text, 300 characters or fewer. A line break is rejected. File import uses the same three names, and a ServiceNow-shaped file uses the `u_` prefix. Those columns may be omitted.

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
| `handling_minutes` | no | Omit, null, or blank leaves human handling time unmeasured. A non-negative whole number is stored. A JSON number or a digit string is accepted. Fractions, booleans, and negative numbers are rejected and are not rewritten. The CLI flag is `--handling-minutes` |
| `rework_minutes` | no | Omit, null, or blank leaves rework time unmeasured. A non-negative whole number is stored. A JSON number or a digit string is accepted. Fractions, booleans, and negative numbers are rejected and are not rewritten. Rework is time spent redoing work after a first pass. It is not handling time. The CLI flag is `--rework-minutes` |
| `manual_touches` | no | Omit, null, or blank leaves the touchpoint count unmeasured. A non-negative whole number is stored. A JSON number or a digit string is accepted. Fractions, booleans, and negative numbers are rejected and are not rewritten. The count is self-reported human touchpoints on that assessment. It is not handling time and it is not rework time. The CLI flag is `--manual-touches` |
| `handoffs` | no | Omit, null, or blank leaves the handoff count unmeasured. A non-negative whole number is stored. A JSON number or a digit string is accepted. Fractions, booleans, and negative numbers are rejected and are not rewritten. The count is self-reported times the assessment was handed between people or queues before disposition. It is not handling time, rework time, or a manual-touch count. The CLI flag is `--handoffs` |
| `authenticated_effort_minutes` | no | Omit, null, or blank leaves it unmeasured. A non-negative whole number is stored only when the HTTP request passed the demo password gate. The CLI has no signed-in session and rejects a number. Fractions, booleans, and negative numbers are rejected and are not rewritten. These minutes are not handling time, rework time, a manual-touch count, a handoff count, or a session timer. There is no CLI flag. |
| `cash_savings_dollars` | no | Omit, null, or blank leaves cash savings unmeasured. A non-negative whole number of dollars is stored only when the HTTP request passed the demo password gate. Zero is a reported zero. The CLI has no signed-in session and rejects a number. Fractions, booleans, and negative numbers are rejected and are not rewritten. These dollars are what the person typed. They are not a wage times handling time, rework time, a manual-touch count, a handoff count, or authenticated effort. There is no CLI flag. |
| `incident_cost`, `avoided_incident_count`, `avoided_incident_value` | not accepted | These are not decision fields. A request that includes one is rejected and nothing is saved. Avoided-incident value is a modeled assumption in the versioned cost file. The shipped file leaves both inputs null, so the figure is Not measured. It is not cash savings. |

An invalid disposition is rejected before a risk row is written. An invalid `handling_minutes` value is rejected the same way, and nothing is saved. An invalid `rework_minutes` value is rejected the same way. An invalid `manual_touches` value is rejected the same way. An invalid `handoffs` value is rejected the same way. An `authenticated_effort_minutes` number on a request that did not pass the demo password gate is rejected the same way, and nothing is saved. An invalid value is rejected the same way. A `cash_savings_dollars` number on a request that did not pass the demo password gate is rejected the same way, and nothing is saved. An invalid value is rejected the same way. `incident_cost`, `avoided_incident_count`, and `avoided_incident_value` are unrecognized decision fields. A request that includes one is rejected the same way, and nothing is saved. Approving a prohibited result without an exception rationale is also rejected, and the register is unchanged. Escalate means a person is sending the case on. It is not an approval, including when the residual tier is low.

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
| `direction_context` | Optional intake context copied from the form. `scored` is false. `provided` is false only when the result has no direction section to copy. Values and the note do not change `residual` |

`persisted` is false unless this request saved the vendor. `risk_id` and `decision` are null when nothing was saved. When a save succeeds, `risk_id` is the register id and `decision` copies the stored disposition, rationale, decider, policy reference, rule set version, `prohibited_at_decision`, `handling_minutes`, `rework_minutes`, `manual_touches`, and `handoffs`. `handling_minutes` is null when the caller did not report one. `rework_minutes` is null when the caller did not report rework time. `manual_touches` is null when the caller did not report a touchpoint count. `handoffs` is null when the caller did not report a handoff count. `authenticated_effort_minutes` is null when a signed-in caller did not report one, and a caller who is not signed in cannot store one. `cash_savings_dollars` is null when a signed-in caller did not report dollars, and a caller who is not signed in cannot store them. `decision.separate_from_score` is true. The residual tier is not copied into the disposition. `human_review_required` is true. `automatic_approval` is null. `synthetic_data` is taken from the intake result. `trust_center.fetched` is copied from that result. It is false when fetch was not requested or did not succeed. `trust_center.fetch` copies the outcome, timestamp, summary, excerpt, error, and evidence status from the same result.

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
- A human decision is recorded only with persist true. Approve, approve with conditions, escalate, and reject are that disposition. The web form on a saved risk uses the same four. Assess without persist does not save one. `handling_minutes` is optional on that decision. It is self-reported, it is not authenticated, and it is not elapsed cycle time. `rework_minutes` is optional on that same decision. It is self-reported time spent redoing work after a first pass. It is not handling minutes, it is not authenticated, and it is not elapsed cycle time. `manual_touches` is optional on that same decision. It is a self-reported count of human touchpoints. It is not handling minutes, it is not rework minutes, it is not authenticated, and it is not elapsed cycle time. `handoffs` is optional on that same decision. It is a self-reported count of times the assessment was handed between people or queues before disposition. It is not handling minutes, it is not rework minutes, it is not manual touches, it is not authenticated, and it is not elapsed cycle time.
- `assess-file --persist` uses one disposition for the whole file. It does not ask for a different decision per row. The import result page does, one vendor at a time.
- The saved row is synthetic demonstration data in the local SQLite register. Saving the same request again adds another row. The decider text is not checked against a directory.
- Draft control mappings are review prompts from mapping set 0.2.0, including a small ISO/IEC 27001 and ISO/IEC 42001 set. The ISO entries are draft portfolio review prompts. A mapping does not show that a control is implemented, that a framework is met, or that two frameworks are equivalent.
- The local event log and the mock remediation ticket on the web page are separate views of an assessment. They are not part of this JSON document.
- The CLI and the API do not call ServiceNow and do not open attachment bytes. They GET a trust-center URL only when `fetch_trust_center` is `yes`. That GET is not independent verification. File commands (`preview`, `assess-file`) do not fetch.

# File-based intake import

The public demo can read a vendor intake file, show what it parsed, and then run those rows through the same intake builder as the questionnaire. The parser lives in `app/services/intake_importer.py`. It does not score a vendor and it does not write to the database. Scoring happens only after confirmation, in `build_intake` and `run_intake`.

This is a simulated file import. It does not call ServiceNow, and it does not download attachment bytes or trust-center pages.

## What is accepted

| File | How it is read | What it becomes |
| --- | --- | --- |
| `.csv` | Python `csv`, UTF-8, commas | One vendor per row, using the questionnaire column names |
| `.xlsx` | `openpyxl`, first worksheet only | The same columns as the CSV |
| `.json` | Python `json` | A simulated ServiceNow ticket export |
| ServiceNow `.csv` | Python `csv` | The same ticket fields, flattened, with `u_` prefixes |

`.xls` and `.xlsm` are rejected. Macros, merged cells, cell comments, and extra worksheets that contain values are rejected so that content is not left out of the preview. Formulas are not evaluated. Numbers, booleans, and dates are not turned into text. A value such as `10` in `data_sensitivity` is an error, not the text `"10"`.

Limits: 256 KB, 20 vendor rows, 200 rows scanned, 40 columns, 500 characters in a cell, 30 attachments on a JSON ticket. The intake form itself stays limited to 16 KB. Import posts may use the larger cap.

Samples are served from `/try/import/sample/csv`, `/try/import/sample/xlsx`, `/try/import/sample/json`, and `/try/import/sample/servicenow-csv`. The same bytes are stored under `tests/fixtures/imports/`. The vendors are synthetic.

## Questionnaire columns

CSV and Excel use the public intake field names. The header row is required. Names are matched without regard to case or extra internal spaces. Answer values are case-sensitive. Surrounding spaces are removed.

The current columns, in the order the sample writes them, come from intake questionnaire 1.0.0 and org policy `ORG-AI-USE` 1.1.0:

| Column | Role |
| --- | --- |
| `vendor_name` | Required name, 80 characters or fewer |
| `data_sensitivity` | `public`, `internal`, `confidential`, `restricted`, or `unknown` |
| `integration_permissions` | `none`, `read_only`, `read_write`, `admin`, or `unknown` |
| `ai_use` | `none`, `assistive`, `autonomous`, or `unknown` |
| `model_training_on_customer_data` | `no`, `yes`, or `unknown`. Blank only when `ai_use` is `none` |
| `external_exposure` | `internal_only`, `customer_facing`, or `unknown` |
| `retention_deletion` | `documented`, `undocumented`, or `unknown` |
| `decisions_affecting_people` | `no`, `yes`, or `unknown` |
| `evidence_integration_permissions` | One evidence key |
| `trust_center_url` | Blank, or one `http://` or `https://` URL. Not fetched |
| `trust_soc2`, `trust_security`, `trust_privacy` | One evidence key each |
| `evidence_clause_CC-001` | One evidence key for the required contract clause |

Evidence keys: `independent_verified`, `vendor_statement`, `not_reviewed`, `expired`, `contradicts`, `none`.

A new questionnaire field or contract clause changes this list. The upload page reads the live column guide. An old file that omits a new column is rejected for the missing column.

Unknown columns are named in the error and block the import. They are not ignored.

Two rows with the same vendor name are a conflict, whether the other answers differ or match. Both rows stay on the preview. Neither row is imported until the file has one row per vendor. A file that mixes valid and invalid rows is not partially imported.

Blank rows are counted and skipped. A header with no vendor rows is an error.

## Simulated ServiceNow JSON

The file is an object. A bare array is rejected. A reviewer package (`kind` of `vendor_intake_package`) and a mock remediation ticket (`_demo_note` without `result`) are rejected. Those are exports from this app, not intake files.

| Field | Required | Use |
| --- | --- | --- |
| `import_kind` | yes | Must be `servicenow_vendor_intake` |
| `simulation` | yes | Must be JSON `true`. Any other value is rejected. This prototype does not call ServiceNow |
| `note` | yes | Text stating that the file is synthetic and was not retrieved from ServiceNow |
| `result` | yes | List of ticket objects. Empty is an error |

Each ticket:

| Field | Required | Use |
| --- | --- | --- |
| `number` | yes | Shown as the ticket id. Not scored |
| `category` | yes | Must be `vendor_risk` |
| `attachments` | yes | Evidence choices. See below |
| `u_vendor_name` | yes | `vendor_name` |
| `u_data_sensitivity`, `u_integration_permissions`, `u_ai_use`, `u_model_training_on_customer_data`, `u_external_exposure`, `u_retention_deletion`, `u_decisions_affecting_people` | yes | The same answers as the questionnaire. Text, not numbers |
| `u_trust_center_url` | yes | May be an empty string. Not fetched |
| `sys_id`, `short_description`, `description`, `state`, `priority`, `assignment_group`, `opened_at` | no | Preview context only |

`priority` does not set the residual tier. `opened_at` does not set the evaluation date. The evaluation date is the date the import is confirmed. Evidence ages are still calculated from that date by the intake builder, as they are for the form.

JSON field names are case-sensitive. Duplicate keys are an error. The repeated value is not kept.

### Attachment metadata

Evidence choices are not ticket columns in the JSON. Each required evidence field needs one attachment object. The sample uses one attachment per evidence column.

| Field | Required | Use |
| --- | --- | --- |
| `file_name` | yes | Shown on the preview. The file itself is not in the payload and is not opened |
| `u_intake_field` | yes | An evidence column: `evidence_integration_permissions`, `trust_soc2`, `trust_security`, `trust_privacy`, or `evidence_clause_CC-001` |
| `u_evidence_option` | yes | One of the six evidence keys |
| `sys_id`, `content_type`, `table_name`, `table_sys_id` | no | Text, shown or stored only as metadata |
| `size_bytes` | no | A non-negative integer. A string is a type error |

An assessment answer or the trust-center URL on an attachment is an error. Those belong on the ticket. Two attachments for the same `u_intake_field` are an error, including when the options match. The extra record is reported and is not dropped. Missing attachment metadata for a required evidence field is an error. It is not treated as `none`.

`table_name` in the sample is `incident`. That label is not checked. The category on the ticket is what must be `vendor_risk`.

## Simulated ServiceNow CSV

The optional CSV uses the same ticket fields in one row. Evidence choices are `u_` columns, for example `u_trust_soc2`, because a CSV has no nested attachment list. `number` and `category` are required. The context columns are optional. A file that has both `vendor_name` and `u_vendor_name` is rejected. Excel is not used for the ServiceNow shape.

## Confirming an import

`/try/import` uploads the file and renders the preview. The preview lists every mapped field, ticket context, attachment metadata, and every problem. It does not show an inherent tier, a residual tier, or a policy outcome.

Confirm posts the previewed rows back as JSON. The server checks them again with the intake builder. It does not re-read the original file. A field that is not a questionnaire column is rejected. When the rows are valid, each one is passed to `run_intake`. The result page shows the engine output, the workflow steps, and the mock remediation payload when one is produced. Nothing is written to the risk register, and the mock ticket is not sent.

A low score still does not approve the vendor. The result page uses the same assessment partial as the rest of the demo, including the human-review notice.

## Limitations

- There is no live ServiceNow connection, OAuth client, or attachment download.
- The importer does not accept an arbitrary spreadsheet, PDF, or email.
- Imported rows are not saved. Closing the page drops them.
- The confirmation step trusts the previewed field values after a second validation. It does not prove the bytes on disk were unchanged.
- A file hash of an uploaded workbook is not stored. The evidence model still treats a hash as a change detector, not as proof of authenticity.
- `openpyxl` reads `.xlsx` only. It is the only added dependency.
- The column list will change if the questionnaire or the org policy changes. Old files are not migrated.

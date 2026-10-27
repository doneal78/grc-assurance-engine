# Evidence Model (Evidence Policy 0.2.0, draft)

This document defines how a claim's evidence status is derived from evidence records. Statuses are calculated by written rules, not typed in by hand, so every status can be explained. Freshness limits will live in `app/data/evidence_policy.json`, a file added for this phase because the build plan requires configurable freshness.

## Evidence record fields

| Field | Meaning |
| --- | --- |
| evidence_id | Unique identifier |
| claim_id | The claim this evidence relates to |
| artifact_name, artifact_type | What the artifact is, for example a SOC 2 Type II report |
| source | vendor, independent_auditor, or internal_observation |
| collection_date | Date the artifact was issued or collected |
| review | Optional: reviewer, review date, and four recorded checks |
| file_sha256 | Optional file hash |

A review records four checks: relevant to this service, in scope, supports the claim, and contradicts the claim. Currency is not a reviewer judgment. It is calculated from the collection date and the freshness limit.

## Freshness limits (illustrative)

| Artifact type | Maximum age in days |
| --- | --- |
| soc2_type2_report | 365 |
| penetration_test | 365 |
| policy_document | 365 |
| vendor_questionnaire_answer | 365 |
| vendor_statement | 365 |
| configuration_export | 90 |
| contract_clause | 365 |

Evidence policy 0.2.0 adds `contract_clause`. The 365-day limit matches a policy document in this illustrative set. It is not a legal conclusion about how long a contract term lasts. The other limits are unchanged from 0.1.0.

## Status of one evidence record

The first rule that matches wins.

| Order | Condition | Result | Why |
| --- | --- | --- | --- |
| 1 | Reviewer recorded that it contradicts the claim | conflicting | A contradiction must be reconciled no matter how old the evidence is |
| 2 | Older than its freshness limit | expired | Reviewing outdated evidence cannot make it current |
| 3 | No review recorded | not_reviewed | Having a document is not the same as checking it |
| 4 | Relevant, in scope, or supports claim is false | unusable, excluded | Evidence that does not support this claim cannot count toward it |
| 5 | Source is vendor | self_attested | The vendor describing its own controls is not independent verification |
| 6 | Otherwise | verified | Independent, reviewed, current, relevant, in scope, and supporting |

## Status of a claim

| Situation | Claim status | Why |
| --- | --- | --- |
| No evidence records | missing, reason "no evidence provided" | Not demonstrated, which is different from a confirmed failure |
| Any record is conflicting | conflicting | One verified document cannot outweigh an unresolved contradiction |
| Records exist but all are unusable | missing, reason "no evidence supports the claim" | Kept distinguishable from having no records at all |
| Otherwise | the best usable status: verified, then self_attested, then expired, then not_reviewed | An extra weak document should not drag down a strong one |

## Evaluation date

The evaluation date is passed in, never read from the system clock. The same evidence and the same date always produce the same result, which keeps the Phase 2 repeatability rule intact and lets tests check exact boundaries. Evidence at exactly its maximum age is still current. One day older is expired.

## Invalid input

The validator rejects, with an error naming each problem: unknown artifact types or sources, a collection or review date after the evaluation date, a review date before the collection date, a review missing any of the four checks, evidence pointing to a claim that does not exist, and duplicate evidence IDs.

## File hashes

A matching SHA-256 hash shows the file has not changed since its hash was recorded. It does not show the file is authentic, accurate, complete, or sufficient. A hash is recorded for reference and never changes a status.

## Required contract clauses

A required clause from `app/data/org_policy.json` is checked as a claim. The evidence record's `claim_id` is the clause id, for example `CC-001`. The clause text is the claim statement. `validate_contract_clauses` calls `validate`, so a clause does not have a second status algorithm.

`contract_clause` is the artifact type for a contract excerpt. Another known artifact type can also support a clause, and it keeps that type's freshness limit. A vendor source is self-attested even when the artifact type is `contract_clause`. An internal observation or an independent auditor can reach verified when the other review rules pass.

| Clause situation | Status | Meaning here |
| --- | --- | --- |
| No evidence records | missing | Not demonstrated. Not a confirmed breach of the clause. |
| Reviewed, current, supporting, source is not the vendor | verified | The assured state in this model. There is no separate "assured" label. |
| Same, but the source is the vendor | self_attested | The vendor's own statement is not independent verification. |
| A record contradicts the clause | conflicting | One supporting document does not outweigh the contradiction. |
| Older than the freshness limit, and not contradicting | expired | Currency is calculated, not assumed. |
| No review recorded, and still current | not_reviewed | Having the excerpt is not the same as checking it. |

The risk engine records that status, the reason, and the evidence basis. It does not add the clause to the claim list, so the clause does not change evidence confidence or fire ESC-003. See `docs/risk-model.md`.

## Trust-center citations and fetch

Intake questionnaire 1.1.0 can store a vendor trust-center URL and three pasted artifact choices: a SOC 2 Type II report, security documentation, and a privacy notice. The same questionnaire can store vendor direction, residual direction, and a short note. Those three answers are not evidence records and are not scored. Leaving `fetch_trust_center` omitted or `no` does not open the URL. There is no scraper and no new runtime dependency. The GET, when requested, uses `urllib` in `app/services/trust_center_fetch.py`.

A URL with no artifact choice and no fetch creates no scored evidence record. It cannot raise evidence confidence, satisfy a contract clause, or approve the vendor. Each pasted artifact choice becomes one or more ordinary evidence records, and `validate` assigns the status. The SOC choice is cited for the authentication claim and the logging claim. The validator scores those claims separately. The security document is cited for transmission protection. The privacy notice is its own claim. Draft ISO/IEC 42001 review prompts can match that `privacy` topic. Those prompts do not change the evidence status, and they are not a reviewed privacy-law mapping.

No new artifact type was added for those pasted choices. The SOC report uses `soc2_type2_report` (365 days). The security document and the privacy notice use `policy_document` (365 days). A reviewed SOC whose source is the auditor can reach verified. A reviewed privacy notice or security document is an internal observation when someone other than the vendor checked the published page, because the page itself is the vendor's. The vendor's own description stays self-attested. The claim text says what the cited document addresses. Verified means that review passed. It does not mean the practice was independently tested, and it does not approve the vendor.

A requested fetch is a different record. It uses artifact type `vendor_statement`, source `vendor`, and no review. `validate` therefore returns `not_reviewed`: the page was collected and nobody has checked it. The record cannot become `verified` under these inputs, because a vendor source stops at `self_attested` even if a review were present, and this record has no review. The fetch claim is not added to the scored claim list, so it does not change evidence confidence. A failed GET produces no evidence record. The same validator reports that claim as `missing`. That is an evidence gap, not a confirmed control failure and not a successful collection.

The result copies `pointer_id`, `trust_center_url`, `fetched_at`, `content_summary`, and `excerpt` onto the evidence view when the record has them. Those fields do not change the status rules above. A file hash is still not required for a fetch. The excerpt is a review aid. It does not prove the page is authentic, complete, or sufficient, and it does not certify the vendor.

## Connection to the risk engine

The validator sets each claim's evidence status, and the risk engine uses those statuses as its evidence input. Later rule sets can add intake fields. They do not reinterpret an evidence status. Each result records the rule set version, the evidence policy version, and the org policy version.

## Worked examples (expected results)

Evaluation date for all examples: 2026-10-14.

| Example | Claim status |
| --- | --- |
| Claim with no evidence records | missing, no evidence provided |
| Independent SOC 2 report, 200 days old, reviewed, all checks pass | verified |
| Same report, exactly 365 days old | verified |
| Same report, 366 days old | expired |
| Vendor statement, reviewed, all checks pass | self_attested |
| Independent report, not reviewed | not_reviewed |
| Reviewed report where supports claim is false | missing, no evidence supports the claim |
| Verified report plus a configuration export marked as contradicting | conflicting |
| Expired SOC 2 report plus a current, reviewed vendor statement | self_attested |

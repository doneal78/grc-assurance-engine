# Evidence Model (Evidence Policy 0.1.0, draft)

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

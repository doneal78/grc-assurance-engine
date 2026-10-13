# Risk Model (Rule Set 0.1.0, draft)

This model is illustrative. It is not an industry-standard methodology and is not empirically calibrated. Weights and thresholds will live in `app/data/risk_rules.json`, and every assessment records the rule set version it used.

## Three separate results

| Result | Meaning | Form |
| --- | --- | --- |
| Inherent risk | Exposure before considering safeguards | Score 0 to 100, plus a tier |
| Evidence confidence | How well the available evidence supports the claims | high, medium, low, or none |
| Residual risk | Exposure remaining after supported safeguards | A tier, with a stated reason |

These are never combined into one number.

## Inputs and inherent risk points

| Factor | Rule ID | Allowed values and points |
| --- | --- | --- |
| Data sensitivity | INH-DATA | public 0, internal 10, confidential 25, restricted 35, unknown |
| Integration permissions | INH-PERM | none 0, read_only 10, read_write 20, admin 30, unknown |
| AI use | INH-AI | none 0, assistive 10, autonomous 20, unknown |
| Model training on customer data | INH-TRAIN | no 0, yes 10, unknown (only when AI use is not none) |
| External exposure | INH-EXPO | internal_only 0, customer_facing 5, unknown |
| Retention and deletion | (escalation only) | documented, undocumented, unknown |

An `unknown` value adds no points and is listed under missing information. Any unknown makes the result provisional. When provisional, the inherent tier and residual risk are both reported as undetermined, and the partial score is shown for reference only. Unknown is never treated as proof of safety or failure.

When the questionnaire and technical integration details disagree, scoring uses the technical detail, both values are kept, and the conflict is recorded.

Tiers: low 0 to 29, moderate 30 to 54, high 55 to 74, critical 75 to 100.

## Evidence statuses

| Status | Weight | Meaning |
| --- | --- | --- |
| verified | 1.0 | A reviewer confirmed the evidence is relevant to this service, covers the right scope, is current, and supports the specific claim |
| self_attested | 0.5 | The vendor's own statement or document, not independently checked |
| expired | 0.25 | Evidence existed but is past its validity date |
| not_reviewed | 0 | Evidence was provided but nobody has reviewed it yet |
| missing | 0 | No evidence was provided for the claim |
| conflicting | 0 | Another source contradicts the claim |

A report on file is not enough for verified. In this rule set, the engine relies on the status a reviewer assigns. Phase 3 adds the fields that support that judgment.

Confidence is the average weight across all claims: high at 0.75 or above, medium at 0.40 or above, low below 0.40, and none when there are no claims.

## Residual risk

Residual risk equals the inherent tier, lowered by one tier only when all of these are true: the result is not provisional, confidence is high, no claim is conflicting, and no escalation rule fired. It is never lowered by more than one tier.

## Mandatory escalation rules

Any rule that fires sets the review path to escalated review, regardless of the score.

| Rule ID | Condition |
| --- | --- |
| ESC-001 | Restricted data with read_write or admin permissions |
| ESC-002 | Autonomous AI with confidential or restricted data |
| ESC-003 | Any claim with status conflicting |
| ESC-004 | AI in use, confidential or restricted data, and model training is yes or unknown |
| ESC-005 | Data sensitivity, integration permissions, or AI use is unknown |
| ESC-006 | Confidential or restricted data, and retention and deletion is undocumented or unknown |

## Worked scenarios (expected results)

| Scenario | Inherent | Confidence | Residual | Escalations | Path |
| --- | --- | --- | --- | --- | --- |
| All core answers unknown, no claims | 0, undetermined | none | undetermined | ESC-005 | escalated_review |
| Internal data, read_only, no AI, all claims verified | 20, low | high | low | none | standard_review |
| Restricted data, admin, assistive AI, customer facing, all verified | 80, critical | high | critical | ESC-001 | escalated_review |
| Confidential data, questionnaire says read_only, integration shows admin | 55, high | low | high | ESC-003 | escalated_review |

## Outputs

Every evaluation returns: the rule set version, the inherent score, tier, and contributing factors with rule IDs, whether the result is provisional, evidence confidence with counts per status, the residual tier and its reason, fired escalation rules with reasons, missing information, conflicts, and a review path of standard_review or escalated_review. The engine never returns an approval. A person makes every disposition.

## Invalid input

Missing required fields or values outside the allowed lists are rejected with an error naming each problem field. The engine does not guess or substitute values.

## Repeatability

The same input and the same rule set version always produce the same output.

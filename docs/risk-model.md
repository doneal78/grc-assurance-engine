# Risk Model (Rule Set 0.3.0, draft)

This model is illustrative. It is not an industry-standard methodology and is not empirically calibrated. Weights, thresholds, and escalation definitions live in `app/data/risk_rules.json`, and every assessment records the rule set version it used.

Rule set 0.2.0 keeps the same point values and tier boundaries as 0.1.0. It adds the assessment contract on every escalation rule, and it narrows the old ESC-005. That rule used to escalate whenever data sensitivity, integration permissions, or AI use was unknown. Unknown data sensitivity still always escalates. Unknown permissions and unknown AI use escalate only when the data is confidential or restricted, as ESC-007 and ESC-008.

Rule set 0.3.0 keeps those point values, tier boundaries, and ESC-001 through ESC-008. It adds one intake answer, `decisions_affecting_people`, and ESC-009 for when that answer is unknown. The prohibited outcome below is not a change to the score. It comes from the separate org policy in `app/data/org_policy.json`.

## Separate results

| Result | Meaning | Form |
| --- | --- | --- |
| Inherent risk | Exposure before considering safeguards | Score 0 to 100, plus a tier |
| Evidence confidence | How well the available evidence supports the claims | high, medium, low, or none |
| Residual risk | Exposure remaining after supported safeguards | A tier, with a stated reason |
| Policy outcome | Whether the intake matches a hard restriction in the org policy | `prohibited` or `not_prohibited`, citing the restriction id and policy version |

The first three are never combined into one number. The policy outcome is not a tier and does not add points.

## Inputs and inherent risk points

| Factor | Rule ID | Allowed values and points |
| --- | --- | --- |
| Data sensitivity | INH-DATA | public 0, internal 10, confidential 25, restricted 35, unknown |
| Integration permissions | INH-PERM | none 0, read_only 10, read_write 20, admin 30, unknown |
| AI use | INH-AI | none 0, assistive 10, autonomous 20, unknown |
| Model training on customer data | INH-TRAIN | no 0, yes 10, unknown (only when AI use is not none) |
| External exposure | INH-EXPO | internal_only 0, customer_facing 5, unknown |
| Retention and deletion | (escalation only) | documented, undocumented, unknown |
| Decisions affecting people | (policy check, no points) | no, yes, unknown |

`decisions_affecting_people` asks whether the AI makes fully automated decisions about people's eligibility, safety, or similar outcomes, with no human review. It uses the same yes/no/unknown answers as model training. It is not an inherent-risk factor. `yes` is handled by the org policy, not by the point table. `unknown` adds no points, is listed under missing information, and fires ESC-009.

An `unknown` value adds no points and is listed under missing information. Any unknown makes the result provisional. When provisional, the inherent tier and residual risk are both reported as undetermined, and the partial score is shown for reference only. Unknown is never treated as proof of safety or failure, and it is never a prohibited value. An unknown does not, by itself, open a deeper assessment. Which unknowns escalate is defined by the rules below and explained under Proportionality.

When the questionnaire and technical integration details disagree, scoring uses the technical detail, both values are kept, and the conflict is recorded.

Tiers: low 0 to 29, moderate 30 to 54, high 55 to 74, critical 75 to 100. Why those cuts are where they are is under Proportionality. The numbers were not moved in 0.2.0 or 0.3.0.

## Evidence statuses

| Status | Weight | Meaning |
| --- | --- | --- |
| verified | 1.0 | A reviewer confirmed the evidence is relevant to this service, covers the right scope, is current, and supports the specific claim |
| self_attested | 0.5 | The vendor's own statement or document, not independently checked |
| expired | 0.25 | Evidence existed but is past its validity date |
| not_reviewed | 0 | Evidence was provided but nobody has reviewed it yet |
| missing | 0 | No evidence was provided for the claim |
| conflicting | 0 | Another source contradicts the claim |

A report on file is not enough for verified. The evidence validator derives claim statuses from evidence records and reviewer checks; the risk engine consumes those resulting statuses. See `docs/evidence-model.md` for the derivation rules.

Confidence is the average weight across all claims: high at 0.75 or above, medium at 0.40 or above, low below 0.40, and none when there are no claims.

## Residual risk

Residual risk equals the inherent tier, lowered by one tier only when all of these are true: the result is not provisional, confidence is high, no claim is conflicting, and no escalation rule fired. It is never lowered by more than one tier. A prohibited policy outcome does not block that reduction and does not raise the tier.

Questionnaire 1.1.0 can also store vendor direction, residual direction, and a short note. Those answers are intake context for a person. They are not inputs to this formula. `unknown` on either direction field means the requester does not know the direction. It is not a missing scoring answer, it does not make the result provisional, and it does not fire ESC-009. A stated direction does not lower or raise the residual tier, and it is not a safeguard.

## Organization policy outcome

The profile is one file, `app/data/org_policy.json`. This prototype is not multi-tenant. The current profile is illustrative policy `ORG-AI-USE` version `1.1.0`. Version 1.1.0 keeps the HR-001 and CC-001 text from 1.0.0. It marks CC-001 enforced and checks it against evidence. Point values are unchanged.

| Kind | Id | What it does in this version |
| --- | --- | --- |
| Hard restriction | HR-001 | Fully automated AI decisions about eligibility, safety, or similar outcomes with no human review. `decisions_affecting_people` = `yes`. The result is `prohibited` and cites HR-001 plus the policy id and version. |
| Required contract clause | CC-001 | No vendor model training on company or customer data. Checked against evidence. The status is an evidence status, not a score. |

The starter profile stops there. Another restriction or clause is another object in the same list. This version does not add a second restriction.

A `yes` answer matches HR-001 even when AI use is `none`. The engine does not reconcile that contradiction. Both answers stay visible for the reviewer.

`unknown` does not match HR-001. The result stays `not_prohibited`, becomes provisional, and opens ESC-009 because that unknown can hide the restriction at any data sensitivity.

A matched restriction sets the review path to escalated review. It does not fire an escalation rule, so it does not change the residual-tier calculation. A moderate inherent score can still show a lowered residual tier and a prohibited policy outcome at the same time. The score is not a clearance, and `not_prohibited` is not an approval.

CC-001 is checked by the evidence validator, not by a separate scoring rule. Evidence for the clause uses `CC-001` as its claim id. The artifact type `contract_clause` is in the evidence policy. Any other known artifact type can also be linked to the clause and keeps that type's freshness limit.

The clause status uses the evidence vocabulary. Verified is the assured state: a non-vendor source was reviewed and the evidence is current, relevant, in scope, and supports the clause. Self-attested means the source is the vendor. Missing means no usable evidence was provided. Conflicting means at least one record contradicts the clause. Expired and not reviewed stay distinct. There is no separate "assured" status.

A missing or conflicting clause does not change the inherent score, the residual tier, or the review path, and it does not fire a new escalation rule. ESC-004 still covers a yes or unknown training answer on confidential or restricted data. That rule answers whether the intake says training happens. The clause check answers whether evidence supports the contractual limit. A gap is shown on the result. Like other evidence gaps, it is enough to draft a follow-up. It does not block approval, and it does not require the exception rationale that a prohibited result requires. The person remains the decider.

A `yes` on model training still follows INH-TRAIN and, when the other conditions are met, ESC-004. That is the risk rule set. The clause status is recorded beside it.

## Mandatory escalation rules

Any rule that fires sets the review path to escalated review, regardless of the score. A fired rule copies its assessment type, owner role, required output, and next step from this rule set into the result. The pages display those fields. They do not invent a follow-up.

The same words are stored in `app/data/risk_rules.json`.

### ESC-001 Privileged-access impact assessment

**Condition.** Restricted data with read_write or admin permissions.

**Owner role.** GRC analyst.

**Required output.** A written finding on whether this integration can change or administer restricted data, which limits apply to that access, and whether the exposure is to be reduced, accepted for a stated period, or stopped.

**Next step.** Record the finding on the risk register, with a remediation action when access must change. Escalated review continues until a person records that outcome.

### ESC-002 AI impact assessment

**Condition.** Autonomous AI with confidential or restricted data.

**Owner role.** AI governance reviewer.

**Required output.** An impact assessment of the autonomous behavior, the confidential or restricted data it can reach, who or what is affected, and the human oversight that can interrupt it.

**Next step.** Keep the engagement on escalated review until the AI governance reviewer records the assessment outcome and any remediation that outcome requires.

### ESC-003 Evidence conflict review

**Condition.** A claim has status conflicting.

**Owner role.** Evidence reviewer.

**Required output.** One resolved evidence status for the conflicting claim, naming the source relied on and why the contradicting source was rejected or superseded.

**Next step.** Update the claim or the evidence record, then re-run the assessment. The conflict remains until a reviewer resolves it.

### ESC-004 Model-training assessment

**Condition.** AI in use with confidential or restricted data, and model training is yes or unknown.

**Owner role.** AI governance reviewer.

**Required output.** A determination of whether customer or organizational data is used to train or improve a model, which data elements are involved, and the contractual or technical limit that supports the answer.

**Next step.** When training is confirmed, record a risk and a remediation action. When training is shown not to occur, re-run the assessment with model training set to no. An unknown answer is not treated as no.

### ESC-005 Data-classification review

**Condition.** Data sensitivity is unknown.

**Owner role.** Business owner.

**Required output.** The data categories in scope and one confirmed sensitivity value: public, internal, confidential, or restricted.

**Next step.** Re-run the assessment with that value before opening any further deeper assessment. The provisional score is not a completed review.

### ESC-006 Retention and deletion review

**Condition.** Confidential or restricted data, and retention and deletion is undocumented or unknown.

**Owner role.** Records owner.

**Required output.** The retention period, the deletion method, and where that practice is documented, or a finding that the practice is not documented.

**Next step.** When the practice is undocumented, record a remediation action to document or change it. When it is documented, re-run the assessment with retention and deletion set to documented.

### ESC-007 Integration access review

**Condition.** Integration permissions are unknown and data sensitivity is confidential or restricted.

**Owner role.** Integration owner.

**Required output.** The effective permission level taken from the integration configuration: none, read_only, read_write, or admin.

**Next step.** Re-run the assessment with the confirmed permission level. Restricted data with read_write or admin access then follows the privileged-access impact assessment.

### ESC-008 AI use determination

**Condition.** AI use is unknown and data sensitivity is confidential or restricted.

**Owner role.** Business owner.

**Required output.** Whether the service uses no AI, assistive AI, or autonomous AI, and whether a model is trained on customer data.

**Next step.** Re-run the assessment. Autonomous use follows the AI impact assessment. Assistive or autonomous use with training set to yes or unknown follows the model-training assessment. Confirmed absence of AI does not open either assessment.

### ESC-009 Affected-decision determination

**Condition.** Whether the AI makes fully automated decisions about people's eligibility, safety, or similar outcomes, with no human review, is unknown.

**Owner role.** Business owner.

**Required output.** Whether the AI makes those fully automated decisions with no human review, answered yes or no.

**Next step.** Re-run the assessment with yes or no. Yes matches the org policy hard restriction. Unknown is not treated as no.

## Proportionality

The tier and the escalation path answer different questions. The tier is how much exposure the known answers add up to. An escalation opens one named assessment when a specific condition is met. A low tier does not skip an escalation, and a missing answer does not open every deeper assessment.

These cuts are design choices in an illustrative model. They are not calibrated to observed losses. An organization that adopts the model should replace them with its own methodology.

### Why each tier boundary is where it is

Point values are multiples of 5, and the largest single factor is restricted data at 35. The bands are wide enough that one answer moves a result by at most one tier. Stacking is what reaches high and critical.

**Low ends at 29.** The ordinary contained case is internal data (10) plus read-only access (10), which scores 20 and stays low. Confidential data alone scores 25 and also stays low: sensitivity without a meaningful integration, without AI, and without customer exposure is not yet treated as a moderate engagement. The next real scores are 30. That is either admin access on its own (30), or two factors together, such as confidential data plus customer exposure (25 + 5) or internal data plus read-write access (10 + 20). The band is written through 29, rather than through 25, so a later factor worth less than 5 points would not silently become moderate. The current point table cannot actually produce 21 through 29.

**Moderate runs from 30 through 54.** This is one strong factor, or a pair of ordinary ones. Restricted data alone is 35. Restricted data with read-only access is 45. Confidential data with read-write access is 45. Confidential data with read-only access and assistive AI is 45. None of those, on their own, meet a mandatory escalation rule.

**High starts at 55.** That number is the first combination of sensitive data with broad access: restricted data plus read-write access (35 + 20), or confidential data plus admin access (25 + 30). Restricted data plus read-only access plus assistive AI is also 55 (35 + 10 + 10). Restricted data with admin access and no further factor is 65, which stays high. That case still escalates through ESC-001, so the workflow does not depend on calling it critical.

**Critical starts at 75.** Reaching 75 takes a third material factor on top of the two largest. Restricted data plus admin access plus assistive AI is 75 (35 + 30 + 10). Restricted data plus read-write access plus autonomous AI is 75 (35 + 20 + 20). Confidential data plus admin access plus autonomous AI is 75 (25 + 30 + 20). The maximum is 100: restricted 35, admin 30, autonomous 20, training on customer data 10, and customer-facing exposure 5. Critical is reserved for that kind of stack. Privileged access to restricted data is high, and it is a mandatory escalation, without using up the top tier before AI, training, or customer exposure is added.

### Why each escalation stops where it does

**ESC-001** requires read-write or admin access, not the mere presence of restricted data. Read-only access to restricted data scores 45 (moderate) and stays on standard review. No access scores 35 and does the same. The deeper assessment is about the ability to change or administer restricted data. A person still reviews the moderate result. An organization that wants every use of restricted data to open that assessment would add a rule; this set does not.

**ESC-002** is limited to autonomous use. Assistive use can still escalate through ESC-004 when training is yes or unknown. Assistive use with training explicitly set to no, on confidential data and read-only access, scores 45 and does not escalate.

**ESC-003** has no score condition. A conflicting claim escalates at every tier, because the record does not support a single conclusion.

**ESC-004** treats training unknown as the condition that needs the assessment, and treats an explicit no as enough to stay off this path. Unknown is not converted into no.

**ESC-005** escalates only when data sensitivity itself is unknown. That unknown can hide every data-dependent rule, so the next assessment is classification, performed by the business owner, and the other deeper assessments wait for the re-run. A scoring intake with every core answer unknown, and with the policy answer set to no, fires ESC-005 only. If the policy answer is also unknown, ESC-009 fires as well. The other blank fields stay in missing information, the tier stays undetermined, and the review path stays escalated. It does not open an AI impact assessment before anyone knows what the data is.

**ESC-006** still fires when the score is low. Confidential data with no integration and undocumented retention scores 25 (low) and escalates. The condition is an unaddressed retention obligation on sensitive data, not a high total. Unknown or undocumented retention on public or internal data does not fire this rule.

**ESC-007** fires when permissions are unknown and the data is confidential or restricted. Unknown admin access on confidential data would move the score from 25 to 55, into high, and unknown read-write or admin access on restricted data is exactly ESC-001. Unknown permissions on public or internal data do not fire it. The largest hidden addition there is admin (30): a public service stays at most moderate, and an internal read-only service becomes at most moderate (10 + 30). The result is still provisional, so the partial score is not a finished low or moderate classification.

**ESC-008** fires when AI use is unknown and the data is confidential or restricted, because that unknown can hide ESC-002 or ESC-004. Unknown AI use on public or internal data cannot meet either rule, both of which require confidential or restricted data. A public customer FAQ with AI use left blank stays provisional under standard review. It does not open an AI impact assessment.

**ESC-009** fires whenever the decisions-affecting-people answer is unknown, including on public or internal data. HR-001 does not depend on data sensitivity, so this unknown is not narrowed the way ESC-007 and ESC-008 are. Answering yes does not fire ESC-009. Yes is the policy outcome, not a score escalation. Answering no fires nothing from this rule.

**External exposure** unknown never escalates. It is worth at most 5 points, and it still makes the result provisional.

**HR-001** is not an escalation rule. It does not add points and it does not stop a one-tier residual reduction. It does move the review path to escalated review, because a prohibited use should not be presented as routine standard review. The path change is routing. The tier is still the tier.

### What standard review means for a provisional result

`standard_review` is not a completed disposition and it is not an approval. When an unknown left the result provisional, the inherent and residual tiers are undetermined even if no escalation rule fired. A person still has to supply the missing answer and re-run, or record why the gap is acceptable. The difference from escalated review is that no deeper assessment of the kinds listed above has been opened.

## Worked scenarios (expected results)

| Scenario | Inherent | Confidence | Residual | Escalations | Path |
| --- | --- | --- | --- | --- | --- |
| All core answers unknown, no claims | 0, undetermined | none | undetermined | ESC-005 | escalated_review |
| Internal data, read_only, no AI, all claims verified | 20, low | high | low | none | standard_review |
| Restricted data, admin, assistive AI, customer facing, all verified | 80, critical | high | critical | ESC-001 | escalated_review |
| Confidential data, questionnaire says read_only, integration shows admin | 70, high | low | high | ESC-003 | escalated_review |
| Public FAQ, no integration, AI use unknown, claims verified | 5, undetermined | high | undetermined | none | standard_review |
| Restricted archive, read_only, no AI, documented retention, verified | 45, moderate | high | low | none | standard_review |
| Confidential data, assistive AI, training no, read_only, verified | 45, moderate | high | low | none | standard_review |
| Data sensitivity unknown, otherwise the lower-risk baseline | 10, undetermined | high | undetermined | ESC-005 | escalated_review |
| Decisions affecting people unknown, otherwise the lower-risk baseline | 20, undetermined | high | undetermined | ESC-009 | escalated_review |
| Decisions affecting people yes, assistive AI, internal, read_only, training no, one verified claim | 30, moderate | high | low | none | escalated_review, policy prohibited HR-001 |

Unless a row says otherwise, `decisions_affecting_people` is `no`. The policy outcome is then `not_prohibited` under `ORG-AI-USE` 1.1.0, and the review path is the path in the table. Clause evidence status is not a column here. It does not change the score, the residual tier, or the review path. The synthetic scenario `contract-clause-conflict` uses internal data, read-only access, and assistive AI with training set to no. That scores 30, moderate, with a low residual tier and standard review. CC-001 is conflicting on that scenario. The same answers with no clause evidence produce the same score and the same review path.

## Outputs

Every evaluation returns: the rule set version, the inherent score, tier, and contributing factors with rule IDs, whether the result is provisional, evidence confidence with counts per status, the residual tier and its reason, fired escalation rules with their reasons and the assessment type, owner role, required output, and next step, missing information, conflicts, the org policy id and version, the policy outcome, each required contract clause with `enforced: true` and an evidence status, reason, and evidence basis, and a review path of standard_review or escalated_review. When the caller does not supply a clause check, each required clause is missing because no clause evidence was provided. The engine never returns an approval or a rejection. A prohibited outcome is not a rejection. A clause gap is not a rejection. A person makes every disposition.

## Human disposition

On a saved risk, a person records one of four dispositions:

- approve
- approve with conditions, with the conditions stored as text
- escalate, which sends the case on and is not an approval
- reject

The record stores the rationale, the decider's name or role, a UTC timestamp from the server clock, the policy id and version, and the rule set version. Those last two are copied from the saved assessment. The form does not ask the reviewer to type them. The same form has an optional field for minutes spent reviewing, a separate optional field for minutes spent redoing work after a first pass, a separate optional count of manual touches, and a separate optional count of handoffs. Blank stores null. A non-negative whole number is stored as self-reported handling time, self-reported rework time, a self-reported touchpoint count, or a self-reported handoff count. None of them is elapsed cycle time, none is checked against an identity system, and none is an input to the cost formula. Rework minutes are not handling minutes. Manual touches are not handling minutes and not rework minutes. Handoffs are not handling minutes, not rework minutes, and not manual touches. A signed-in disposition form can also store optional authenticated effort minutes. That field is absent when the demo password gate is off, and the public try and import forms do not ask for it. Blank stores null. A non-negative whole number is the minutes that reviewer entered. The application does not time the session. Those minutes are not handling minutes and are not an input to the cost formula. Each save writes a workflow event. Saving again replaces the current decision and writes another event. A blank minutes field on that later save clears the number stored earlier for that field. The earlier rationale is not kept as a second row. The local event log is not tamper-proof.

A prohibited result cannot be approved, with or without conditions, unless the reviewer records an exception rationale. Rejection does not require one. Escalation does not require one. An exception rationale is rejected when the result is not prohibited, and it is rejected on a rejection or an escalation, so the field means only "proceed despite this restriction."

A general intake can be saved with that decision in the same step. The residual tier is still the engine result. Saving a low tier with disposition escalate leaves both values on the record. The tier did not approve the vendor.

The exception is allowed on purpose. The policy check makes the restriction visible and traceable. It does not decide the case, and it is not an automatic block. The person remains the final decider. The exception does not change the policy outcome. The assessment stays prohibited, and the decision shows both the restriction and the recorded reason for proceeding.

This prototype has no non-overridable restriction. An organization that needs a legal ban to be impossible to override inside the tool would configure that separately. It is not implemented here. The recorded decider is not checked against an identity system or against the restriction's owner role. A saved result that has no policy reference cannot receive a decision until the scenario is evaluated again.

## Invalid input

Missing required fields or values outside the allowed lists are rejected with an error naming each problem field. The engine does not guess or substitute values. An escalation rule that omits its assessment type, owner role, required output, or next step is rejected before scoring, so a deeper assessment cannot fire without a defined follow-up. A policy that lists `unknown` as a prohibited value, or that marks a required contract clause as not enforced, is rejected before scoring. A clause check that omits a required clause, repeats one, or uses a status outside the evidence vocabulary is rejected.

## Repeatability

The same input and the same rule set version always produce the same output. An assessment stored under an older rule set keeps that version on its record. Re-running 0.1.0 answers under 0.2.0 can change the review path where ESC-005 used to match and no longer does. Re-running under 0.3.0 requires `decisions_affecting_people`. The same other answers with that field set to `no` keep the 0.2.0 score and the same ESC-001 through ESC-008 results. The decision timestamp uses the server clock and is not part of the deterministic score.

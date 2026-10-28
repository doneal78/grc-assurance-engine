# Cost-of-Assurance Model

**Status:** Illustrative model, version 0.1.0. No user study or production measurements have been collected.

## Inputs

The example inputs live in `app/data/cost_assumptions.json` so a result can be reproduced from its versioned source:

| Input | Value | Type |
| --- | ---: | --- |
| Assessments per month | 20 | Illustrative assumption |
| Baseline handling time | 2.0 hours per assessment | Illustrative assumption |
| Assisted handling time | 1.5 hours per assessment | Illustrative assumption |
| Added human review | 0.25 hours per assessment | Illustrative assumption |
| Ongoing maintenance | 2.0 hours per month | Illustrative assumption |
| Loaded labor rate | $60 per hour | Illustrative assumption |
| One-time development cost | Not provided; excluded | Unknown |

These are modeled inputs, not observed application performance.

## Formulas and example result

Gross capacity hours = assessment volume × (baseline handling hours − assisted handling hours)  
Review effort hours = assessment volume × review hours per assessment  
Net capacity hours = gross capacity hours − review effort hours − monthly maintenance hours  
Capacity value = capacity hours × loaded hourly labor rate

For the current inputs:

- Gross capacity: `20 × (2.0 − 1.5) = 10` hours per month ($600 gross modeled value)
- Added review: `20 × 0.25 = 5` hours per month
- Maintenance: `2` hours per month
- Net modeled labor capacity: `10 − 5 − 2 = 3` hours per month ($180 net modeled value)

The service uses decimal arithmetic and rounds output to two decimal places. If assisted handling takes longer than baseline, the net result can be negative; the model does not hide added effort.

## Interpretation

The result is **modeled labor capacity**, not actual cash savings. No payroll reduction, reduced contractor spend, or other cash outflow reduction has been measured. The model reports no cash savings. One-time development costs are unknown and excluded; they must not be combined with recurring maintenance as though they were the same cost.

The modeled values above are a labeled example. They are separate from the observed register figures below. Workflow events are local trace records. A timestamp records when a row was written. Self-reported handling minutes, when a person entered them on a decision, are a separate observed figure. Self-reported rework minutes are another observed figure on that decision. Self-reported manual touches are another observed figure on that decision. Self-reported handoffs are another observed figure on that decision. None of them is copied into this formula. Do not present the modeled values as measured results, as cash savings, or as evidence of risk reduction.

## Observed measurements

Definition version 5 lives in `app/services/workflow_metrics.py`. The dashboard and the methods page render its result. An empty register shows zeros.

| Figure | Source | Reading |
| --- | --- | --- |
| Assessment volume | `risks` rows | Saved assessments. An unsaved public try is absent. A `scenario_id` beginning with `intake-`, or stored `intake_origin` of `general_intake`, is general intake. Every other row is a scenario fixture. |
| Open remediation | `remediation_actions` | Actions whose status is not `completed`. `in_progress` stays in the open count. |
| Residual tiers | `risks.residual_tier` | One tier per saved assessment. The stored column is the source, including `undetermined`. |
| Claim evidence statuses | `rationale_json` claims | One status per stored claim. Missing evidence is a gap. It is not counted as a confirmed control failure. |
| Clause evidence statuses | stored required contract clauses | Counted in a separate list from claims. |
| Persisted dispositions | current `decisions` row | approve, approve with conditions, escalate, or reject. A replacement updates that row. |
| Decision events | `workflow_events` of type `decision_recorded` | The log can contain more than one event after a replacement. That count is shown beside the current-row count when the two differ. |
| Intake-to-disposition cycle time | earliest `intake_received` to earliest `decision_recorded` on the same risk | Elapsed clock time. A shared timestamp is 0 elapsed seconds. Scenario rows have no `intake_received` event and stay out of the series. A row with no disposition event has no cycle time. A reversed pair, an unreadable timestamp, or a naive timestamp mixed with an offset-aware timestamp stays out of the average. |
| Self-reported human handling time | `decisions.handling_minutes` on the current row | Optional whole minutes a person entered with the disposition. Null stays out of the median and the mean. The headline figure is the median. For an even count, the median is the mean of the two middle values. The mean is rounded half up to two decimal places. Zero is a reported zero. When no row has a number, the panel says the figure is not measured. |
| Self-reported rework time | `decisions.rework_minutes` on the current row | Optional whole minutes a person entered for time spent redoing work after a first pass. The median rules match handling minutes, and null stays out. Zero is a reported zero. When no row has a number, the panel says the figure is not measured. This is not handling time, not elapsed cycle time, and not an input to the formula. |
| Self-reported manual touches | `decisions.manual_touches` on the current row | Optional whole-number count of human touchpoints a person entered with the disposition. The median rules match handling minutes, and null stays out. Zero is a reported zero. When no row has a number, the panel says the figure is not measured. This is not handling time, not rework time, not elapsed cycle time, and not an input to the formula. |
| Self-reported handoffs | `decisions.handoffs` on the current row | Optional whole-number count of times the assessment was handed between people or queues before disposition. The median rules match handling minutes, and null stays out. Zero is a reported zero. When no row has a number, the panel says the figure is not measured. This is not handling time, not rework time, not manual touches, not elapsed cycle time, and not an input to the formula. |

The mean of the measured spans is rounded half up to two decimal places. The minimum, maximum, and total stay exact. For an even count, the median is the mean of the two middle spans.

A same-transaction save can write `intake_received` and `decision_recorded` with the same timestamp. The resulting 0 elapsed seconds is the clock record of that write. It is a measured elapsed span. It is not the self-reported handling minutes on that decision, it is not the self-reported rework minutes, it is not the self-reported manual-touch count, and it is not the self-reported handoff count. Those fields are unmeasured when left blank.

## Why the observed series stays out of the formula

| Observed series | What would have to be true before it could feed the formula | What this version does |
| --- | --- | --- |
| Assessment volume | The count would have to be one reporting month, with scenario fixtures and repeat saves removed. The register does not store a reporting month. | The count stays on the observed panel. `assessments_per_month` remains 20 in `cost_assumptions.json`. |
| Elapsed cycle time | The span would have to be labor hours, split into a baseline and an assisted handling time. The events store two write times. They do not store either handling time. | The span stays on the observed panel. Baseline hours remain 2.0 and assisted hours remain 1.5. |
| Self-reported handling minutes | The minutes would have to be authenticated labor hours, split into a baseline and an assisted handling time, and tied to one reporting month. They are an optional number on a decision. | The median stays on the observed panel. Baseline hours remain 2.0 and assisted hours remain 1.5. |
| Self-reported rework minutes | The minutes would have to be authenticated rework hours, separate from handling time, and tied to one reporting month. They are an optional number on a decision. | The median stays on its own observed card. It is not copied into baseline hours, assisted hours, review hours, or maintenance hours. |
| Self-reported manual touches | The count would have to be authenticated labor, separate from handling time and rework time, and tied to one reporting month. It is an optional number on a decision. | The median stays on its own observed card. It is not copied into baseline hours, assisted hours, review hours, or maintenance hours. |
| Self-reported handoffs | The count would have to be authenticated labor, separate from handling time, rework time, and manual touches, and tied to one reporting month. It is an optional number on a decision. | The median stays on its own observed card. It is not copied into baseline hours, assisted hours, review hours, or maintenance hours. |
| Open remediation, evidence status, residual tier, dispositions | These are inventory counts. The formula takes hours and a labor rate. | They stay on the observed panel. |

No second dollar figure is calculated from the register. Cash savings stay unmeasured. Hypothetical avoided incidents stay unmonetized. One-time development cost stays excluded.

## Still unmeasured

- Authenticated effort tracking. The optional minutes, the optional touch count, and the optional handoff count are whatever the person typed. There is no identity check and no timesheet.
- A monthly assessment rate
- Cash savings
- Avoided-incident value

The local event log can be edited. It is not a tamper-proof measurement store.

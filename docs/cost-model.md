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

The application currently has no observed baseline-versus-assisted timing study or intake-to-disposition measurement. Workflow events are local trace records, not human handling-time measurements. Do not present these modeled values as measured results or as evidence of risk reduction.

# Control Mapping Methodology

**Status:** Draft portfolio methodology, mapping set version 0.2.0

## Purpose and limits

The mapping library in `app/data/control_mappings.json` links explicitly tagged assessment claims to a small set of potentially relevant requirements. It is a review aid. A mapping does not establish that a vendor implemented a control, that evidence is sufficient, or that a vendor or organization conforms to a framework. No certification or equivalence claim is made.

ISO/IEC 27001 and ISO/IEC 42001 entries in this set are draft portfolio review prompts. A shared claim topic only chooses which prompts appear on an assessment. It does not make one framework's control the same requirement as another's, and it does not show that a control is implemented.

## Source and version

Mapping set 0.2.0 keeps the four NIST SP 800-53 entries from 0.1.0 and adds four ISO/IEC 27001:2022 Annex A controls and four ISO/IEC 42001:2023 Annex A controls. This repository stores only selected identifiers and short titles. It does not store control statements, annex guidance, or other standard body text. Sources are external and may change. Recheck them before presenting a mapping as reviewed.

### NIST SP 800-53

The NIST entries use Revision 5, Release 5.2.0. Identifiers and titles were checked against the NIST [SP 800-53 controls download catalog](https://csrc.nist.gov/Projects/risk-management/sp800-53-controls/downloads), which identifies the catalog as a derivative format of the authoritative SP 800-53 Rev. 5 publication. NIST notes that the normative publications take precedence if a derivative format differs. The NIST [SP 800-53 Rev. 5 publication page](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/Final) records the later Release 5.2.0 update.

### ISO/IEC 27001:2022

The free previews of [BS ISO/IEC 27001:2022](https://webstore.ansi.org/preview-pages/BSI/preview_30457406.pdf) and [DS/ISO/IEC 27001:2022](https://webstore.ansi.org/preview-pages/DS/preview_M364392CURES.pdf) name Annex A as "Information security controls reference" and do not list each control title.

The Annex A identifier and short title for each entry below were read from the [ANSI National Accreditation Board comparison](https://blog.ansi.org/anab/iso-iec-27001-2013-2022-comparison/) of ISO/IEC 27001:2013 and ISO/IEC 27001:2022. In that annex table, the 2022 control column and the 2022 title column give:

| 2022 control | 2022 title in the ANAB table |
| --- | --- |
| A.5.14 | Information transfer |
| A.5.15 | Access control |
| A.8.5 | Secure authentication |
| A.8.15 | Logging |

The same title words, at clause numbers without the `A.` prefix, appear in the contents pages of national adoptions of ISO/IEC 27002:2022: [BS EN ISO/IEC 27002:2022](https://webstore.ansi.org/preview-pages/BSI/preview_30465419.pdf) (5.14, 5.15, 8.5, 8.15) and the English contents of [DS/ISO/IEC 27002:2022](https://webstore.ansi.org/preview-pages/DS/preview_M362244CURES.pdf). That contents check corroborates the title words. It is not a statement that the two standards are equivalent.

### ISO/IEC 42001:2023

The [ISO preview of ISO/IEC 42001:2023](https://webstore.ansi.org/preview-pages/ISO/preview_ISO%2BIEC%2B42001-2023.pdf) identifies the document as the first edition, 2023-12, and names "Annex A (normative) Reference control objectives and controls". That preview contents page does not list each Annex A control title.

The four short titles stored here are the same string in all three of these public lists:

- [Sensiba, ISO/IEC 42001 readiness checklist](https://explore.sensiba.com/hubfs/White%20Papers/RAS%20WP/WP%20-%20RAS%20-%20ISO%2042001%20Readiness%20Guide.pdf) (printed as "Annex A 6.2.6" and so on)
- [Modulos, Annexes A–D](https://docs.modulos.ai/frameworks/iso-42001/annexes-a-d) (printed as `A.6.2.6` and so on)
- [OG Technologies, Annex A controls list](https://www.ogtechnologies.co/downloads/iso-42001-annex-a-controls.pdf)

| Identifier stored | Short title, agreed by those three lists |
| --- | --- |
| A.6.2.6 | AI system operation and monitoring |
| A.6.2.8 | AI system recording of event logs |
| A.7.2 | Data for development and enhancement of AI system |
| A.7.3 | Acquisition of data |

Other titles in those lists do not always match one another. Examples include A.6.1.3 and A.10.2. Those controls were left out. A reviewer who has a licensed copy of ISO/IEC 42001:2023 should confirm these four titles before changing an entry from draft. The titles were not copied from the ISO requirement text.

## Current mappings

| Framework/version | Control | Claim topic | Mapping intent | Review status |
| --- | --- | --- | --- | --- |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | AC-6 — Least Privilege | `integration_permissions` | Review whether integration permissions are limited to service needs. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | AU-2 — Event Logging | `audit_logging` | Ask what security-relevant events are logged and reviewable. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | IA-2 — Identification and Authentication (Organizational Users) | `authentication` | Review organizational-user authentication claims and evidence. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | SC-8 — Transmission Confidentiality and Integrity | `transmission_security` | Review safeguards for information in transit. | Draft |
| ISO/IEC 27001:2022 | A.5.15 — Access control | `integration_permissions` | Draft portfolio review prompt for whether access is limited to what the service needs. | Draft |
| ISO/IEC 27001:2022 | A.8.5 — Secure authentication | `authentication` | Draft portfolio review prompt for how organizational users authenticate to the service. | Draft |
| ISO/IEC 27001:2022 | A.5.14 — Information transfer | `transmission_security` | Draft portfolio review prompt for safeguards when information moves to, from, or through the service. | Draft |
| ISO/IEC 27001:2022 | A.8.15 — Logging | `audit_logging` | Draft portfolio review prompt for whether security-relevant activity is logged and reviewable. | Draft |
| ISO/IEC 42001:2023 | A.6.2.6 — AI system operation and monitoring | `audit_logging` | Draft portfolio review prompt to ask how an AI system is operated and monitored. The mapper does not read the AI-use answer. | Draft |
| ISO/IEC 42001:2023 | A.6.2.8 — AI system recording of event logs | `audit_logging` | Draft portfolio review prompt to ask what event logs an AI system keeps. The mapper does not read the AI-use answer. | Draft |
| ISO/IEC 42001:2023 | A.7.2 — Data for development and enhancement of AI system | `privacy` | Draft portfolio review prompt to ask whether customer data is used to develop or enhance an AI system. The mapper does not read the model-training answer. | Draft |
| ISO/IEC 42001:2023 | A.7.3 — Acquisition of data | `privacy` | Draft portfolio review prompt to ask how data for an AI system was acquired. | Draft |

`privacy` is an existing claim topic on the public intake. It is the tagged statement about collection, use, and retention of customer data. It is not one of the NIST topics. The two ISO/IEC 42001 data prompts use it because that is the tagged topic about how customer data is used. The privacy notice is not treated as implementation of those controls.

## Matching and traceability

Claims may include an explicit `topic`. `app/services/control_mapper.py` matches only exact topic values declared in the mapping data. Untagged or unmatched claims remain unmapped; the service does not infer a mapping from free-text claim wording, and it does not read assessment fields such as `ai_use` or `model_training_on_customer_data`. For matched claims, the result retains claim identifiers and evidence identifiers/statuses from the evidence validator. Mapping does not modify those evidence results.

Each mapping record includes the framework and version, identifier, title, applicability note, rationale, related claim topics, source reference, and review status. The mapping-set version is returned with each match so results can be tied to the data version.

`list_library` in `app/services/control_mapper.py` returns the full library, including the mapping-set version and source note, without matching claims and without changing review status. The Control mappings page at `/mappings` renders that result. Assessment and saved-risk pages render only the matched prompts, using the same field labels and the same stored review status. The templates do not add mappings and do not mark a draft entry as reviewed. Each card also shows a so-what sentence: what the control is asking the business to decide, and, on an assessment, the evidence status already stored on the related claim. That sentence does not change the review status, the evidence status, or the score.

An ISO/IEC 42001 logging prompt appears whenever a claim is tagged `audit_logging`, including when the intake says the service does not use AI. The applicability note says the reviewer decides whether the prompt applies. The same is true of the privacy prompts: they appear when a privacy claim is tagged, and they do not read the model-training answer.

## Review policy and limitations

All current mappings remain `draft`. Verifying an identifier and a short title does not validate the project's applicability judgment or rationale. A human reviewer should check the actual service context, claim wording, supporting evidence, and the applicable organizational control-selection method before changing a status to `reviewed`. If any reference, applicability decision, or rationale cannot be supported, keep it draft or mark it unverified.

The ISO/IEC 42001 titles above were not read from the ISO preview page. They stay draft until someone checks them against a licensed copy.

These controls were not added, because no current claim topic is an honest join and this library does not invent topics:

- ISO/IEC 42001 A.5.4, impact on individuals, and A.9.4, intended use. `decisions_affecting_people` is an intake field, not a claim topic.
- ISO/IEC 42001 A.10.3, suppliers. No claim is tagged for a supplier-control topic.
- Further ISO/IEC 27001 controls beyond the four above. One prompt per NIST topic is enough for this set.

`ai_use` and `model_training_on_customer_data` are assessment fields. They are not claim topics, so a mapping cannot join them without a new tagged claim. Adding that claim would change the evidence input to the risk engine, which this mapping change does not do.

A cross-framework join on a claim topic is not equivalence, complete conformity, or certification. This prototype does not certify a vendor or an organization against NIST SP 800-53, ISO/IEC 27001, or ISO/IEC 42001.

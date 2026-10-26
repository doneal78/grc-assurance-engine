# Control Mapping Methodology

**Status:** Draft portfolio methodology, mapping set version 0.1.0

## Purpose and limits

The mapping library in `app/data/control_mappings.json` links explicitly tagged assessment claims to a small set of potentially relevant requirements. It is a review aid. A mapping does not establish that a vendor implemented a control, that evidence is sufficient, or that a vendor or organization conforms to a framework. No certification or equivalence claim is made.

## Source and version

The initial catalog references use NIST SP 800-53, Revision 5, Release 5.2.0. Identifiers and titles were checked against the NIST [SP 800-53 controls download catalog](https://csrc.nist.gov/Projects/risk-management/sp800-53-controls/downloads), which identifies the catalog as a derivative format of the authoritative SP 800-53 Rev. 5 publication. NIST notes that the normative publications take precedence if a derivative format differs. The NIST [SP 800-53 Rev. 5 publication page](https://csrc.nist.gov/pubs/sp/800/53/r5/upd1/Final) records the later Release 5.2.0 update.

This repository stores only selected identifiers and titles needed for its synthetic demonstration; it does not redistribute the full catalog. Sources are external and may change. Recheck them before presenting mappings as reviewed.

## Current mappings

| Framework/version | Control | Claim topic | Mapping intent | Review status |
| --- | --- | --- | --- | --- |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | AC-6 — Least Privilege | `integration_permissions` | Review whether integration permissions are limited to service needs. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | AU-2 — Event Logging | `audit_logging` | Ask what security-relevant events are logged and reviewable. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | IA-2 — Identification and Authentication (Organizational Users) | `authentication` | Review organizational-user authentication claims and evidence. | Draft |
| NIST SP 800-53 Rev. 5, Release 5.2.0 | SC-8 — Transmission Confidentiality and Integrity | `transmission_security` | Review safeguards for information in transit. | Draft |

## Matching and traceability

Claims may include an explicit `topic`. `app/services/control_mapper.py` matches only exact topic values declared in the mapping data. Untagged or unmatched claims remain unmapped; the service does not infer a mapping from free-text claim wording. For matched claims, the result retains claim identifiers and evidence identifiers/statuses from the evidence validator. Mapping does not modify those evidence results.

Each mapping record includes the framework and version, identifier, title, applicability note, rationale, related claim topics, source reference, and review status. The mapping-set version is returned with each match so results can be tied to the data version.

`list_library` in `app/services/control_mapper.py` returns the full library, including the mapping-set version and source note, without matching claims and without changing review status. The Control mappings page at `/mappings` renders that result. Assessment and saved-risk pages render only the matched prompts, using the same field labels and the same stored review status. The templates do not add mappings and do not mark a draft entry as reviewed.

## Review policy and limitations

All current mappings remain `draft`. Verifying an identifier and title at NIST does not validate the project's applicability judgment or rationale. A human reviewer should check the actual service context, claim wording, supporting evidence, and the applicable organizational control-selection method before changing a status to `reviewed`. If any reference, applicability decision, or rationale cannot be supported, keep it draft or mark it unverified.

Only NIST SP 800-53 is included in this initial library. ISO/IEC 27001 and ISO/IEC 42001 mappings are not implemented. Extending the library requires authoritative source checks and separate mapping review; cross-framework similarity must not be presented as equivalence.

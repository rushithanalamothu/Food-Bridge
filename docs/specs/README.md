# Individual design specifications

[Donation Intake and Eligibility, v0.3 (PDF)](donation-intake-eligibility-v0.3.pdf) is Mani Mokshith Noonety's October 28, 2026 individual design specification. The PDF is preserved unchanged from the supplied original.

Use it as the intended requirements reference for the intake subsystem, including DI-01–DI-12, NFR-01–NFR-06 and UT/FT acceptance scenarios. Its presence does not mean every requirement is implemented. The current [intake implementation guide](../features/intake.md) describes delivered behavior; the [shared design](../design.md) defines cross-team integration boundaries.

[The alignment record](intake-v0.3-alignment.md) maps the PDF requirements to current code/tests, records explicit design amendments, and names remaining cross-team integration. Urgency, packaging, configurable review policy, retry and local observability are implemented; the full Orchestrator-to-Matching pipeline and production metrics aggregation remain pending. Do not infer those milestones from the intake worker demo.

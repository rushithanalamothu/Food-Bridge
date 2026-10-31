# Intake agent — Mokshith

Text-to-draft extraction, required-field review, urgency and deterministic eligibility.

Current status: queue entry point and diagnostic `foodbridge.intake.probe` only. No business workflow is implemented here yet.

- Input: Private draft text for extraction; donor-confirmed DonationInput + typed recipient/route facts for policy.
- Output: Proposed fields with missing/provenance metadata, or versioned eligibility decisions/reason codes. Never silently confirm an LLM guess.
- First task: Add proposal DTO + pure hard-policy tests, then implement repositories/task handlers against those contracts.

Consume only the `intake` queue. Register tasks as `foodbridge.intake.<verb>`. Use shared domain types and repositories; keep provider calls bounded and outside write transactions. See the repository design, events and team implementation plan under `docs/` before changing cross-agent interfaces.

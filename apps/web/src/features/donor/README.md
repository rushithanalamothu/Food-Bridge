# Donor workspace

The intake slice implements description → persisted proposal → correction/confirmation → submission, urgency and a clearly synthetic eligibility-worker demo. It uses generated intake types and typed API wrappers; it never fabricates matching/reservation success.

See the repository `docs/features/intake.md` for local identity setup and backend integration. Mithil owns further UI work; Mokshith owns extraction, confirmation and eligibility. Shared login, matching/SSE and profile selection remain integration work. API access tokens are accepted through the in-memory API wrapper, not persisted in browser storage.

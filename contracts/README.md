# Shared contracts

Source of truth: `backend/src/foodbridge/domain/contracts.py` and `domain/states.py`. Run `make contracts` from root to export `domain.schema.json`, the implemented `openapi.json`, and frontend `src/api/generated/domain.ts`. Never edit generated artifacts by hand.

`FoodBridgeContracts` is an export bundle, not a real HTTP request wrapper. Individual schemas are the wire models. Only the health API is currently mounted; planned business endpoints are in `docs/architecture/api.md` and gain generated OpenAPI when implemented. Valid examples are in `examples/`.

Schema changes need producer/consumer review and examples. CI checks drift from both Python and TypeScript generation. Optional/new fields are preferred over breaking renames; update versioning when a breaking change is unavoidable.

# Donation lifecycle and commands

The canonical enum and transition graph live in [states.py](../../backend/src/foodbridge/domain/states.py). The guard validates edges only; auth, versions, capacity, clock and food-handling checks also have to pass in the application transaction.

| Current state | Allowed next states | Trigger / owner |
| --- | --- | --- |
| `draft` | `submitted`, `cancelled` | Donor confirms or abandons draft |
| `submitted` | `needs_review`, `matching`, `expired`, `cancelled`, `failed` | Intake validation via orchestrator |
| `needs_review` | `submitted`, `expired`, `cancelled` | Donor corrects required fields |
| `matching` | `offered`, `no_match`, `expired`, `cancelled`, `failed` | Candidate/routing/ranking outcome |
| `offered` | `reserved`, `matching`, `expired`, `cancelled`, `failed` | Recipient accepts/declines, offer times out |
| `reserved` | `pickup_assigned`, `matching`, `expired`, `cancelled`, `failed` | Assignment or pre-pickup release |
| `pickup_assigned` | `picked_up`, `reserved`, `expired`, `cancelled`, `failed` | Driver confirms collection or assignment released |
| `picked_up` | `delivered`, `failed` | Driver confirms delivery or handling exception |
| `delivered`, `no_match`, `expired`, `cancelled`, `failed` | None | Terminal, immutable; no automatic reopening |

`draft` is used by the extraction/review aggregate; only donor-confirmed input becomes a posted donation. A posted donation starts at `submitted`. Keeping the initial edge in the shared vocabulary does not require unconfirmed food to be visible in the live donation board.

Match statuses: `offered`, `accepted`, `declined`, `expired`, `superseded`. Reservation statuses: `active`, `released`, `fulfilled`. Assignment statuses: `assigned`, `accepted`, `declined`, `released`, `collected`, `delivered`, `failed`. These additional lifecycle enums must be added to canonical contracts when their routes/tables are implemented.

## Re-matching and driver redispatch

Recipient decline, offer timeout or released reservation excludes that recipient from future rounds for the same donation. Increment `matching_round` atomically; old round results cannot win. Never re-offer endlessly: stop at configured rounds or last feasible safe time. Immediate exhaustion is `no_match`; reaching the time boundary is `expired`.

A driver decline is `pickup_assigned -> reserved`, then another assignment attempt. It does not erase recipient acceptance. If no driver can feasibly complete the trip, release reservation/capacity, exclude any now-infeasible recipient, and transition through `matching` or to a terminal state with a specific reason.

A worker/provider transient failure does not immediately mean `failed`. Keep persisted business state and record attempts on `workflow_steps`. After budget exhaustion choose an explicit outcome: `needs_review` for uncertain intake, `no_match` for genuinely exhausted feasible candidates, `expired` for time, or `failed` for unresolved technical/handling failure. Dead-lettering is an operational record, not permission to make unsafe transitions.

## Commands, not arbitrary status patches

Implement methods such as `confirm_details`, `accept_offer`, `decline_offer`, `assign_driver`, `confirm_pickup` and `confirm_delivery`. They derive destination status server-side, validate the old version and write the matching history/outbox atomically. Never expose `PATCH {status: "delivered"}`.

Every transition stores `actor_type`, actor ID where applicable, reason code, correlation ID and aggregate version. History supports audit, UI timelines and evaluation without treating agent log text as a database. Duplicate delivery confirmation returns the original idempotent response and records impact once.

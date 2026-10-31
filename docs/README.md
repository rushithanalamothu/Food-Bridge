# Team documentation

The [implemented Intake and Eligibility feature](features/intake.md) includes its local runbook and team handoff.

Read in this order:

1. [Local setup](setup.md): get a reproducible environment running.
2. [Design document](design.md): decisions, system boundaries and end-to-end behavior.
3. [Ownership](team/ownership.md): where each person works and who reviews shared changes.
4. [Implementation plan](team/implementation-plan.md): dependency order, first tasks and acceptance gates.
5. [HTTP contract](architecture/api.md), [events and recovery](architecture/events.md), [data model](architecture/data-model.md), [state machine](architecture/state-machine.md): exact integration rules.
6. [Testing and evaluation](testing.md), [deployment](deployment.md), [decision log](architecture/decisions.md).

The [UI prototype](design/ui/foodbridge.html) is visual reference only. Workbook diagrams and meeting notes provide context; this design and the canonical code contracts describe the implementation baseline. Proposed changes should update the decision log and affected contracts in the same PR.

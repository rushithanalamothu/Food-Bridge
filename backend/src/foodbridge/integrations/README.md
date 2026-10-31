# Provider adapters

`ports.py` starts the routing/notification interface boundary. Add extraction/ranking interfaces after their proposal/candidate contracts are reviewed. Routing and LLM adapters are owned by the corresponding intake/matching owner; notification adapters by Tej.

Each adapter needs a deterministic fake, bounded timeout, classified retry errors and provenance (provider/model/prompt version). It returns data; it cannot change workflow state, invent a feasible route, approve unknown allergens or override capacity/deadlines. Keep provider credentials in server environment only.

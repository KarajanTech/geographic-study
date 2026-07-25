# ADR 0001: Record architecture decisions

- Status: accepted
- Date: 2026-07-25
- Phase: 0

## Context

Sentinel Planner produces scientific results: coverage figures, selected tower
positions and cost estimates that clients will act on. Choices such as the
analysis CRS, the visibility model or the optimizer used are not implementation
details — they change the numbers. A reviewer must be able to find out _why_ a
number is what it is, months later.

## Decision

Every decision that affects results, data handling or system boundaries is
recorded as a short ADR in `docs/adr/NNNN-title.md`, numbered sequentially and
never rewritten: a superseded ADR gets a new one pointing back at it.

An ADR is required for:

- CRS selection rules and reprojection strategy;
- the surface model used for visibility (DEM, DSM, vegetation);
- viewshed algorithm and its parameters;
- optimizer choice and objective function;
- data storage and provenance rules;
- external service dependencies.

## Consequences

- Reviews discuss the decision, not only the diff.
- Roadmap phases inherit context instead of re-litigating it.
- A small ongoing writing cost, paid once per decision.

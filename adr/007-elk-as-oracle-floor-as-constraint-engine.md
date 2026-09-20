# ADR-007: ELK as layering oracle; the floor as the constraint engine

**Status:** Proposed (2026-09-20). Supersedes the *division of labor*
in ADR-006 Amendment 2 (ELK owns flow geometry; floor owns declared
arrangement) with a cleaner split; the ELK backend itself remains as
the zero-constraint fast path.

## Context

Two threads converge.

**The reviewer's strategic question:** for the agent-authored diagram
vision ("study the code, add a diagram, make the path preattentive"),
is it better to fix the floor's auto-layout — designing
positions-constrain-autolayout from the start — or to fix where ELK
doesn't serve us (label placement, preattentive placement), "fighting"
ELK where needed?

**The empirical survey (ADR-006 Amendment 2):** ELK Layered honors
ports, column seeds, and FIRST/LAST pins; it ignores IN_LAYER,
positionId, and model-order enforcement; same-layer against-flow
arrows are re-layered, never drawn; per-pair gaps and exact alignment
have no channel at all. The fight list is therefore a list of engine
forks, not configuration. The floor's defect list (anchor-face
scatter, corridor fill, label residuals) is *our* code.

**The reviewer's sharpening observation (comparison A/B, Worker tree):**
the ELK render reads tidy and hub-legible because every inter-column
edge exits the source's EAST face and enters the target's WEST face.
Measured on juju4 "Worker tree (controller)" through the backend:
17/17 inter-column edges exit EAST and enter WEST; 0 same-column
edges. All arrivals on one face, fan-ordered along it — a preattentive
grouping that makes hubs readable at a glance. Our floor's anchors
scatter across faces per edge (the "arrows start and end in funny
places" complaint). The same observation names the price: concentrating
edges on one face concentrates their labels into the corridor between
columns, which is where the overlap/graze tensions live (corridor
budget, LCLASH). Concentration is not the cause of those tensions —
it is what makes them *visible*; spreading anchors hides them by
scattering.

**The diagonal half-question** rides here: ELK's polyline routing
produces diagonals in non-orthogonal views. The route vocabulary
(ADR-003 amended 0.26.1) is straight/L/U with the audit gate counting
diagonals as defects. Whether a per-view "diagonal: allowed"
declaration should exist stays a reviewer's call (ADR-003 amendment
candidate); nothing in this ADR depends on it.

## Decision

**1. ELK is demoted to a layering oracle; the floor becomes the
constraint engine.**

For the strategic path, ELK's contribution shrinks to its two
strongest, most enforceable outputs — layer (column) assignment and
crossing-minimal intra-column ordering — delivered as *suggestions*.
Its coordinates and edge routes are discarded. Below the oracle line,
everything is ours:

- **Coordinates**: kiwisolver solves column x-positions and
  within-column y-positions from (a) the oracle's ordering as the
  base, (b) every declared arrangement constraint as additional
  solver terms.
- **Routes**: the floor's router (ADR-003 vocabulary) with the port
  discipline below.
- **Labels**: the ADR-002 machinery, unchanged.

This dissolves the fight by construction: we stop asking ELK for
everything it cannot give. Align, fan, gaps, same-column arrows,
emphasis placement — all live below the oracle line, where cascades
are kiwisolver's native job.

**2. Positions become refinement, not a mode.**

The dispatch rule ("declared positions → floor, no positions → ELK")
fades into one path: synthesis is the default; every declared
constraint enters the same solve as additional kiwisolver terms over
the synthesized base. A view declares as much or as little
arrangement as it needs. The degradation ladder collapses to "how
many constraints did the author declare."

**3. Port discipline is a first-class floor rule** (from the reviewer's
observation):

- inter-column edges bind source EAST, target WEST;
- intra-column edges bind NORTH/SOUTH (the fan above/below case);
- ports along a face are ordered to minimize crossings
  (barycentric order of the far endpoint), which is what produces the
  hub fan the ELK render shows;
- label budgets and the corridor machinery absorb the concentration
  (the known accepted tension: corridors fill; edges overlap, never
  bend to hide it — ADR-003).

**4. The ELK backend (ADR-006) stays as the zero-constraint fast
path** — today's 8/11 flat views keep serving exactly as now. The
oracle mode is additive: same ELK run, different consumption of its
output. View curation (`except:`) applies to every consumer of the
model edge list (fixed 2026-09-20, parser + elk).

## Consequences

- **Work items, in order:** (1) anchor-face/ port discipline in the
  floor router (kills the "funny places" complaint; measured bar: all
  inter-column edges EAST→WEST, face-ordered, on the juju4 corpus);
  (2) the oracle path in `solve()` — ELK columns in, constraint solve
  out, floor routes out; (3) label-placement iteration on top
  (transfers regardless of backend); (4) salience/emphasis vocabulary
  (SPEC item) once placement is controllable enough to honor it.
- **Acceptance bar unchanged**: audit-geometry on the corpus
  (crossing-edges 0, node-strikes 0, ≤2 bends, ratio ≤2), plus new
  port-discipline assertions in the corpus tests.
- **Determinism**: ELK's layering is deterministic (pinned by
  test_elk_determinism); kiwisolver is deterministic given the same
  term order; byte-stability remains testable.
- **Risks**: the floor's coordinate quality must reach the ELK
  render's tidiness — the oracle ordering plus kiwisolver refinement
  starts from ELK's own structure, so the gap is bounded; corridor
  fill stays the honest accepted tension; label concentration on
  shared faces is watched through LCLASH metrics, not by scattering
  anchors again.
- **Not in scope**: bringing container views to ELK (ADR-006 v2);
  the diagonal per-view declaration (ADR-003 amendment candidate).

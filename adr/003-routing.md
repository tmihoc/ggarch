# ADR-003: Obstacle-aware routing over strips

**Date:** 2026-09-18  
**Status:** Proposed — for discussion (implementation is 0.26.0 once
decided; nothing in this ADR is implemented yet)

## Context

The router is obstacle-blind: every route is derived from the two
endpoint rects alone (straight face-to-face for horizontal-dominant
edges, L-shaped for vertical, face spreading to de-clutter shared
faces). The measured consequences (0.25.2-0.25.4 audits, both twins):

- **Arrows over boxes** — the headline review defect ("fix ASAP"):
  juju3 15 crossing-edges, juju4 35 (the 0.25.4 gap-floor shrinkage
  tightened the auto-layout twin from 31). The HA Raft mesh's long
  arrows cross the middle controller's children in both twins; fan
  edges cross stacked column-mates; the controller worker tree's
  leader-lease edge plows through its own column-mates.
- **Border notches without port semantics** — `_compute_border_gaps`
  (renderer.py:279) notches a container border for ANY edge segment
  crossing it, with no ancestry check: an edge passing OVER the Charm
  container cuts notches into its border ("Charm box has its edge
  interrupted"). A notch is being drawn where no port exists.
- **Coincident anti-parallel strokes** — pairs sharing an endpoint
  pair overlap on one stroke; their labels are anchored at ⅓/⅔ of the
  span purely to keep the two texts apart (a workaround, 0.25.4).
- **Diagonals on horizontal planes** (juju3 11 / juju4 22): edges
  render face-centre to face-centre, so any vertical centre offset
  becomes a diagonal — including planes the author laid out flat.

The user's review framing, which this ADR answers:

1. Routing style is a **global** decision: curved vs L-shaped vs
   diagonal must be decided once, not per diagram.
2. **Minimize arrow length** — shorter arrows read faster.
3. L's tidiness **must not override meaning**: an L imposes two
   turns the model did not declare; the diagonal is content
   ("meaning lives in the diagonal"; "all roads lead to x" — hub
   structure — must stay preattentive).
4. **No Structurizr-style box explosion** — routing must not
   re-arrange or inflate the drawing to make room for paths.
5. State-view transition labels (horizontal with opaque masks, not
   along the curve) are the **same decision** — do not fix in
   isolation.

## Decision

**Routes are obstacle-aware shortest paths over strips, found by
search, not derived from endpoint geometry.** Specifically:

1. **Shortest path over a Hanan grid, diagonals allowed.** Candidate
   bend points come from the endpoint coordinates and the obstacle
   rect coordinates (Hanan grid); the search is A* with 8-neighbour
   moves, so a path bends only to clear an obstacle. This is the
   libavoid-free v1 the 0.25.2 plan already scoped. Diagonal edges
   are the default and survive routing (see 4).
2. **The collision currency is the strip: path + label extent.**
   Every edge occupies a swept corridor — stroke width, arrowhead,
   and the one-sided ADR-002 label extent (text above the line). A
   route is collision-free only if its whole strip clears every
   obstacle: node rects, annotation boxes and regions, container
   walls, and other edges' strips. Labels never strike; routing
   never has to be re-done for labelling.
3. **Cost = length + turn penalty.** The search minimizes path
   length plus a per-turn constant. This answers "minimize arrow
   length" directly while leaving diagonals cheaper than their
   L-equivalents (a diagonal is shorter AND has fewer turns). The
   turn constant is the one tuning knob; it should start high enough
   that a path only bends to clear an obstacle.
4. **Diagonal-preserving; L-shaped stays opt-in.** The directness of
   a connection is meaning: consumer→provider adjacency, hub
   reach, fan structure. The router must not flatten that into
   orthogonal tidiness. Declared orthogonal routing (the existing
   "straight by default, orthogonal opt-in" decision) becomes a
   4-neighbour search with the same strip currency — one mechanism,
   two axis vocabularies.
5. **No box explosion.** The router treats the solved arrangement as
   fixed input (position is content): it never moves nodes, never
   inflates containers, never inserts gap floors to make room. When
   no collision-free path exists, the router returns the
   cheapest-collision path and reports it to the solver's label
   contract, which may reserve clearance and re-solve — the
   arrangement yields only through the solver, under the user's
   constraints, never through the router.
6. **Anti-parallel and mesh edges route at distinct offsets.** Edges
   sharing an endpoint pair (or a face) get separate corridors —
   this extends today's face spreading into the search. The ⅓-⅔
   label anchors become redundant and are removed: each label rides
   its own stroke.
7. **Rounded joins are a later aesthetic pass.** The path is found
   and stored as polylines (strips are rectangular); corner rounding
   is a renderer-side post-process that does not participate in the
   search. Deferred until the router is proven on the corpus.
8. **State-view transition labels adopt along-path textPath under
   this decision.** Transition curves become routed strips like any
   edge (back-edge bows outside the machine are the same
   corridor-around-obstacle problem); labels ride the curve per
   ADR-002 and the opaque background masks die. One label mechanism
   across all three view kinds — decided globally, as reviewed.
9. **Port semantics for border notches.** `_compute_border_gaps`
   notches a container border only when **exactly one endpoint of
   the edge is inside that subtree** — the notch then reads as a
   port (the edge genuinely enters or exits there). Edges passing
   over a container (both endpoints outside) leave the border solid;
   their crossing is a routing defect for 1-6 to eliminate, not a
   border feature. Edges internal to the subtree do not notch
   their own container.

## Reasoning

**Why shortest-path search over strips rather than smarter
endpoint-derived routes?** Every current defect class comes from
routing in ignorance of everything but the two endpoints. Adding
obstacle awareness piecemeal (mid-y flattening here, detours there)
reproduces the placement-branch proliferation ADR-002 abolished for
labels. One search with one collision currency — the strip, which
ADR-002 already made uniform — handles crossings, coincident pairs,
label strikes, and state-view bows as the same problem: a strip
intersecting an obstacle.

**Why preserve diagonals?** The review's own principle: meaning lives
in the diagonal. A hub whose spokes all reach directly reads
preattentively ("all roads lead to x"); the same spokes bent into
Ls read as a maze — tidiness overrides meaning. Diagonals are also
the shortest paths, so cost = length + turns keeps them by default
without special-casing.

**Why length + turns and not length alone?** Pure length prefers
staircase paths that graze obstacle corners. The turn penalty makes
the search pay for each bend, so paths are straight where possible
and bend only to clear geometry — the visual convention the review
asked for (minimal arrows, minimal kinks).

**Why no box explosion?** Structurizr's router makes room by inflating
boxes and gaps until every edge is a tidy orthogonal; the result
teleports authoring intent (position is content — the model's spatial
argument is the diagram). ggarch's division of labor: the router
finds the honest best path through the given arrangement; the solver
(under user constraints, via the existing reservation machinery) is
the only thing that changes arrangement.

**Why fold state-view labels in?** Their masks exist because labels
float free of their curves; once labels ride paths (ADR-002) and
paths are routed strips (this ADR), masks solve a problem that no
longer exists. Deciding per-view would leave two label mechanisms
and mask machinery alive — the exact mode-duality ADR-002 removed.

**Why fix border notches here?** Notch semantics are port semantics,
and ports only make sense relative to routed paths: once routes are
obstacle-aware, an edge crossing a container it does not enter is a
router bug to eliminate; the border renderer must not paper over it
by notching. Fixing the ancestry check alone today (without the
router) would leave pass-over arrows visually un-notched but still
crossing — cosmetic honesty that hides the defect. Landing it with
the router makes the notch an honest signal.

## Consequences

**Easier:**
- One collision currency (strip) across router, solver reservations,
  audit, and all three view kinds' labels.
- Crossing-edges and label-clash metrics become router-owned and
  measurable against an acceptance bar, not hand-compensated by
  authored positions.
- Anti-parallel pairs separate; ⅓-⅔ anchor workaround is deleted.
- State-view masks die; one label mechanism everywhere.
- The audit harness (segment-vs-rect, label-strike tests) already
  measures everything the acceptance bar needs.

**Harder:**
- A* over a Hanan grid of every-rect coordinates per view: needs
  measurement on the corpus (22 views; the largest has ~17 edges and
  ~40 nodes) before committing to the grid density and the turn
  constant. Risk: grid degeneracy in tightly packed containers.
- Pairwise strip-vs-strip collision makes the search order-dependent
  for meshes (route A's offset constrains route B); v1 routes pairs
  and fan-groups greedily after independent edges.
- "Cheapest collision" paths must degrade gracefully: a crossing
  should remain visible in the audit rather than being silently
  accepted.
- Sequences keep their own row-router — out of scope by acceptance
  (byte-identical), but the strip concept should stay compatible.

**Acceptance bar (from the 0.26 plan):** crossing-edges near zero in
both twins, annotation boxes counting as obstacles; sequences
byte-identical; rotated-label and label-clash counts no worse than
the 0.25.5 baseline; strips clear all obstacles in the audit.

## Open questions for discussion

1. **Turn constant and grid density** — start values and whether the
   turn penalty should scale with edge length (long edges afford more
   turns without looking kinked).
2. **Crossing over annotation boxes** — the plan counts them as
   obstacles (annotation boxes are content). Confirm: no edge may
   pass through a region even when the region is visually "empty".
3. **Degenerate cases** — when the cheapest path still collides
   (locked authored layouts, REQUIRED constraints), is the residual
   crossing acceptable, or does the router fail the build? Proposal:
   acceptable + audited, never silent.
4. **Anchor faces** — does the search also choose exit/entry faces
   (replacing `_best_anchors`), or do today's closest-opposing-face
   anchors seed the grid? Proposal: let the search choose; anchors
   become grid candidates.
5. **Rounded joins** — confirmed as a post-pass, or dropped entirely?
   Proposal: post-pass, scheduled only after the acceptance bar
   passes on the corpus.

# ADR-006: ELK Layered as the synthesized-layout backend

**Date:** 2026-09-19
**Status:** Accepted — spike proven; integration next

## Context

The edge-aware floor (5e1b5f7 + the Sugiyama heuristics 7006682/d619b22)
reached dagre-grade quality, and the review still found arrow defects:
corner-hugging entries, in-layer edges without port discipline, legs
grazing box edge lines. Three measured experiments on anchor aesthetics
(corner guard ×2, port pricing) each regressed the corpus. The pattern:
we were re-deriving, one experiment at a time, problems the layered-
layout world solved years ago — in-layer edge distribution, port
placement, orthogonal channel routing, coordinate assignment.

The user asked the build-vs-buy question directly: "isn't there an
implementation we can borrow wholesale?" and surfaced ELK Layered.

## Decision

**Adopt ELK Layered (via elkjs) as the layout backend for views with no
declared positions**, behind the existing synthesizer boundary.

- **What ELK replaces:** the synthesizer's layering, ordering,
  coordinate assignment, and — for views routed orthogonally — the edge
  routes themselves (ELK's orthogonal router with its spacing model).
- **What stays ours:** the grammar and shared model; position-is-content
  (ELK fires only when the view declares no positions — authored views
  never call it); the route vocabulary for non-orthogonal views; edge
  type grammar and semantic styling (ADR-004); the along-path label
  contract (ADR-002) running on ELK's polylines; the renderer; the
  audit gate.
- **Uniform leaf sizing stays** (the floor's contribution): ELK packs
  nodes with their content sizes, which leaves ragged columns — uniform
  sizing restores the aligned-column look before ELK runs.

## Spike evidence (Worker tree (controller), 15 nodes / 17 edges)

ELK Layered (direction RIGHT, orthogonal routing, Brandes-Köpf node
placement, 60/80/30 spacing), 0.4s per view under node:

- Rows snap to a grid: every node y ∈ {12, 132, 252, 372, 492} (120px
  rows).
- Every adjacent-rank edge is a straight horizontal: `http_server →
  api_server [(181,282),(309,282)]`, `undertaker → domain_services
  [(437,522),(517,522)]`.
- Port distribution on shared faces: DB accessor's three incoming
  arrows at y = 377/392/407 — evenly spaced, ordered by source.
- Corridor jogs for multi-rank edges: `domain_services → db_accessor
  [(693,517),(908,517),(908,407),(978,407)]` — one clean L, no box-edge
  grazing, no corner clipping.

Ragged columns in the raw spike (x varies with node width) are the
missing uniform sizing — the floor already implements it.

## Integration design

1. `ggarch/elk.py`: materialize the view (existing instance expansion +
   view selection) → uniform min-sizes → ELK JSON → one `node`
   subprocess (batched: all ELK views per build in one process) →
   positions + edge sections back.
2. `solve()`: when the view declares no positions and the ELK runtime
   is available, use the ELK backend; otherwise the built-in
   synthesizer (fallback = no new hard dependency).
3. `route()`: for ELK views, wrap ELK's edge sections as `RoutedEdge`
   (strips via `strip_for_edge` so the label contract and audit keep
   working); the built-in router serves everything else.
4. Node dependency: the juju docs toolchain already carries node
   (pa11y); ggarch's own test suite gates ELK tests on node
   availability (skipped when absent).

## Risks and mitigations

- **Determinism**: ELK Layered is deterministic for a fixed graph +
  options; verified by double-run in the spike (byte-identical JSON).
  The audit re-checks on every corpus run.
- **Latency**: ~0.4s/view standalone; batching keeps a 22-view build
  well under 10s. Test suite impact measured before merge; caching by
  graph hash if needed.
- **Route vocabulary drift**: ELK's orthogonal routes may bend more
  than our two-bend vocabulary. Accepted: the bends are ELK's tuned
  corridor routing, audited by the same gate. The vocabulary remains
  canonical for authored and non-orthogonal views.
- **Our hand-rolled synthesizer stays** as the node-less fallback —
  the floor's work is not discarded; it becomes the portable path.

## What this does not change

ADR-002 (labels), ADR-003 (route vocabulary for authored/diagonal
views), ADR-004 (edge channel grammar), ADR-005 (provenance),
position-is-content, the audit gate. ELK is a backend behind
`solve()`, not a new architecture.

## Amendment (same day, review round): labels decide the integration shape

Review round with both pipelines rendered side by side (spike preview vs
the floor's current state) changed the integration detail:

- **ELK's layering/ordering is acceptable as-is.** The reviewer judged
  its row assignment "a reasonable option" (lease manager on the top
  rank with primary election, its feeder, is a legitimate reading). We
  do NOT need to import our row preferences.
- **The label overlap the reviewer found between columns is a spacing
  option, not a defect**: `elk.spacing.edgeNode = 48` (+
  `edgeEdgeBetweenLayers = 40`) gives parallel routes enough room for
  the 9px along-path labels — verified on the same view; labels render
  horizontal on horizontal routes, riding vertical jogs rotated (the
  ADR-002 layered-reading accepted tension, ~2-3 per view).
- **Our label system is the keep-side of the integration**: the
  ecosystem's static-label standard is background masks over edges
  (banned here — ADR-002: the stroke is content; dash rhythm is
  semantic). ggarch's contribution to an ELK-backed pipeline is exactly
  the mask-free along-path label contract plus the semantic channel
  grammar.
- The hand-rolled floor remains the node-less fallback and the
  canonical router for authored/diagonal views. The corner-anchor
  discipline was reverted after a third measured regression on authored
  views (1.91 -> 1.95, >1.5x 4 -> 8) — ELK supersedes the orthogonal
  synthesis path it would have served.

## Amendment 2 (2026-09-20) — the verified constraint surface

Before committing to the backend, the pre-layout constraint channels
were probed empirically against both the pinned elkjs 0.8.2 bundle and
npm-latest 0.12.0 (tiny discriminating graphs through the runner):

| Channel | Status | Evidence |
|---|---|---|
| `elk.portConstraints` FIXED_SIDE + `elk.port.side` | **honored** (0.8.2) | ELK moved a node right of its target to face a WEST port |
| `elk.layered.layering.layerConstraint` FIRST/LAST | honored (0.12) | node pinned to outermost layer |
| `IN_LAYER` + `layerId` (pin to exact column) | **ignored, both versions** | enum absent from compiled JS; output equals natural layering |
| `crossingMinimization.positionId` + `positionChoiceConstraint` | **ignored, both versions** | order identical with and without |
| `semiInteractive` seeded in-layer order | **not enforced** | crossing-minimal order won over seeds |
| `considerModelOrder` PREFER_NODES + cm NONE + greedySwitch OFF | **not enforced** (contradicts the ELK 0.8.x blog) | crossing-minimal order won; also mutually exclusive with INTERACTIVE seeding (kills seed layering) |
| INTERACTIVE seeds for column assignment | honored **only** in the plain stack (cycleBreaking+layering INTERACTIVE, semiInteractive, default cm) | probe: 4 seeded columns held |
| Same-layer edges (in-column arrows against flow) | **outside the paradigm** | ELK re-layers the target instead of drawing the connector |
| Per-pair gaps / exact alignment | **not supported** | spacing options are graph-global; no per-node alignment constraint in JS builds |

Consequence (the split of labor this ADR now records):

- **ELK owns**: column assignment along the flow, ordering within
  columns (crossing-driven), edge routes, anchor faces (FIXED_SIDE
  upgrades from our port inference when needed), global spacing.
- **The floor owns**: every declared-arrangement statement — same-plan
  grouping, fan above/below (against-flow in-column arrows), exact
  alignment, per-pair gaps. A view whose arrangement is content
  declares positions and never reaches the backend (existing dispatch
  rule, now the formal boundary).
- View curation (`except:`) is applied to the backend's input graph,
  not just the render — layout must never see curated-out edges
  (fixed 2026-09-20; was silently layering around them).

## Amendment (2026-09-21): the fast path is retired — explicit oracle only

The floor's typed hub planes are synthesis machinery an ELK build
cannot express (the synthesizer emits its own FanConstraints; a
zero-constraint view is no longer "views the floor can't serve"). The
auto-selection in solve() (env-gated) is retired: solve() is
floor-only by construction — "no ELK dependence" holds without
configuration. ELK remains the on-demand ORACLE (ADR-007's role):
ggarch.elk.solve_view() and scripts/elk-compare.py run a parallel ELK
build explicitly, floor | ELK side by side per view.

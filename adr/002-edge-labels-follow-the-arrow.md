# ADR-002: Edge labels follow the arrow

**Date:** 2026-09-18  
**Status:** Accepted — implemented in 0.25.4

## Context

Edge labels were rendered by interrupting the arrow (gap mode): the
path split into two segments with the label in the on-axis gap, falling
back to floating beside the arrow (offset mode) when the segment could
not fit label + 2×16px tails. The 0.25.2 geometry audit measured the
fallout: per-edge coin flips between the two modes (11 offset labels in
the auto-layout twin, 9 in the authored twin), and the 0.25.3 label
contract had to be built just to keep gap mode reachable.

The deeper problem: gap mode assumes the line is not content — that it
is a mere connector, safe to cut. That is true in Structurizr, the
convention's origin, which deliberately has one edge type. It is false
in ggarch: strokes are typed (solid = synchronous, 6,3 = async/stream,
2,2 = ipc) and custom edge styles are first-class since 0.24.0. Cutting
the stroke:

- breaks dash rhythm *objectively* — SVG restarts the dash phase at each
  sub-path, so a 6,3 pattern resumes at phase 0 after the gap;
- privileges the least meaningful stroke (solid survives interruption
  best; 2,2 on a short arrow leaves unreadable stubs);
- gets worse with every new edge style, since each must answer "does
  this still read as a line when cut?"

Meanwhile, labels were forced horizontal, which forced three placements
by geometry (underline / signpost / midpoint-float) and would force a
fourth (horizontal text near a curved arc — ambiguous association) once
mesh-aware routing lands.

## Decision

**Labels render along their arrow's path, above the line, never
splitting it.** Specifically:

1. **Along-path (SVG textPath).** The text follows the path's geometry —
   straight, vertical, or curved — anchored on the longest leg. This is
   the street-map convention: text follows the road.
2. **Above the line, one-sided.** Text sits on one side of the stroke
   only (its above, in the text's local reading frame), with padding
   below (clearance to the stroke) and on the sides (clearance from the
   endpoint boxes and their arrowheads). The stroke stays fully visible:
   **no background mask, no fill** — zero occlusion by construction.
3. **Never upside-down.** Rotation is clamped to ≤90°; paths that run
   right-to-left get mirrored text so it always reads left-to-right or
   top-to-bottom.
4. **No gap mode.** The stroke is never interrupted. The gap/offset mode
   duality is abolished — there is one placement mechanism.
5. **Wrap to the leg.** Text wraps to the longest leg minus side
   padding. When a single word still cannot fit, the solver reserves
   clearance (see below) rather than degrading the placement.
6. **Reading model: layered.** Shapes/colours carry the first read,
   captions (set larger) carry the narrative, arrow labels are the
   detail layer consulted on examination. Rotated text is an acceptable
   cost in the detail layer because association is guaranteed by
   construction — the text lies along its arrow.

**Orientation policy (same decision, other face):** on a page, text is
horizontal, so horizontal flow maximises legibility. The auto-layout
floor is built axis-symmetric and horizontal (LR) by default;
`orientation: tb` is a declared, whole-view axis swap. Automatic
re-orientation is staged behind a real case, with the rotated-label
count per view (added to the geometry audit harness) as the trigger
metric — a TB-flow diagram rendered LR shows rotated text everywhere,
so misorientation becomes visible and measurable.

## Reasoning

**Why along-path rather than always-horizontal with a mask?**
Always-horizontal needs a placement branch per geometry (on-line for
horizontal arrows, across-line for vertical, floating for diagonal,
ambiguous near curves) and a masking mechanism to protect stroke
legibility under on-line text. Along-path needs one mechanism that
handles every geometry identically via textPath, with zero occlusion
(beside the stroke, not on it). One rule instead of three placements —
and it is the placement that keeps label–arrow association strongest.
The horizontal-text readability cost is consciously accepted under the
layered reading model.

**Why not gap mode (the incumbent)?** Named above: it cuts content,
privileges solid strokes, degrades with custom styles, and generated a
measured mode-duality defect class. Structurizr's precedent does not
transfer: one edge type there, a typed stroke grammar here. "Technically
true is the only kind of true" applies to rendering: a style that stops
reading as itself when labelled is a distortion.

**Why no mask?** A mask exists to solve occlusion; above-line placement
has no occlusion. Dropping it removes machinery (halo rendering, mask
colour coupling to light/dark themes and tinted container fills) and
keeps the stroke fully visible. The sequence renderer's above-line
convention is thereby unified with topology labels.

**Why is the solver contract retained?** The 0.25.3 two-phase machinery
(measure rendered geometry → reserve → re-solve, required constraints
outranking reservations) survives; only its policy changes. Labels no
longer need on-axis room, so reservations become rarer and smaller — the
contract repurposes to **strike avoidance**: when a wrapped along-path
label's extent would strike a node, container wall, or another label,
reserve the clearance. The HA anti-parallel pairs (coincident strokes
today) become visible under any label policy and are thereby recorded
as router work: separate the strokes, anchor paired labels at ⅓ and ⅔
of the span.

## Consequences

**Easier:**
- Dash rhythm and every edge style stay legible under labelling; the
  "does this style survive being cut?" question never has to be asked
  again.
- One label mechanism (no mode branches, no mask), one rendering path
  for straight/vertical/curved.
- Edge + label is a one-sided strip (path + text extent above it) — a
  uniform collision currency for the auto-layout floor (step 2) and the
  obstacle-aware router (step 3).
- On-axis label reservations largely relax; layouts regain the space
  0.25.3 spent widening gaps.
- The wrap budget grows (leg minus side padding, not minus 2×16px
  tails): shorter arrows get fewer lines.
- Rotation count becomes a measurable orientation metric, making
  auto-flip a principled future decision instead of a heuristic.

**Harder:**
- textPath wrapping must be computed by the renderer (no automatic
  multi-line textPath): estimate per-line leg capacity with the
  character-width model, emit one textPath element per line, stacked
  outward from the stroke.
- Side padding must clear endpoint boxes and arrowheads; strike checks
  must account for the one-sided extent, including against the source's
  own container wall for edges that exit containers.
- Vertical arrows carry rotated text (accepted under layered reading).

**Supersedes:**
- The HANDOFF key decision "Edge label placement: labelled arrows split
  the path into two segments with a gap at the midpoint" (gap mode).
- The 0.25.3 gap-mode label contract's *policy* (gap guarantee); its
  machinery is repurposed to strike avoidance in 0.25.4. Until 0.25.4
  lands, gap mode remains the implemented behaviour.

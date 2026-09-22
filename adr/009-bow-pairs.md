# ADR-009: Bow pairs — curved anti-parallel corridor strokes

Date: 2026-09-22. Status: accepted.

## Context

The route vocabulary was straight → L → U, axis-aligned only (ADR-003).
Two anti-parallel edges sharing a corridor — the "back and forth"
between two entities — drew as near-coincident parallel strokes with
both labels anchored at their own midpoints: the strokes and the
labels overprinted (measured: the Machine designations pair anchored
at midpoint+0 and midpoint+8..12 on the same faces, 4px apart; the
principles chain pairs clashed the same way). The reviewer (round 9)
directed: keep the anchors symmetric about the face midpoints, stop
the labels overlapping, and asked whether curved arrows should be
implemented — ggarch had no provision for curves.

## Decision

Anti-parallel straight strokes that share a corridor (chords
anti-parallel within dot < -0.99, perpendicular distance ≤
BOW_MAX_DIST (30px), chord projections overlapping ≥ 50%) draw as two
shallow **mirrored arcs**: each stroke is a quadratic bezier whose
apex is offset BOW_OFFSET (8px) from the chord midpoint along the
chord's world normal, on the side AWAY from the paired stroke. Each
label rides its own arc's OUTER side (the convex side), so the two
lanes — strokes and labels — separate at mid-corridor.

Constraints that keep the vocabulary honest:

1. **The axis member stays straight.** When exactly one chord is
   already dead straight and the other is not, only the sloped one
   bows: the straight chord is a spine/align seat (an align-middle
   arrow must stay straight — the worker-tree lesson, ADR-008).
2. **The safety veto.** A bow is kept only when its rebuilt strip —
   label rect + swept corridor — stays clear of every node box that
   is not the edge's endpoint or the endpoint's own container, and
   does not sweep into another edge's strip. Either member vetoing
   reverts BOTH to the straight vocabulary: a half-bowed pair is
   worse than none.
3. **One geometry, everywhere.** The bow is a signed apex offset
   along the chord's world normal (`_chord_normal`), computed from
   the UNMIRRORED leg in `label_geometry`, `strip_for_edge`,
   `draw_path_label` and the audit alike — the drawn label and the
   measured label are one object (the Addendum-22 law).

## Consequences

- The corpus's accepted anti-parallel LCLASHes clear without authoring
  changes: principles.ggarch went to zero residuals (the Forced-
  structure ACLASH included, whose annotation moved with the paired
  chain); juju.ggarch label-clashes 8 → 3, strip-crossings 31 → 28.
- Straight, L and U remain the planning vocabulary — the bow is a
  RENDERING of an existing straight route, never a route shape. Bend
  counts, traceability and the ≤2-bend law are untouched.
- Vetoed pairs keep the straight vocabulary (the Agent taxonomy
  declared pair reverts: its corridor hugs the middle row).
- Curves are NOT part of the candidate search: bows are assigned
  after routing, so the solver's cost model is unchanged.
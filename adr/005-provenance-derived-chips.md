# ADR-005: Provenance v2 — chips derive, bridges render

**Date:** 2026-09-19
**Status:** Accepted — implemented same day (post-0.26.1)

## Context

Review note 8 (0.26.1 corpus review), four symptoms, one failure:

1. **Records chips are semantically opaque.** The chip reads
   `rec: controller_rec` — a ggarch node id. Nothing on the canvas
   tells a reader what that means.
2. **6px text is illegible.**
3. **The unit pod lacks a chip by hand-authoring omission** — units
   ARE recorded (the unit agent carries `records: unit_rec`); the pod
   shows nothing because nobody hand-copied the chip up.
4. **Data-model views cannot draw the runtime↔record link** —
   `records:` is view-sugar on an attribute; no view grammar surfaces
   the bridge.

The user's diagnosis: all four are the same failure — **hand-declared
provenance**. The chips are author-to-author grounding pointers
(check-grounding bait), not reader signals.

The SPEC already holds the doctrine this ADR implements: "provenance
is not something you declare; it is something the model *derives*. The
unit agent's record has a foreign key to its application's record,
that record to its model's, and the model's to its cloud. A node's
provenance is a walk over real, typed, cardinality-bearing
relationships — never a hand-written address string."

## Decision

### 1. Chip text derives from the record's storage truth — never the id

The chip renders the record's **DDL ground** when it has one
(`model:units`, `controller:user` — exactly the strings
check-grounding.py verifies), falling back to the record node's label
first line when ungrounded. The ggarch node id (`unit_rec`) disappears
from the canvas entirely. The chip answers the reader's actual
question — *where does this live in persistence?* — with the string
whose truth is mechanically verified, on the channel where it belongs.

### 2. Chips are upward-closed

A container whose subtree declares `records:` shows the derived chip.
The unit pod is recorded *via* its unit agent; the hand-copied-chip
duty (and its omission failure mode) is abolished. Derivation rule:
depth-first, declaration order, first `records:` found in the subtree;
a node's own declaration outranks its descendants'.

### 3. Legibility is a requirement, not a nicety

Chip text moves 6px → 7px; the pill sizes to its content. Note 8's
"legibility fixed or dropped" resolves to *fixed* — with derived text,
a chip is worth reading.

### 4. The runtime↔record bridge is a view rendering

```
select {
  nodes: unit_pod controller
  records: shown
}
```

`records: shown` materializes one bridge edge per recorded node in the
view — runtime → record, amber, solid, **headless** — and
auto-includes the record nodes. The bridge style is the ADR-004
channel product: amber = persistence domain, headless = the
realisation axis states no call and no pointer (the pointer lives on
the FK edges of the data model, which is a different view's argument).

`records:` **stays a node attribute in the model** — the SPEC's
entity-vs-edge sidestep (0.21.0, reaffirmed by the renderings-split
resolution) stands: the attribute links entities without claiming
identity; what varies per view is the rendering. Bridges are
synthetic view edges — the validator never sees them, and
hand-declaring `type: records` edges stays invalid unless styled
(the type is not blessed as a model edge type).

### 5. Full FK-walk facets stay staged

`scope.model`, `scope.cloud` as query paths over `records:` + FK edges
remain the SPEC's TODO ("derive facets from relationships"). Derived
chips are the first leg: provenance now *derives* for rendering;
faceted *queries* (a node's provenance as data) are the next leg,
behind the tag-rendering work. No grammar for facets is added here.

## Reasoning

**Why derive the text from the ground rather than the record's
label?** The label ("unit") names the persistence face in diagram
vocabulary; the ground (`model:units`) names it in the schema's own
vocabulary, verified by check-grounding. The chip's job is to connect
the drawn process to its storage — the schema's name is the honest
answer, and it is the same string the grounding check already proves.
Ungrounded records fall back to the label (a record may be
illustrative), preserving the chip's meaning at a lower grade of
witness.

**Why upward closure rather than telling authors to copy chips?** The
omission (symptom 3) is not an authoring mistake; it is the cost of
hand-declared provenance — the exact failure note 8 names. Derivation
removes the duty instead of documenting it. A container without any
recorded descendant shows no chip (the empty case stays empty — the
chip asserts storage, and no storage is no chip).

**Why headless bridges?** Realisation ("this process is backed by this
row") is not a call (no rhythm), not a notification (no commitment),
and the storage *pointer* direction belongs to the FK edges of the
data model view, not to the runtime-view bridge. Amber + solid +
headless is the persistence-axis signature; the ER view's FK→PK arrows
remain the directional half.

**Why a view option and not always-on bridges?** Most topology views
exist to argue runtime structure; the persistence face is context
today (chips), argument in others (bridges). Making bridges opt-in
keeps the ADR-003 rule — the view tells the story it exists to tell.

## Consequences

**Easier:**
- The chip failure class (typo'd id, forgotten copy-up, illegible
  text) dies: chips are computed from validated declarations.
- The chip string and check-grounding verify the same fact — one
  truth, two consumers.
- Any view can now argue the persistence bridge without the model
  gaining grammar.

**Harder:**
- Chip pixels change everywhere records: is used (the corpus's chips
  re-render with DDL strings) — no audit metric measures chips, but
  the juju docs SVGs rebuild on next `make rebuild-ggarch`.
- The bridge is a synthetic edge type: the renderer's style bank
  carries a `records` pseudo-style that no model may declare (not
  blessed, enforced by the existing unknown-type validation).
- Facet queries remain unbuilt — the SPEC TODO stands, now with its
  first leg landed.

**Supersedes:** the `rec: <id>` chip rendering (0.21.0). Nothing else;
`records:` grammar, validation, and the entity-vs-edge resolution all
stand.

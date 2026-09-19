# ADR-004: The edge visual grammar — channels, not types

**Date:** 2026-09-19
**Status:** Accepted — implemented same day (post-0.26.1)

## Context

Review note 7 (0.26.1 corpus review): typed edges barely differ
visually — dash rhythm is the only carrier. Measured state of the juju
preset:

- `api` and `control` are **pixel-identical** (`#555555`, solid, filled
  head). The model-level distinction never reaches the canvas.
- `stream` and `event` differ **only by grey level** (`#555555` vs
  `#888888`, both `6,3`) — a distinction the reader must squint to
  find, and the weakest channel for it.
- Every topology edge carries the **same filled arrowhead**; the
  commitment distinction (call vs fire-and-forget) exists only in the
  sequence renderer, which already renders filled (call, return) vs
  open (async) heads.

An edge identity is currently one flat key ("which type") mapped to a
flat style. The reader-facing question is not "which type is this" but
"what does this stroke say" — and strokes say several independent
things at once. Flat per-type styling cannot express that composition,
and review asks for **iconic, preattentive** differentiation.

## Decision

**Edge identity decomposes into three channels with closed
vocabularies; an edge type is a point in the channel product, composed
through the style block.**

### 1. The channels

| channel | encodes | values (closed) |
|---|---|---|
| **rhythm** (stroke dash) | timing | solid = synchronous/committed; `6,3` = asynchronous/long-lived; `2,2` = in-process/local |
| **arrowhead** (terminal glyph) | commitment | filled = the stating end commits (a call is made, a pointer is stored, a watch is held); open = initiated without commitment (fire-and-forget); none = headless, no directed fact |
| **colour** (stroke) | ownership | preset-owned palette: core-process `#555555`, ambient/external `#888888`, amber = the persistence domain (visual rhyme with amber record nodes) |

The preattentive budget is **~3 values per channel**. Rhythm and
arrowhead are closed enums enforced by validation; colour is preset-
owned and the budget is an acceptance criterion for presets (a preset
shipping seven edge colours fails review, not the parser).

### 2. The built-in vocabulary re-mapped

| type | rhythm | head | colour | reads as |
|---|---|---|---|---|
| `api` | solid | filled | `#555555` | synchronous call |
| `control` | solid | filled | `#555555` | lifecycle / drives — **collapses visually with api** (ratified, see Resolved 2) |
| `stream` | `6,3` | filled | `#555555` | long-lived, committed watch |
| `event` | `6,3` | **open** | `#888888` | one-way notification, fire-and-forget |
| `ipc` | `2,2` | filled | `#888888` | local call |
| `data` | solid | filled | amber | pointer / persistence |

The changes to today's rendering: `event` gains the **open** head
(previously colour-only vs stream). Everything else keeps its pixels.

### 3. Unification with the sequence arrowhead grammar

Filled = committed interaction; open = initiated without awaiting.
The sequence renderer already implements exactly this split (call and
return filled, async open) — the topology side adopts the same
semantics and shapes, so a reader learns the head grammar once.
Sequence `return` keeps its dashed rhythm and filled head (a return is
a committed delivery); sequence-local timing stays sequence-local.

### 4. Direction is orthogonal to shape

The per-edge `arrow:` attribute (forward / back / both / none)
composes with the type's head shape: `arrow: both` on a `stream` is
two filled heads; on an `event`, two open heads. Shape says
*commitment*; `arrow:` says *which ends state it*.

### 5. Custom types compose channels via the style block

```
style {
  extends: juju

  edge notify { stroke-dash: "6,3" arrowhead: open }   // async family
  edge watch-lease { stroke-dash: "6,3" }              // inherits filled
  edge memo { arrowhead: none }                        // headless
}
```

An unknown `arrowhead` value is a validation error — the channel's
preattentive limit is enforced by construction, not by review.

## Reasoning

**Why three channels rather than richer per-type styling?** Because
the reader's question is compositional. "Is this call synchronous?"
and "does this end commit?" are independent facts; a flat type palette
forces their product into the type list (N types × M variants) or
into labels. Three channels with ~3 values each give 27 distinguishable
combinations inside the preattentive budget, and a custom type is one
line, not a new reading lesson.

**Why is rhythm timing, not mechanism?** `ipc`'s dotted line does carry
a mechanism hint (in-process), but its timing truth is "no cross-process
call" — solid and `6,3` both promise cross-boundary interaction timing
that `2,2` does not. One channel, one question.

**Why head = commitment?** Because it is the sequence grammar's
existing, reader-tested distinction (note 5 of the same review: "subtle,
note recorded" — the distinction was present but never documented as a
grammar). A watch (stream) commits: state changes flow back, the
connection is held. A notification (event) does not: the sender forgets.
The heads encode exactly that, in both view kinds.

**Why does `data` keep its head?** Note 7 sketched "data = association
(headless, multiplicity)". That sketch predates the data-model doctrine
(2026-09-19, SKILL.md): on record views, **the FK→PK arrow is the only
directionality storage states** — the pointer location is the one half
with a truth-maker, and the arrow is where it lives. Headless data
edges would hide it. Headless remains per-edge vocabulary (`arrow:
none`) for true undirected associations; no corpus case exists yet, so
none is shipped by default (the ADR-003 pattern: deferred behind a real
case).

**Why does api collapse with control?** The distinction is modeler
vocabulary (lifecycle supervision vs RPC), not reader vocabulary:
both are synchronous committed calls between processes. Spending a
rhythm value or a colour on it would break the channel budgets for a
difference no reader acts on. The semantic distinction survives where
it belongs — the model, the validator, and the legend's text (a legend
names vocabulary; it does not have to claim pixel differences that do
not exist).

**Why is the marker colour neutral?** Head shape is the commitment
channel; painting heads in the ownership colour would double-spend
colour and blur the channel boundary. One neutral head palette
(light/dark) for all types.

## Consequences

**Easier:**
- `stream` vs `event` is readable at a glance (head + colour agree,
  per the "never let two channels argue" taste) instead of by squint.
- Custom edge types are one style-block line composing declared
  channels; the closed enums keep the preattentive budget honest by
  construction.
- The commitment question ("does this end commit?") is answered
  identically in topology and sequence views.
- The legend documents vocabulary and can assert the channel meanings
  once, for every diagram in the project.

**Harder:**
- Two marker defs become four (filled/open × forward/reverse); the
  renderer picks per resolved edge style.
- The style block gains a validated enum; presets must keep their
  colour budget (~3) honest — review criterion, not code.
- `event` edges change pixels (2 in the juju corpus); the audit does
  not measure head shape and sequences are untouched, so no metric
  moves.

**Supersedes nothing.** ADR-002 (labels) and ADR-003 (routing) are
untouched; this decision sits above them in the stack (identity before
placement). SPEC open question 4 ("extend via style, not built-ins")
is reaffirmed and sharpened: extensions compose declared channels.

## Resolved in discussion (2026-09-19)

1. **`data` stays directional** (refines note 7). The headless sketch
   predates the data-model doctrine; the FK→PK arrow is storage truth
   and stays drawn. Headless is per-edge vocabulary, staged behind a
   real case.
2. **api + control collapse ratified** — from accident to policy.
   Recorded in the table above.
3. **event = open head** — fire-and-forget is the definition of "no
   commitment"; the stream/event split moves from grey-squint to
   head + colour.
4. **Neutral head colour** — shape is the channel; colour is not
   double-spent.

## Related resolutions recorded here (label-tension riders, from the
## 2026-09-19 label-semantics thread)

These are decisions of record, attached to this ADR because they share
its review round; each is a staging rule, not new rendering.

- **Mixed read-directions in a fan are correct, not a defect.** The
  mirror law (`mirror = ux < 0`, ADR-002 decision 3) is the street-map
  semicircle: text flips to stay in the readable half-plane, so labels
  on near-vertical legs read opposite ways with no local cue why. The
  discontinuity is the entire cost of the design and cartography
  accepted it a century ago. The auto-flip staging question is
  therefore purely "does the fan read at a glance"; the clash and
  ratio metrics stay the gate.
- **The annotations tripwire.** If edge labels stop fitting their
  longest leg, the model wants annotations (box, callout), not longer
  labels. "Labels name, annotations explain" — long-label pressure is
  a vocabulary problem in every placement style (glue pays it in
  rotation, horizontal+gap pays it in occlusion; neither dissolves
  it).
- **Fallback criteria, on file:** (1) structurizr-style
  horizontal+gap labels only if auto-flip fails the at-a-glance test —
  and dash-rhythm integrity (ADR-002: the stroke is content) makes
  along-path constitutionally preferred; (2) an external layout engine
  (ELK) is benchmarked only when a corpus view shows a residual no
  listed floor mechanism owns; (3) Cassowary badge placement only if
  LCLASH-class clashes prove the cheaper label contract insufficient.

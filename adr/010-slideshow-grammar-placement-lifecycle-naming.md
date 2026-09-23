# ADR-010: The slideshow grammar, section placement, and lifecycle naming

Date: 2026-09-23 (reviewer round 25, session 11). Status: §1-§3
ACCEPTED; §4 UNDER REVIEW (see its section).

Three ratified conventions from the slideshow discussion and its
follow-ups. They govern how views compose into docs — the layer above
any single view.

## 1. The slideshow grammar: seed -> mechanism -> result

A diagram's role in an argument is one of three:

- **Seed (ERD / data model)** — the state space: which records exist,
  where the pointers live. The mechanism's writes populate it.
- **Mechanism (sequence)** — what turns intent into records: who
  calls whom, in what order.
- **Result (topology)** — the settled nouns-in-place.

**Composition law: shared node identity.** The sequence's actors ARE
the topology's nodes; the records the sequence writes ARE the ERD's
entities. A slideshow is one world observed at three levels of
abstraction, not three diagrams.

**Slides are filled only when the doc's argument needs them** — a
bootstrap pair is sequence -> result (no ERD beat: bootstrap writes
controller records, not the model-DB records the data model draws);
a deploy quartet is seed -> mechanism -> result -> **verification
beat** (the `juju status` sequence: what you built is what status
projects).

**Form**: multiple views in one beat compose as a `:slides:` carousel
(`:slide-captions:` carrying the per-slide connection); single-diagram
beats stay plain embeds. The top-placement pattern (below) applies to
plain embeds; a carousel stands in for the stack of figures. Tutorial
reveal stays in-page (prose develops between beats).

## 2. Placement: the diagram is a preview on top of the text

A diagram (drawing + caption) sits at the TOP of its section, before
the prose — a visual redundancy the reader previews, the GitHub-README
pattern. Consequences:

- Captions must be self-sufficient (no lead-in paragraph frames the
  figure); keep them SHORT (the Databag caption budget: ~25% of its
  former length).
- Connective prose survives — as body text under the figures.
- With multiple figures in one section, use a carousel (see 1) rather
  than a bare stack — the exception is figures the reader should
  compare side by side.

## 3. Lifecycle sections: event titles, entity-scoped

Entity reference pages carry LAYERS: structure (taxonomy,
identification), mechanism, records, lifecycle.

- Lifecycle sections are named for the event, entity-scoped:
  *Unit removal*, *Model removal*, *Relation creation*. Activity
  titles (*Integrating applications*) stay in the how-tos.
- Lifecycle content groups under an `<Entity> lifecycle` umbrella
  with event-named subsections, kept whenever a page carries
  lifecycle content — never an empty scaffold (the secret.md
  precedent: *Secret lifecycle* -> *Charm-secret lifecycle* /
  *User-secret lifecycle*).
- Title-announces-nesting is a DEFAULT, not a law: a qualifier-titled
  section keeps its full explicit title when it must stand alone in
  search/AI retrieval (*Hook execution guarantees* stays an h3 with
  its full name; the full title is the SEO/AI surface, the level
  carries the nesting).
- The catalogue's **Insert at** lines carry the literal heading text,
  path included when nested (`§ Unit lifecycle -> § Unit removal`).

## 4. State machines are not the default lifecycle rendering — UNDER REVIEW

Draft position (NOT yet ratified): a state machine earns its place
only where the entity has a negotiated, failure-prone state graph
(the uniter's operation executor, secret lifecycle); a linear
scripted flow is sequence material, not a state machine. The
reviewer re-opened this for every `<entity> lifecycle` section in
round 25 (batch 5, "the big question"); the design note there
settles it.

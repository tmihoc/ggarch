# ADR-014: Persistence follows the schema

Date: 2026-09-27 (session 43, in-session design conversation). Status: **ACCEPTED** —
reviewer ratified 2026-09-27 ("let's make it adr-014 and start working on it in the next
session"). Worked ground: build/review/design-persistence-erd-first.md.

## Context

The entity pages' persistence sections are "incredibly inefficient" (reviewer): record
prose spread across subsections — identity, data-model, states, types — that restate what
the schema's tables already say, with the ERD relegated to an illustration. Anything that
is an entity in the ADR-013 sense has a persistence-layer story, i.e., TABLES; those
tables, rendered as a physical ERD, give all the information the subsections try to say in
prose: the entity's attributes (including identity and states), its neighbors, and how it
relates to them.

A grounded walkthrough of the simplest case (subnet,
`domain/schema/model/sql/0008-space.sql` + `0009-subnet.sql`) established the vocabulary
the redesign is built on:

- **The PK is the join handle; the UNIQUE index is the natural key.** `subnet.uuid` exists
  so neighbors' FKs have something to point at; how the entity is ADDRESSED is the unique
  claim (`space.name`, `availability_zone.name`, and for subnet the 1:1
  `provider_subnet.provider_id` pair — subnet has no unique on `cidr`).
- **An FK is a pointer the record HOLDS** — an assertion about its neighbor (containment,
  membership, attribution), not a call; nothing is invoked in the data model. A nullable FK
  states an honest absence in the schema itself.
- **Four column classes, distinguishable by shape in the ERD:** intrinsic attributes
  (`cidr`, `vlan_tag`); vocabulary FKs to lookup tables (the stored discriminators — the
  "Types of X" material); neighbor-fact copies (1:1 satellites like `provider_*`);
  the edge as a record (join tables — composite PK, the most-connected tables on the page;
  ADR-013's associative entities are join tables that grew facts).

## Decision

1. **ERD-first persistence.** Each entity page's persistence section opens with the
   physical ERD of the entity's tables as the anchor truth; the prose EXPLAINS it
   (provenance paragraph — cached vs native; the identity pair; each FK edge read as an
   assertion; each satellite/join table in one sentence) and does little else.
2. **Subsections dissolve.** Identity + data-model h3s stay dissolved (anchors stacked on
   the persistence h2, names VERBATIM — the established discipline). "X states" is read off
   the ERD (no life column, no status table = nothing transitions — visible, not declared);
   machine keeps projection prose only because its four status tables have four different
   writers. "Types of X" survives only as vocabulary-FK discriminators; the phenomenological
   problem (charm's parked taxonomy) dissolves — a taxonomy with no table has no home in an
   ERD-first chapter.
3. **The abstraction ladder, applied per page:** the entity's own tables at attribute
   level; satellites and join tables at key level or folded into edge annotations;
   neighbors at entity level — collapsed, entity-labeled boxes without columns.
4. **Neighbor collapse** is meaningful, not a loss: FK edges are type-level facts,
   multiplicity lives on the edge label, and ggarch's record-node grammar already reads
   "this row points into that table." Collapsed chips hyperlink to the neighbor's
   persistence chapter (the parked node-label-hyperlinks rider becomes load-bearing) and
   carry their own visual style (rides the visual-language overhaul) so a chip never reads
   as a table with hidden columns.
5. **Expand/collapse rule:** expand what exists to describe THIS entity (status tables,
   satellites, join tables storing its facts — relation's settings hang on the
   unit↔relation edge); collapse what is another entity's story.
6. **What stays beyond the walkthrough:** the recording acts (which service performs the
   writes — the spine keeps it) and the cached-vs-native provenance. The ADR-013 copies
   census folds into the provenance paragraph.

## Consequences

- **Precondition — the ggarch floating-edge defect must be fixed FIRST** (TODOS riders,
  session 43): all six attribute slices (application, unit, charm, secret, relation,
  machine — rasterized and inspected) route edges to `positions`-relocated nodes at the
  pre-position grid, leaving floating stubs with orphaned labels. The ERD cannot be the
  page's anchor truth while the renderer betrays it. Engine fix: apply declared positions
  BEFORE route computation; regression-gate it (session rule 3).
- **Template test before the sweep:** one template must hold at both ends of the spectrum —
  subnet (simple: ERD + walkthrough, states/types dissolve) and machine (heavy: ERD +
  walkthrough + per-projection prose, the ladder decides level). If the machine walkthrough
  bloats, the fallback is a two-tier template. Reviewer picks after the test.
- **Then the sweep:** 18 persistence sections + ~8 ERD views rewritten ERD-first, per-round
  chain unchanged (inbound-ref greps for every dissolved anchor, purge builds, curl gates,
  verify-docs serverless, Conventional commits).
- **Sequencing:** engine fix → subnet/machine template test → reviewer pick → sweep.
- Interacts with parked items: ERD-C2 (abstraction-level trade-off — largely superseded by
  the ladder here), node-label hyperlinks, visual-language overhaul (chip style),
  charm's parked phenomenological taxonomy (dissolves; the end-of-page TODO retires when
  the page round reaches charm).
- The round-(b) rules-slot vocabulary (build/review/design-rules-slot-enforcement.md) is
  unaffected: enforcement material stays in rules; only persistence is redesigned here.
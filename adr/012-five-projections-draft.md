# ADR-012 (DRAFT): The five projections — one model, five diagram kinds

Date: 2026-09-26 (session 32 tail). Status: **PROPOSED** — reviewer:
"This is important. Store it somewhere where we can easily find it
again. Might be the key to my entity reference docs dilemma."

## Context

The entity reference's records sections were reading as incoherent
(session 32, reviewer's credential.md walk-through): identity
pre-empting the states section, the data-model figure scoped
differently from the identity enumeration, "Types of X" meaning two
different things across pages. Separately, the diagram catalogue's
caption kinds (ERD / Topology / Sequence / State machine / Taxonomy)
needed a rule for which kind a figure is. Both questions turned out to
be the same question.

## The claim

There is ONE model of a Juju entity — the domain-logic skeleton of
ADR-011 — and every useful diagram is one of five PROJECTIONS of it.
Each projection answers one question:

| Projection | Question | Drawn from (the four layers) |
|---|---|---|
| Schema (grammar) | what CAN exist | enums, the life domain, FKs, uniqueness — DDL + validator constants |
| ERD (records) | what IS stored, where the pointers live | the tables — the schema's stored vocabulary |
| State machine | what may change, who may change it | the schema/service SEAM: possible states from schema (the `life` enum is DDL-constrained); allowed transitions from service rules (authority owners — the Undertaker marks dying, an agent reports dead) |
| Topology | what runs where | runtime workers/agents — the schema constrains none of it |
| Sequence | how a change happens over time | operations spanning the layers |
| Taxonomy | what kinds exist | classification above all of it |

(Six rows; the schema row is the model's grammar, not a diagram kind —
ERDs project its stored vocabulary, state machines project its change
vocabulary joined with service authority.)

The connective tissue: the state machine sits exactly at the
schema/service seam. The ERD is the schema's instance vocabulary;
topology and sequence are the runtime that realizes and mutates those
instances; taxonomy classifies. No single projection carries the
entity — which is why an entity reference page needs all of them, and
why ADR-011's four parts are these projections read as prose.

## Consequences

1. **Caption kind = the question the figure answers.** A record-pointer
   figure drawn in ERD grammar answers "what is stored?", never "what
   runs where?" — regardless of what it looks like. (This is the test
   the session-32 caption relabels applied: charm origins, credential
   chain -> ERD.)
2. **Mixed-question figures declare one primary**, and the caption's
   opening matches it (machine.md's designation figure is runtime — its
   caption should open with the provisioning story, not the records).
3. **Mirrors the ADR-011 skeleton and the
   declaration/persistence/execution layer as one system:**
   persistence -> ERD; execution -> topology + sequence; the entity's
   own states -> state machine; types -> taxonomy; declaration stays in
   the how-tos with no diagrams (ADR-011 ruling unchanged).
4. **Slot contracts (the C13 proposal) become derivable:** each records
   section is the prose of one projection; content that belongs to a
   different projection (cross-db facts, state flags narrated in
   identity) is misfiled and moves. "Types of X" must say which
   projection it is: the stored discriminator (schema grammar) or an
   interpretive taxonomy.

## The bubble-up principle (general form; see TODOS discussion)

Every claim in a reference doc must be GENERATED FROM, GUARDED AGAINST,
or LINKED TO a lower carrier — or explicitly marked as synthesis
(multi-source, review-caught). Bubble-up is a PLACEMENT discipline
(dev docs: never hoist what belongs lower) joined with a VISIBILITY
discipline (user docs: surface what the audience will never find in the
codebase); the one genuine scope-addition of the reference layer is
cross-layer synthesis. Go's doc.go/pkg.go.dev institutionalizes one
carrier tier; Rust similar; C has none.

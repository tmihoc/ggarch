# ADR-011: The entity reference doc follows the domain logic

Date: 2026-09-23 (round 25, session 11; reviewer directive: "look at
the Juju codebase, the way it does domains — not the code structure
necessarily but its logic"). Status: ADOPTED (ratified in discussion;
pilot = relation.md).

AMENDED 2026-09-24 (session 15; reviewer verdicts round 26): the
section NAMING law below is new — the pilot's first titles were
verbal ("Working with relations", "Watching relations") and one broke
the metalanguage rule ("Related domains"). The amended skeleton fixes
all eight titles and makes the storage→story derivation visible.

## Context

The entity reference docs evolved organically: taxonomy /
identification / lifecycle / databag / backend / permissions
sections in varying orders. Two attempts to derive a principled
section ORDER (an "existence arc"; a "life spine" mirroring the
how-tos) were rejected — the reviewer's framing settled the frame:
**howto sections are methods; entity reference sections are
attributes** (Juju is a Go codebase — Go composition, not Java OOP;
the closer parallel to attributes is the entity attributes in an
ERD). Two constraints ratified with it: **no diagrams in howtos**
(operations logic is client-agnostic; the howtos are
juju-CLI-specific), and the reference's lifecycle sections describe
operational logic client-agnostically.

Grounds: two read-only scouts walked the Juju 4.0 domain layer
(domain/doc.go, domain/services, domain/secret, domain/relation
end-to-end). A domain = four conceptual parts:

1. **A persistence portrait** — the entity's tables, FKs, and
   derived views (the ERD slice; the code separates stored vs
   derived).
2. **Two orthogonal state machines** — the shared life
   (Alive → Dying → Dead) plus domain-specific statuses with
   validated transitions and an OWNER per transition (leader-gated,
   controller-gated, unit-gated).
3. **Services split by authority and concern** — Service /
   LeadershipService / WatchableService / MigrationService, grouped
   in code by concern (create / update / queries / access / delete /
   watch).
4. **Cross-cutting apparatus** — change-stream watchers, async
   removal jobs, an error taxonomy encoding the rules, invariant
   prose in the state doc-comments.

Related state lives in neighbouring domains (status transitions in
domain/status, removal scheduling in domain/removal, the cross-model
half in domain/crossmodelrelation).

## Decision

**The entity reference doc is the domain's public documentation,
sectioned the way the domain itself is grouped.** Eight sections,
same order on every entity page:

| # | Section (nominal) | Derivation shown | Domain counterpart | Diagram |
|---|---|---|---|---|
| 1 | X | identity: the record and its key fields | the domain's types | — |
| 2 | Types of X | the discriminating scope | the discriminating scope/fields | kind trie (is-a edges) |
| 3 | X in the data model | the persistence portrait | tables, FKs, derived views | ERD slice (stored + derived) |
| 4 | X states | state as records in the data model | life + domain statuses | the two small state machines, owners annotated |
| 5 | X operations | what mutates the entity | the service's operations, grouped create/read/update/remove with an authority axis | sequences where a workflow exists |
| 6 | X watchers | what observes the entity | change-stream triggers, namespace watchers (WatchableService) | — |
| 7 | X rules and errors | what constrains the entity | validators + the error taxonomy | — |
| 8 | Related entities | what extends the entity elsewhere | the neighbouring-domain extensions | as needed |

### The naming law (reviewer verdicts round 26)

1. **Nominal titles only.** Reference titles are nouns; the doc is
   the authoritative DESCRIPTION of the entity, not instruction.
   "Working with X" / "Watching X" are howto-verbal and retired;
   "X operations" / "X watchers" name the thing described.
2. **Visible derivation.** The titles carry the storage→story split
   the domain code embodies: record (§1) → data model (§3) → state
   records (§4) → operations (§5) → watchers (§6) → rules (§7).
   A reader sees from the table of contents that sections 1–4 are
   what the entity IS and 5–7 what HAPPENS to it.
3. **Entity as subject** (docs/agents rules): every title keeps the
   entity as subject ("Relation operations", not "Working with
   relations").
4. **No metalanguage.** Section titles never use code vocabulary as
   such — "Related domains" ("domain" is code structure) breaks the
   docs/agents metalanguage rule; the slot is "Related entities",
   whose body names the actual extensions (status, removal,
   cross-model).
5. **Client-agnostic.** The doc describes the entity, not the CLI;
   CLI mentions appear only as examples, description-first.

### Placement resolutions (round 26)

- **Entity data/settings live in §3**, not §5. The relation's
  settings (its per-unit and per-application payload, and who may
  read/write it) are a structural attribute — part of the data
  model — not an operation between creation and removal. §5 keeps
  only the state-changing workflows.
- **Watchers keep their own section (§6)** because the code gives
  them one: the domain splits Service (mutations) from
  WatchableService (change streams). The §5/§6 split is the code's
  own grouping, not an editorial one; the nominal titles make the
  grouping self-evident.
- **Rules and errors stay (§7)** but framed to the relevance bar:
  the error taxonomy is what charm developers meet in relation
  hooks and what Juju developers maintain as the domain's
  validation law. If a rule serves no reader population, it goes.

Ordering logic: it is the code's own grouping, not a narrative —
predictable on every page, client-agnostic, and charm-user vs
developer-agnostic (the domain service is the same API both consume;
the code proves it — the agent and client facades import the same
service).

## Consequences

- **Howtos carry no diagrams** (ratified): they are the juju-CLI
  task narratives; every operational diagram lives in the entity
  reference.
- **ADR-010 §4 resolved**: "lifecycle" is §4 (the two small state
  machines — life + statuses, owners included), not a big
  invocation narrative; a state machine appears exactly where the
  domain has a negotiated state graph. Scripted flows are §5
  sequences.
- **The is-a edge is green-lit for the §2 pilot** (generalization
  edges, hollow-triangle); has-a remains containment/composition
  (ADR: no conflation). Kind badges carry the kinds.
- **§2 varieties are positively named** (verdicts round 26 part 2):
  no "non-x" discriminators; each variety a self-standing subsection
  whose title carries its discriminating fact. For a tree-shaped
  taxonomy, the declared layout follows the root-apex recipe (root
  top-centre, children row-packed on the rank below centred under
  the parent, ranks top-down) — documented in SKILL.md.
- **Sequences stay in the reference** (§5), as domain workflows —
  the removal sequence tells the removal job's flow, the deploy
  sequence the creation workflow.
- **The reviewer's "topology makes things real"**: topology views
  are instance snapshots of the §3/§4 material and appear where the
  page's argument needs concreteness (deploy/bootstrap beats),
  multi-homed per the catalogue convention.
- Predictability test: a reader can locate all eight sections on any
  entity page because the skeleton is invariant.
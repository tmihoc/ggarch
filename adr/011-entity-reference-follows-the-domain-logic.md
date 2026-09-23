# ADR-011: The entity reference doc follows the domain logic

Date: 2026-09-23 (round 25, session 11; reviewer directive: "look at
the Juju codebase, the way it does domains — not the code structure
necessarily but its logic"). Status: PROPOSED (ratified in
discussion; pilot = relation.md).

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

| # | Section | Domain counterpart | Diagram |
|---|---|---|---|
| 1 | X (identity + definition) | the domain's types | — |
| 2 | Types of X | the discriminating scope/fields | kind trie (is-a edges) |
| 3 | X attributes | the persistence portrait | ERD slice (stored + derived) |
| 4 | X states and transitions | life + domain statuses | the two small state machines, owners annotated |
| 5 | Working with X | the service's operations, grouped create/read/update/remove with an authority axis | sequences where a workflow exists |
| 6 | Watching X | change-stream triggers, namespace watchers | — |
| 7 | Rules and errors | validators + the error taxonomy | — |
| 8 | Related domains | the neighbouring-domain extensions | as needed |

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
- **Sequences stay in the reference** (§5), as domain workflows —
  the removal sequence tells the removal job's flow, the deploy
  sequence the creation workflow.
- **The reviewer's "topology makes things real"**: topology views
  are instance snapshots of the §3/§4 material and appear where the
  page's argument needs concreteness (deploy/bootstrap beats),
  multi-homed per the catalogue convention.
- Predictability test: a reader can locate all eight sections on any
  entity page because the skeleton is invariant.
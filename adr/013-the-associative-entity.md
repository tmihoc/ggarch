# ADR-013: The associative entity

Date: 2026-09-26 (session 33). Status: **PROPOSED** — the generalization the reviewer sensed was
missing from the concepts/entities/processes/tools framework ("Originally I defined an entity as
anything that has a lifecycle story... Now not sure anymore").

## Context

Juju's access-control model (the `access` domain) has no reference page, so its facts leak: the
credential page states the grant fact twice (ERD caption + rules bullet), and user.md carries the
access levels as a user attribute. Meanwhile the client docsets project the same underlying record
three ways — terraform-provider-juju as per-object resources (`juju_access_model`,
`juju_access_offer`, `juju_access_secret`, `jaas_access_cloud`, …), JAAS as permission triples
(subject tag × permission × object tag, with a hierarchy note), and the Juju docs as user
attributes.

## Decision

Access IS an entity by the original definition — it has a lifecycle story (granted → revoked) —
but of a class the framework does not yet name: **the associative entity**. A record that exists
to connect a principal to an object with a role. Three tells:

1. **Its natural key is composed of its endpoints' identities** (user × object × level) — the same
   shape as a credential's (cloud × user × name) or a relation's (endpoint pairs).
2. **Its lifecycle is a create/destroy arc** (grant/revoke) — no rich state machine.
3. **Its machinery is delegated** to the connected entities' machinery — the check happens when
   the object is used, not when the grant is made.

Juju's associative entities: access grants, relation, offer, secret grants. A credential is NOT
one — it is resource material (it authenticates; it does not connect a principal to an object).

## Consequences

- The framework gains the associative-entity class; the entity definition (has a lifecycle story)
  stands unchanged.
- `access.md` states the record, the triple, and the hierarchy ONCE; every client howto — Juju,
  terraform-provider-juju, JAAS — links to it instead of re-projecting the model.
- The three-docset tension dissolves: TF resources, JAAS triples, and Juju access levels are
  projections of one association record, each in its own client's surface vocabulary.
- The entity pages stop carrying grant facts ad hoc; the credential page's data-model slot holds
  the FK fact and links out for the model.
## Amended 2026-09-26 (session 34, post-close design session): the entityhood test

The generalization this ADR proposed is now a test, and it settles the founder's old doubt
("originally I defined an entity as anything that has a lifecycle story... now not sure anymore"):

**An entity is something the user can declare intent about through a client, that Juju stores a
record of, and whose realization Juju executes.**

The lifecycle is the CONSEQUENCE (the record's states — the shadow the chain casts), not the
criterion. The counterexample that proves the sharpening: the agent has a lifecycle story
(provisioned, started, dies with its machine) and is not an entity — nobody declares an agent.

**The reference index silently mixes page types; the chain spine sorts them** (each page's
failure mode is its type declaration — the crack is always an empty declaration layer or an
empty persistence layer, and the empty chapter is the truth about the thing):

| Type | Failure | Pages |
|---|---|---|
| Entity | passes all three | cloud, credential, user, model, application, unit, relation, offer, secret, action, machine, storage, space, ssh-key, controller, charm |
| Executor (stage-3 subject) | no declaration layer | agent, jujud, containeragent, worker, watcher, pebble |
| Instrument (stage-1 tool) | the means of intent, not its object | client, juju-cli, juju-web-cli, dashboard, jujuc, hook-command |
| Substrate | the chain runs on it | database (the juju client never speaks to it as an object of intent; manage-the-databases is ops, juju db-repl a peephole) |
| Observation | recordings OF the chain | log, telemetry, status |
| Chain-walk process | the full walk across entities | removing-things, upgrading-things, scaling, high-availability |

**In-entity facet honesty** (entities whose persistence layer is empty or by-reference — the
spine says so rather than pretending): bundle = a composite intent, stored only as the
applications it expands to (nothing is recorded as a bundle); constraint and placement-directive
are recorded on other entities' records (columns on application/machine records); zone
(discovered, not declarable) and script (charm content, not separately declared) are to be
grounded in their own rounds.

**Disposition:** the chain spine applies to the entity pages only; the non-entity types keep
their current form until their own spines are cracked (reviewer: "we'll keep investigating till
we've cracked their logic too"). access.md takes the full entity spine (grants are declarable,
stored, executed) and is queued after the sweep.

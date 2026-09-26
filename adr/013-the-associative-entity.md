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
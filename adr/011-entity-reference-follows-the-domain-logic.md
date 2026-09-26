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

AMENDED 2026-09-25 (session 19; reviewer verdicts round 32): the
PRESENTATION grows two umbrella layers over the invariant slots --
"The X's records" and "The X's machinery" -- the types slot moves
after the data model, body prose adopts the location-qualified
scope-phrase convention, and the §1 opener is rewritten as a
representation claim. The slot table below stays the inner skeleton;
see "The umbrella presentation (round 32)".

AMENDED 2026-09-25 (session 19 cont.; reviewer verdicts round 33):
types-last stands; §1 is retitled *The X's identity* (the
records/record stutter) and §8 *Entities related to the X* (the
red thread -- every title carries the entity name); folding §8
into the intro was evaluated and rejected. See "The umbrella
presentation".

AMENDED 2026-09-25 (session 20; reviewer ratification, the
database.md pilot): the META-ENTITY case -- an entity that is a
mechanism, not a record -- joins the umbrella presentation; see
"The meta-entity" below.

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

### The umbrella presentation (round 32)

The eight slots above stay invariant; the presentation groups them
under two umbrella h2s, and the page's table of contents now
narrates the slideshow grammar (ADR-010): records are the ERD
layer, machinery is the sequence layer, and the topology result
beats live inside the machinery layer.

**The two layers.** The entity page's h2s are:

- **The X's records** -- h3s in order: *the X's identity* (§1), *the
  X in the data model* (§3), *X states* (§4), *Types of X* (§2, the
  last h3). What Juju does with an arrival first: PERSIST it.
  Declaration-of-intent is the client's job; it lives in the howto
  layer and the architecture concept page, not here.
- **The X's machinery** -- h3s: *X operations* (§5), *X watchers*
  (§6). What Juju does with an arrival second: EXECUTE it.
- **X rules and errors** (§7) and **Entities related to the X** (§8)
  stay top-level h2s: cross-cutting law and neighbouring-domain
  extensions are neither records nor machinery.

Umbrella titles are entity-possessive nouns ("The machine's
records", "The machine's machinery"); the participle-epithet
alternative ("the persisted model", "the executed charm") failed on
the meta-entities.

**The slot titles under the umbrellas (round 33).** §1 is titled
*The X's identity*: the umbrella already says "records", and its
first h3 must not stutter with it ("The charm's records / The
charm record") -- the section answers WHICH record the entity is
and what identifies it (the machine ID, the source-name-revision
triple, the offer URL), which is the identity question. §3 stays
*The X in the data model* and remains separate from §1 on
purpose: identity is what you POINT AT; the data model is what
SURROUNDS it -- the whole stored footprint with every foreign
key, the ERD slice view's home. §8 is retitled *Entities related
to the X* (the red thread: every title carries the entity name).
Folding §8 into the intro was evaluated and rejected: its bullets
carry substantive cross-facts (the shared net node, removal
ownership, the zone pointer), the intro must stay a definition,
and reference pages are random-access -- a reader arriving
mid-page never sees the intro. The C4-context anchoring the fold
was after is already served twice over: the intro names the
entity's primary neighbour, and the machinery sentence names who
executes it.

**Types after the portrait.** §2 argues from stored facts -- no type
column, kinds derived, lease-not-a-column -- so it belongs after the
persistence portrait, and after the states, which are stored facts
too. The kinds close the records layer as what the stored facts
imply. This is the fix for the "Types butt-in".

**The machinery sentence.** The machinery umbrella opens with ONE
grounded sentence, in one of three shapes:

- **OWN** (controller, model, machine, unit, agent): the entity has
  machinery of its own; the sentence names where it runs.
- **DELEGATED** (application, charm, relation): no machinery of its
  own; its units' agents execute it, and the model side is
  bookkeeping.
- **NONE** (bundle, subnet, constraint, zone, placement directive):
  no machinery at all; the record is a stored fact -- a cached cloud
  fact, a request input, a client-side artifact.

**The meta-entity (database.md, session 20).** One reference page
names the mechanism the whole presentation rests on: the database
itself -- no records of its own, because it is where every entity's
records live. Its records layer is the DEGENERATE shape, the NONE
machinery sentence inverted onto the persistence mechanism: §1 (The
database's identity) carries the inversion, and the controller
database / model database split stands in for the data-model slot as
the which-database-holds-what portrait. Its machinery is plainly
OWN -- Dqlite embedded in-process in every controller, no separate
database service, Raft-replicated across the HA nodes -- and the
layer carries the change stream every §6 watcher draws on. Slots
appear only when grounded: no states, types, operations, watchers,
rules or relations sections exist for it, and none were invented
(the do-not-force law). The component/tool do-not-force class
(jujud, pebble, the CLI pages) stays out unless a page grows real
entity substance -- the test is substance first, umbrella only where
both layers have a grounded sentence (accepted recommendation,
session 20).

**The scope-phrase convention.** Body sentences carry locations --
databases and processes, never commands: the intro says "In Juju, a
charm is…"; the records layer says "In the model database, a charm
is one record per revision…"; the machinery layer says "In the
controller, the revision updater…". The client-agnostic law is
unchanged (the two CLI-facing exceptions stay flag-marked). Use the
phrase where the location genuinely shifts; never a tic.

**The §1 rewrite rule.** The record section stops competing with
the intro as a definition: no "X is a record" opener. The claim
demotes from definition to representation and becomes
location-qualified: "In the model database, a charm is one record
per revision…".

**§4 stays in records** with the recorded phrasing: life is the
record's condition; instance status is the executed thing's
condition, written down.

**Mechanics.** Every existing `(anchor)=` target is preserved
verbatim; slot sections shift h2 to h3 under their umbrella, and
child headings shift with their section; no new views; the
catalogue's Insert-at strings re-point to the new heading chains.

**The three ontologies, made real.** The layers also separate
concept-with-record entities (relation, offer, user, space…) from
entities with a physical counterpart (machine, unit, charm, secret,
controller, model, credential): the counterpart's mechanism and
result already live in the machinery layer as §5 sequences and
topology result beats.

The "not a narrative" claim above is superseded to this extent: the
slot ORDER stays the code's grouping, but the two-layer GROUPING is
the page's narrative -- records, then machinery, then rules, then
relations.

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
AMENDED 2026-09-26 (session 33; reviewer verdicts, the unified presentation): the three frameworks
compose as one pipeline -- the four layers are where truth lives (sources); the five projections
(ADR-012) are the questions a reader asks; declaration/persistence/execution is the order an intent
visits those sources -- and the page narrates that visit top to bottom. What was rejected in round 25
(two workflow-shaped section ORDERS) never needed resurrecting: the adopted skeleton already realizes
the pipeline as structure. The amendments:

1. **The declaration section.** A new h2, *The X's declaration*, opens the page after the lede. Its
   body is LINKS to the how-to surfaces: the repo-internal Juju how-tos and, where a
   terraform-provider-juju resource/how-to exists, the TF how-to via the `tfjuju` intersphinx mapping
   (the lxd.md See-also pattern). The client-agnostic law is unchanged: links, never CLI narration.
   This supersedes the round-25 reading that declaration lives ONLY in the howto layer (reviewer
   steer, session 33); the ibnote it replaces becomes the section.
2. **The umbrella titles carry their stage.** *The X's records* -> *The X's persistence*;
   *The X's machinery* -> *The X's execution* (the word "machinery" is retired). Rationale: the
   two-umbrella cut is honest as a STAGE sequence, not as categories; the titles now say so, and the
   TOC reads declaration -> persistence -> execution with no explainer needed.
3. **§8 dissolved (supersedes round 33).** *Entities related to the X* is deleted as a section. The
   lede gains a triangulation paragraph (the neighbours, one pass, prose); FK-shaped facts rehome in
   the data-model slot, service facts in machinery/states; random access is served by cross-links,
   not repetition (the watcher-dedup precedent, d4c31acf61).
4. **The filing rule.** ONE claim, ONE stage, ONE section. A repeated claim is a claim whose stage was
   never decided; cross-slot duplication is the defect signature (credential.md's grant fact appeared
   in both the ERD caption and the rules bullet).
5. **The slot contracts (C13 ratified).** identity = what a record of X is, its natural key, where it
   lives -- NO forward references; data model = the stored tables + the FK slice -- cross-database and
   cross-entity facts live HERE; states = life/status with owners, degenerate case explicitly allowed
   (standing flags with no life machine, e.g. credential); types = the section DECLARES its
   projection: the stored discriminator (schema grammar) or an interpretive taxonomy ("kinds, not a
   partition", e.g. charm). rules-and-errors = the enforcement surface ONLY: claims not already
   stated at their stage (a rule that restates a validator's uniqueness or an enum membership
   duplicates identity/types and is deleted) + the error taxonomy — the part users actually meet
   (credential.md's rules section was 3/4 stage duplicates; session-33 round).
6. **Operations are service-side.** §5 narrates the service's mutations with the location-qualified
   scope-phrase; client operations belong to the declaration section's links. A CLI command inside a
   service story is a stage blur (credential.md defect, fixed in the round).
7. **The naming verdict (C; session 34, amends items 1–2 and the round-26 naming law at umbrella
   level).** The umbrella h2s go question/gloss form: *How you declare the X* / *What Juju stores* /
   *What happens in the background* (the reviewer's glosses: declaration = things you can do;
   persistence = what Juju stores; execution = what happens in the background). Rationale: concrete
   phrasing beats abstract nouns — "maybe the old law was bad" — so the round-26 nominal-titles rule
   is AMENDED at umbrella level only: slot h3s may stay nominal where they already read concretely.
   §5 follows the same logic: "X operations" evokes the reader doing something, but the section is
   about what happens in the background — derive the concrete form per entity (proposed per page,
   batched). The article folds in: generic sections drop false definites (The -> bare/generic form);
   the red thread is unchanged (the entity name in every title). Items 1–2's titles (*The X's
   declaration* / *The X's persistence* / *The X's execution*) are superseded by these forms; the
   staged sequence declaration -> persistence -> execution is unchanged — only the wording moved.
8. **The chain spine (session 34, post-close design session; supersedes items 1–2's section model and
   item 7's umbrella forms).** The page's h2 spine is the chain itself — *Credentials in the
   declaration layer* / *Credentials in the persistence layer* / *Credentials in the execution
   layer* — plus *X rules and errors* outside the chain. Packed rulings:
   - **Titles.** Plural class + "layer": "Credentials in the X layer" (plural = the class-topic;
     "in" = the structural reading; the chronology comes from the chapter order and the bridge
     sentence, not the title). "Layer" means the stage strata — the dependency stack genuinely
     holds (an intent flows down: declaration feeds the writes, the writes produce the records,
     the agents read the records). User-facing, the four-layer SOURCE model is "the sources";
     "layer" is never used for it. The red thread is STRICT at every level (the reviewer: dropping
     the entity name is bad for AI and SEO; "Machines in the execution layer" / "Models in the
     persistence layer" is the cross-page preattentive theme that teaches the chain).
   - **The writes re-file (supersedes item 6).** The service's inserts/upserts/removes/invalidates
     are the RECORDING ACT — they live in the persistence layer. The execution layer is
     world-facing only: checks, watches, machinery ("a credential has no machinery of its own"
     becomes the opening payoff, not an apology).
   - **The record merge.** Identity dissolves into the persistence layer's opening prose — the
     record (natural key, attributes, uniqueness) -> the chain figure -> the copies; three zooms,
     no sub-heading of its own. Data model = grammar (the reviewer's standing reading; see
     ADR-012). States and types are h3s INSIDE the persistence layer. The identity contract's "no
     forward references" survives as prose style, not as structure.
   - **The states seam.** One prose clause in the states h3 (stage 3 discovers — a failed check;
     stage 2 records — invalid is written). No tags; the layer titles carry the stages.
   - **The declaration layer is the do-surface.** The verbs, add to remove (one sentence) + the
     client-vs-controller footnote + the ibnote links (lxd.md pattern). Not a creation story
     ("Where a credential comes from" was rejected: it names one verb).
   - **The bridge sentence.** The execution layer opens with the prompt-returns teaching,
     entity-adapted: "by the time the command returns, the record exists; nothing has yet proved
     the credential works" (machine: "the machines don't exist yet"). The prompt returning is the
     declaration/persistence handoff — the common misconception is that it is the end of the
     chain. The canonical statement (with the bootstrap caveat — machine before db, the one place
     the order inverts) lands on the architecture page (P0-1).
   - **Title-law closure.** Topics are nominal/structural; "How you X" titles read as how-to
     (round-26's own rationale) and are retired at every level, along with gerunds; "What you can
     do" reads complete. The naming saga resolves: the round-26 nominal law was right for the
     layer that still has titles; the churn lived in the buckets, which are now three named
     strata carrying the entity in each title.
   - **Watchers keep an h3** under the execution layer (the juju-dev chip's home; the code's own
     Service/WatchableService split).

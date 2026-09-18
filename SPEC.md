# ggarch -- Specification

A Grammar of Architecture Diagrams.

A text-based, constraint-layout diagram tool for architecture documentation,
inspired by the Grammar of Graphics (Wilkinson 2005) and its R
implementation ggplot2. ggarch adopts two of the Grammar of Graphics'
commitments and inverts the third:

- **Separation into composable layers** -- independent concerns declared
  separately and rendered in a defined order (select, positions, routing,
  annotations, style).
- **One channel, one meaning** -- each visual channel encodes exactly one
  semantic dimension of the model; nothing decorates for its own sake
  (see "Visual grammar and shape ontology").
- **Inverted: position derived from data.** In the Grammar of Graphics,
  position is an aesthetic -- x and y are mappings from data, and the
  interesting design question is the scale. In ggarch, position is
  *authored content*: the spatial arrangement of a diagram is part of what
  it says, not a rendering decision delegated to a layout engine. Layout is
  declarative (Cassowary-solved constraints); auto-layout is a default for
  the cases where any coherent arrangement would do, not a claim of
  authority over arrangement. See Motivation, "Position is content".

**Licence: Apache-2.0.** ggarch is an open source project. Apache-2.0 is
Canonical's standard licence for infrastructure and developer tooling (Juju,
LXD, and most of the ecosystem use it). It permits unrestricted use,
modification, and embedding -- including in commercial docs pipelines -- with no
conditions beyond attribution and preserving the licence notice. It includes an
explicit patent grant. Generated SVG output is not a derived work of the tool
and carries no licence obligations regardless. GPL-3 was considered; Apache-2.0
was chosen because copyleft friction on embedding would limit adoption without
meaningfully protecting the project.

---

## Background

Architecture diagrams have three competing demands: **branding** (they must
look good and fit the document's visual identity), **expressive power** (they
must be able to represent what actually needs to be communicated), and
**maintainability** (they must be easy to keep current as the system evolves).

Historically, diagrams-as-code tools score well on maintainability but poorly
on expressive power: constraint layout is absent, semantic edge types don't
exist, deployment environments aren't modelled, and the same entity must be
re-declared in every diagram. Tools with genuine expressive power (Excalidraw,
Omnigraffle, hand-tuned SVG) require manual drawing, which has always been slow
and error-prone for humans and is especially resistant to AI assistance —
current language models are remarkably good at code but struggle to produce
correct spatial layout from scratch in pixel-based or free-form tools.

This created a practical impasse. Several years of experiments with Structurizr,
Mermaid, and D2 concluded that no existing tool had adequate expressive power
for distributed systems documentation -- the kind needed to write a progressive,
beginner-friendly architecture document for a system like Juju, where the same
entities appear in topology views, sequence diagrams, data-model diagrams, and
deployment environment views, and where lifecycle, cardinality, and abstraction
relationships are genuine load-bearing concepts. Expressive power was therefore
treated as the non-negotiable constraint, and manual drawing was accepted as
the cost.

The calculus has now shifted. AI assistance has dramatically changed the
economics of diagrams-as-code: a language model can write and revise ggarch
source fluently, suggest positions, add nodes to sequences, and keep multiple
views consistent -- tasks that are tedious by hand but trivially expressed as
text edits. This makes maintainability newly achievable *without* sacrificing
expressive power, provided the tool itself is expressive enough. ggarch exists
because no existing tool meets both constraints simultaneously.

The current state of ggarch: it has reached full expressive parity with
the best existing docs-as-code tools, and exceeds them on several
dimensions (Cassowary constraint layout, first-class lifecycle and
cardinality, typed edges, single-model multi-view consistency,
deployment environment resolution, state machine views). This parity is
a floor, not a measure of adequacy: there is no golden standard for
diagramming a distributed stateful system -- the field has never
produced one, and every existing tool has failed the domain in a
different way. What ggarch's flagship use case (Juju's architecture
documentation) actually needs is therefore unknown, and can only be
discovered by authoring the real documents; the comparison table below
measures parity with existing tools, not sufficiency for the domain.
The Juju architecture doc work is the requirements-discovery instrument
-- which is why the two projects are developed together. The next design
challenge is **expressive power for distributed systems specifically**
-- identifying the diagram patterns that genuinely communicate system
architecture to readers who need to understand a complex, distributed,
event-driven system, and ensuring those patterns are first-class ggarch
citizens.

The third design challenge is **branding**. ggarch already has a foundation
here -- Ubuntu font and Juju orange are wired into the preset colour grammar,
and the light/dark theme pair is intentional. But branding for infrastructure
diagrams has a second dimension beyond colour and typography: **service
icons**. Kubernetes, AWS, GCP, Azure, PostgreSQL, Redis, Kafka, and similar
products each have an established icon that readers recognise instantly. In
architecture diagrams these icons replace or augment the node box, giving the
diagram a grounded, professional quality that abstract coloured rectangles
cannot. The term of art is **sprite** (a small, embeddable image used as a
visual symbol), or in the context of diagram tooling, an **icon set** or
**icon library**. PlantUML calls them sprites; C4/Structurizr calls them
icons; the AWS and Azure architecture icon kits use the term icon set.
ggarch's branding challenge is two-fold: define a clean preset system for
per-project colour grammars (Ubuntu/Canonical today; any brand tomorrow), and
introduce first-class icon/sprite support so that a node's type can resolve
to a recognised service icon rather than a plain shape.

The fourth design challenge is **extensibility**. ggarch should be easy to
extend provided the extension fits the paradigm -- new icon sets, new
presets, new node types -- without compromising any of the core design
principles. The current architecture already supports this in part: a node's
`type` is a free-form string that maps into the style grammar; there is no
closed enum of node types, only a preset that maps known type names to
`NodeStyle` values. Any type name not in the preset falls back to the
default style -- meaning new types can be introduced in a project's own
`style` block without touching ggarch itself. The extensibility challenge is
to make this pattern complete and intentional: clean APIs for registering
icon libraries and custom presets, clear guidance on what constitutes a
paradigm-conforming extension, and a packaging convention so third-party
icon sets and brand presets can be distributed independently.

This challenge also connects to a deeper design property that deserves
explicit recognition: **model integrity vs. inline convenience**. The
single-model/multi-view architecture promotes correctness and maintainability
— renaming an entity propagates everywhere, relationships cannot silently
diverge, validator errors catch uses of undeclared ids. But it introduces
a brittleness concern: if the model is large and a change has unclear blast
radius across views, an author may hesitate to update it. ggarch addresses
this through a deliberate spectrum: a diagram can be specified entirely
inline (Mermaid-style, with all nodes declared locally in the view) or
fully abstracted into a shared model with all views derived from it, or
anything in between. Inline diagrams trade the correctness guarantees for
zero coupling; that is the author's explicit choice. The tool should make
both ends of the spectrum, and the middle, equally first-class, with the
inline path and the model path treated alike.

---

## Requirements

Four design challenges, derived from the background above. Each is a
requirement on ggarch's roadmap; open items are marked **TODO**.

### Expressive power

ggarch must be able to express the diagram patterns that genuinely communicate
distributed systems architecture -- not just the simple cases other tools handle
adequately, but the hard ones that matter most for a system like Juju.

The current capability set (topology, sequence, ER/schema, class, state
machine, deployment environments) covers the main diagram types. The open
question is whether the *combination* of diagram elements ggarch supports
within each type is sufficient to draw the things that need drawing. Evidence
from the Juju architecture doc suggests the following hard cases:

- **Mixed edge semantics in one diagram.** A single topology diagram may need
  edges of type `api` (websocket RPC), `event` (watcher notification),
  `control` (process lifecycle), `ipc` (Unix socket), and a cloud-level
  "StartInstance" call that has no equivalent in the current taxonomy. The
  typed-edge system handles the first four; the cloud call needs a custom type
  or a new built-in. ✓ Verified (0.24.0): custom edge types style end-to-end
  (edge, arrowhead, SVG legend, HTML legend, light and dark) via the
  `edge <name> { ... }` style rule. Verified by test; the earlier "custom
  types exist" claim was false in practice — the type name collapsed to the
  literal "custom" at parse time, so declared styles never matched.

- **Sub-node labels / record-style nodes in topology.** The controller's
  "relation data bag" for app A and app B are conceptually inside the
  controller node, not separate nodes. Expressing "data lives here, not there"
  requires either record-style nodes (PK/FK table rows) or a way to annotate
  a sub-region of a node. ✓ Verified: record nodes nest inside containers,
  take data edges, and keep the amber record styling + `rec:` chip in
  topology views (verified against a machine-agent/machine-record rendering).
  Field-qualified edge endpoints (`node.field_id`) are supported by the
  grammar and validator; no current Juju view needs them in a topology.

- **Lifecycle on workers.** The compute provisioner runs as a persistent worker;
  hook execution is ephemeral (runs once per hook invocation, then exits).
  These are first-class lifecycle values (`persistent`, `ephemeral`). ✓
  Verified: init renders 6,3 and ephemeral 2,2 border dashes at 1px stroke on
  typical (~150px) node boxes — same dotted idiom as `ipc` edges, which the
  grammar already uses at scale. Legible; the distinction is border pattern,
  not colour, so it survives dark mode.

- **State machine transitions with guards and triggers.** The uniter's
  operation executor has precise states (preparing → executing → committing)
  view exists with `guard:` and `on:` attributes. ✓ Layout verdict: the
  single-row layout was measured colliding transition labels once guard
  text was present ("[hook fails] / fail" overlapping "/ snapshot + run"
  at the same y) -- fixed in 0.25.0 with a layered layout: columns
  follow topological depth along forward edges (the main flow runs
  left-to-right), branch targets stack below their entry column, and
  back edges bow outside the machine (above the chain when they leave
  the chain row, below when they leave a deeper row). Transition labels
  are pushed clear of their curve's flank and carry opaque backgrounds,
  so cross-edge strikes are masked. Verified by geometric audit on the
  5-state uniter machine: zero label overlaps, zero unmasked strikes.

- **Async vs sync edges in sequence diagrams.** Watcher notifications are
  async fire-and-forget; API calls are sync request/response. ggarch sequence
  has `call` (sync) and `async` step kinds. ✓ Verified on the Hook execution
  sequence, which mixes both on the same lifeline pair: call = solid shaft +
  filled arrowhead, async = solid shaft + open arrowhead (11 filled, 1 open
  rendered). Distinction is arrowhead fill only — standard convention, but
  subtle at 10px; if async steps proliferate in authored sequences, consider
  a dash or weight difference as well.

- **In-process vs cross-process calls.** The unit agent runs inside the machine
  agent (nested engine); hook tools connect to an in-process Unix socket server.
  These are architecturally important distinctions. ggarch has `ipc` edge type
  for local IPC and `control` for process lifecycle. ✓ Resolved by idiom:
  nesting is reserved for OS boundaries (containers, machines, pods);
  nested processes render as siblings joined by a `control` edge
  ("hosts (nested)" — the juju2 "Worker tree (machine cloud)" view is the
  working example). No false node boundary, no loss of the in-process fact.


### Branding

ggarch must support per-project colour grammars and service icons out of the
box, and be easy to extend with new ones.

Current state: Ubuntu font and Juju orange are in the preset; light/dark theme
is intentional.

**TODO: preset API.** Define a clean Python API for registering a named preset
(node style map + edge style map + font settings). Currently presets live in
`presets.py` as module-level dicts. A third-party package should be able to
call `ggarch.register_preset("myco", light=..., dark=...)` without patching the
module.

**TODO: icon/sprite support.** A node's `type` maps to a `NodeStyle` (fill,
stroke, shape). It should also be able to map to a **sprite** -- a small SVG or
PNG icon that replaces or augments the shape. Common infrastructure icons (the
Kubernetes wheel, the AWS smile, the PostgreSQL elephant, the Redis cube) are
immediately recognisable to readers and ground abstract box diagrams in the real
world. Design questions:
- Icon source: inline SVG (safe, no network), external URL (convenient, fragile),
  bundled icon library (discoverable, version-pinned).
- Icon placement: replace the fill entirely, or appear in a corner/header of
  the box.
- Icon registration: `ggarch.register_icon("k8s", svg=..., preset="k8s")`
  bundled as optional extras (`pip install ggarch[icons-k8s]`).

**TODO: icon set packaging convention.** Define the structure for a third-party
`ggarch-icons-aws` package so the community can contribute icon sets without
changes to ggarch core.

### Maintainability

ggarch must keep diagrams-as-code maintainable over time: a single model shared
by all views, rename propagation, validator-caught drift.

Current state: fully implemented (single model/view architecture, validator,
environment resolution).

**TODO: `abstracts:` substitution without explicit environment block.** A
`select { nodes: controller }` without an `environment:` in the select block
does not currently auto-substitute the concrete node. Should work transparently.

**TODO: import / file splitting.** A large system model (Juju's is ~600 lines)
is a single file. Allow `include "other-model.ggarch"` or a multi-file model
to keep large projects navigable without sacrificing single-source-of-truth.

### Extensibility

ggarch must be easy to extend within the paradigm -- new node types, new edge
types, new presets, new icon sets, new view renderers -- without forking or
patching core.

Current state (0.24.0): node and edge `type` are both free strings with preset
fallback; custom edge types declare named rules in the style block
(`edge <name> { ... }`, light and `@dark`), validated (unknown types are
rejected with a hint) and rendered end-to-end including legends. The
remaining gap is documented extension points, below.

**TODO: documented extension points.** Explicit API surface for:
- Custom node types and their styles (already works; make it intentional).
- Custom edge types and their styles (already works; make it intentional).
- Custom preset registration (see Branding above).
- Custom icon registration (see Branding above).
- Custom view renderers (new diagram kind beyond topology/sequence/state).

**TODO: packaging convention.** A `ggarch-ext-*` namespace convention and a
minimal plugin protocol (e.g. entry_points `ggarch.presets`, `ggarch.icons`,
`ggarch.renderers`) so extensions are discoverable and composable.

### Visual grammar and shape ontology

ggarch's visual grammar follows the Grammar of Graphics principle: each visual
channel (shape, colour, size) encodes one orthogonal dimension of meaning.
Every visual element is semantically load-bearing; nothing decorates for its
own sake.

Position is deliberately excluded from this list of channels: position is
content (an authored spatial argument), not a channel encoding a model
dimension. See Motivation, "Position is content".

**Current state:** colour already encodes ownership/provenance cleanly (Juju
orange, workload blue, external gray, charm white+orange border). Shape encodes
categorical entity type with a small honest vocabulary: rect (process/software),
cylinder (storage), person (actor). All shapes fill their bounding box to the
same margin so the constraint solver's geometry is honest for every type.

**Decisions made:**

- Workload nodes use `external` styling (gray), not a distinct blue. The
  rejected blue duplicated what colour already encoded and added only visual
  noise.
- Person nodes are a rounded rect with a small head+shoulders badge in the
  top-left corner. The badge is the type indicator; the label is centred
  inside the box. Same bounding-box convention as every other shape.
- The shape vocabulary is intentionally small: rect, cylinder, person. C4-style
  shape proliferation (person, software system, container, component, database,
  queue...) is avoided because C4's hierarchy encodes abstraction level via
  shape, which ggarch handles better through multi-view + `abstracts:`.

**One node, one visual identity across all view kinds.** A node's type
is a model fact; every view projects that fact, so the node's identity
(shape, colours, border, lifecycle dash) must not change between view
kinds. Sequences therefore draw participant headers and footers with
the same shape machinery as topology boxes (0.25.6): a person-typed
participant carries the person glyph, a database the cylinder caps,
and the lifecycle dash comes from the shared style bank — only the
geometry (lifeline column, header band) is sequence-specific. Before
0.25.6 sequences took only the type's colours and invented a private
border convention ("4,3" init dash, fixed 4px radius), so the same
entity read differently across views (juju4 review: the sequence
"User" lost its person badge).

Audit (0.25.6): state views carry the same latent gap — state boxes
apply type colours but draw every state as a fixed-radius rounded
rect, ignoring the shape and border-radius channels. No corpus state
is person- or cylinder-typed today, so nothing renders wrong; the fix
lands with the state-renderer pass in ADR-003 (transition labels),
not in isolation.

**TODO: investigate zoom-level annotation.** C4's zoom-in hierarchy is
genuinely useful for readers -- seeing that "Juju" expands to client +
controller + agents at deploy time is a real insight. ggarch's `abstracts:`
relationship handles the model side (a concrete node realises an abstract one),
but there is no first-class way to annotate a diagram with "this is a zoom-in
of that node in the parent diagram" or to generate a breadcrumb trail. Explore
whether a `zooms-in-on: "parent_view"` attribute on a view, or a callout
annotation linking to a parent view, would satisfy this without importing C4's
prescriptive type hierarchy.

**TODO: infrastructure substrate types.** For reference architecture diagrams
showing MAAS + OpenStack + K8s + Juju + applications, a richer substrate
vocabulary is useful: compute (machine, pod, VM), network (space, subnet,
ingress, load balancer), storage (volume, bucket). These are orthogonal to
the process/actor/storage categories above -- they describe the infrastructure
a process runs on, not the process itself. The current `container` type
conflates compute boundary with software container; the rendering split
(see "Relationships and renderings" below) removes the pressure by
turning the compute boundary into a `deployed-on` edge and leaving
`container` as pure style. The complete list of recurring infrastructure
components worth standardising remains an open design question.

### Relationships and renderings: one fact, many drawings

*(Design direction -- nothing in this section is implemented yet. It
generalises containment and scope, and restructures the two sections
that follow.)*

**The problem in one sentence.** Today, the only way to say "the unit
agent runs on this machine" is to nest the agent inside the machine node
in the `nodes` block. The relationship (a fact about the system) and one
particular way of drawing it (a box inside a box) are welded together,
once, in the model, for every view.

**The idea in one sentence.** Facts live in the model as typed edges;
each view decides how to draw them.

**A worked example.** "This unit agent runs on that machine" is one
fact. Three views may draw it three ways:

- **Nesting** -- the agent box inside the machine box, in a deployment
  view. Says: "these things form one locality; zoom in here."
- **Arrow** -- a `deployed-on` edge in a control-flow view, drawn like
  every other arrow, in a story where software reaching infrastructure
  is causally load-bearing.
- **Tag** -- a small chip on the unit node ("on: m3") in an overview
  with thirty units. Says: "true, but don't stop the eye here."

The fact never changed. What changed is the rhetoric -- the same
authorial choice as bar order in a bar chart (see Motivation, "Position
is content"):

| Notation | Draws as | Says | Use when |
|---|---|---|---|
| long | containment | "one locality" | the grouping is the point |
| medium | arrow | "load-bearing link" | the flow is the point |
| short | tag | "true, but don't stop" | too many to draw |

**Design rules.**

1. **Nesting in the `nodes` block becomes sugar for an edge.**
   `machine { unit_agent }` desugars to a `contains` edge at parse time.
   The edge list stays the single source of truth; there is no second
   way to say "runs on."
2. **The nesting rendering requires N:1.** A box can be inside only
   one box. A relationship may therefore be drawn as nesting only if,
   in that view, each node has at most one container; the validator
   checks this per view. `controller -> cloud` ("knows") is
   many-to-many -- a cloud can be registered on several controllers --
   so it can never nest; arrow or tag only. This rule is what C4 never
   had, and it is why C4 needed a separate kingdom of deployment nodes
   governed by different rules.
3. **Each rendering declares its layout consequences.** Nesting
   participates in the constraint solve (children are placed inside the
   parent); arrows are routed around nodes; tags leave layout alone.
   Like `group-by:` regions, renderings are drawn, never distorting.

**What this does to node types.** Once containment is a rendering, the
`container` type loses its last hidden meaning (see the infrastructure
substrate TODO above). Types become pure style vocabulary -- which is
what the free-form string into the style grammar already wanted to be.
A node is a node: any node can contain, connect, and participate in
behaviours; what varies is how a view draws it.

**Edge labels obey the same principle.** "The unit agent runs the
charm" is what the edge is called at the topology level; "exec
dispatch" is what the same edge is called inside the hook execution
sequence. The edge is the fact; the label, like the rendering, is a
projection. See Open questions item 8.

### Truth kinds and edge families

A diagram tool for architecture documentation describes truths about a
product. Those truths come in three kinds, and ggarch's artifact kinds
line up with them:

| Truth kind | Question it answers | Canonical home | Juju example |
|---|---|---|---|
| structural | what exists, what is part of what | records + associations | application has units; model on cloud |
| interactional | what talks to what, over what wire | interaction edges | websocket, watcher, unix socket |
| operational | what happens over time | behaviours | bootstrap, deploy, integrate, remove |

This is the intent/persistence/execution triad at the tooling layer:
structure is the persistence face; interaction and operation are the two
halves of the execution face. It also gives "one model, many views" a
semantic footing: each view kind is the canonical home of one truth
kind. A data-model view is not a rival drawing of the system; it is the
projection of the structural kind.

**Two edge families, three truth kinds.** Associations (structural) and
interactions (behavioral) obey different rules, so they are two
families. The operational kind is not an edge family at all: it is a
temporal ordering *over* edges -- behaviours traverse interaction
edges, and record operations appear as steps. The family rule-sets:

- **Associations**: multiplicity-bearing, direction-by-convention,
  derivable from the schema's foreign keys. Eligible for the nesting
  rendering, subject to the N:1 rule. Never carry a protocol.
- **Interactions**: protocol-bearing (api, http, socket), sync/async
  semantics, genuinely directional -- "client calls controller" is not
  reversible typography. Never eligible for nesting. Never
  multiplicity-bearing.

The current grammar has one edge syntax with `type:` doing double duty;
whether the split becomes syntactic is a spike question. Spike verdict
(juju2): no -- the conceptual split plus `data` edges with multiplicity
labels carried the full record spine; the families stay one syntax.

**Association direction: FK vs semantic.** A foreign key is a column on
the many side pointing at the one side -- the FK arrow always points
child -> parent ("is part of"). Speech goes the other way: "an
application *has* units" (parent -> child). Both are true; they answer
different questions. A directed, labelled arrow forces a choice the
underlying fact does not make, so association edges should be read from
*multiplicity ends*, not arrowheads: the planned crow's-foot arrowheads
(Phase 9) are what dissolves the direction problem -- the glyph sits on
the many end, and either reading ("application has * units"
left-to-right, "unit belongs to one application" right-to-left) is
valid. Until the glyphs land, the convention is: draw in semantic
direction, carry multiplicity in the label ("has 1..N").

**The bridge must cover operations, not just entities.** Inspecting
juju.ggarch's edges against the schema found a middle class:
interactions whose *content* is structural. A watcher edge is a record
*read* (a standing subscription to record changes); a flush edge is a
*write*; a removal event triggers a life *transition*; Raft sync is
*replication*. `records:` as a node-to-node edge does not cover these.
Whether operations need grammar (edge attributes such as `watching:`)
or annotation is open -- spike evidence.

**Do not record-ify the wire.** The inverse failure mode: a websocket is
not a record and never will be. The three-kind table is the guard:
structure -> records, interaction -> edges, operation -> behaviours, and
nothing crosses except through a declared bridge.

Evidence caveat: this taxonomy generalises from one file (juju.ggarch).
The classes are clean there, and any stateful distributed system should
have schema, wires, and procedures -- but the juju2 spike is the test
of whether the three kinds and their bridges survive real authoring.

### Runtime/persistence duality

Every significant entity in a stateful distributed system has two faces: a
**runtime face** (the process, pod, or agent that runs) and a **persistence
face** (the record in the database that backs it). These faces appear in
entirely separate diagram types today -- topology diagrams show the runtime,
ER/schema diagrams show the persistence -- and the reader must mentally
connect them.

For Juju this connection is especially load-bearing. When an operator runs
`juju status`, what they see IS the model database projected at them. The unit
agent running on a machine corresponds to a `unit` record in a model database,
which lives in a specific model namespace, which is associated with a specific
cloud credential and cloud. An observability stack in model A on K8s and the
controller in model `controller` on MAAS are visually identical boxes in a
topology diagram -- but they are in completely different models with completely
different operational contexts. A reference architecture diagram for a complex
deployment (multiple models, multiple clouds, multiple operators) needs a way
to surface this.

No existing tool addresses this. The gap is not just missing notation -- it
reflects a deeper category that distributed systems documentation has not
formalised: **the record is the declared intent; the process is the
realisation**. This is the intent/execution separation showing up at the data
layer.

**Why surface the persistence face at all?** Three reasons, each
independent.

*Records are part of the software, not an external thing.* In Juju the
databases are not a neighbouring system the software talks to -- Dqlite
is embedded in the controller process, and the workers are record-driven:
a watcher is a standing request to be told when a record changes. A
topology that shows only processes shows the actors but not what they
know. It is half a picture of the software.

*`juju status` is (mostly) the records, projected.* The one command every
Juju user knows is largely a read-only projection of the model database
-- but not entirely: `lost` units and `executing` agents are live
connection state inferred by the controller, not stored rows, and
machine/model status is derived, not declared. "Status = the persistence
face" is a good teaching simplification, but a diagram built on it must
not claim the identity -- it fails precisely where reconciliation is
failing, which is when users look hardest. The bridge is real as an
overlap, not an equality: if diagrams show software and records as two
faces of one thing, the diagram and the command become two views of
overlapping facts.

*Multi-cloud and cross-model topology is record-shaped.* There is no
unit-to-unit wire between two integrated models: the two controllers
mediate -- the `external_controller` record exists precisely so the
local controller can authenticate and connect to the remote one -- and
each side's view of the other is maintained as records (`offer`,
`offer_connection`, the model record's cloud foreign key). The runtime
picture cannot draw the relationship itself; the record graph is the
only view where it is first-class. A data-model view is therefore not
schema documentation that happens to sit next to the architecture --
for cross-model, cross-cloud, and multi-controller concerns, it *is* the
architecture.

**A visual consequence worth naming.** Because every record lives in a
database inside the controller, a topology view that draws persistence
faces gets the star topology for free -- every `records:` edge converges
on the controller. "The database is the only place goal state lives"
stops being a prose claim and becomes visible structure.

**A design caveat.** Not every record is realised by a process.
Deployment records (`unit`, `machine`) have runtime faces; charm
declarations (`charm_relation`, `charm_action`) do not -- they are
*read* by the machinery, not realised by it. The persistence axis has
(at least) two edge semantics: realisation (`records:`) and read-access.
Start with realisation; add read-access only when a diagram needs it --
for example, the uniter reading charm declarations when dispatching.

**Implemented (0.21.0): `records:` as a node attribute.** `records:
"unit_rec"` on a runtime node links it to the record that backs it --
declared in the model, never in views, on the persistence axis
(`abstracts:` is its sibling on the abstraction axis). It delivers:
- Let topology views optionally surface persistence links ("show me
  the record behind everything in this view") as annotations or tags.
- Let data-model views show which runtime entities write each record.
- Be validated: the target must be a declared `record`-type node.

Two questions remain open before `records:` is committed:
- **Entity or edge?** The direction above assumes the record is a second
  entity linked by an edge. The alternative -- one entity, two faces,
  record-notation as a *rendering* of the same node rather than a
  separate node -- is arguably the more consistent completion of the
  renderings split, and has not been tested. The two views do have
  different edge sets (`unit_agent -> charm` is ipc;
  `unit_rec -> app_rec` is a foreign key), which is evidence in both
  directions.
- **Collective realisation.** A `relation` record is enacted by two
  applications' agents. Node-to-node `records:` expresses 1:1 (unit)
  and 1:N (application) realisation; N-party realisation has no
  expression yet.

The edges *between* record nodes -- the foreign keys -- are already
ordinary ggarch edges (the ER diagram is drawn with them). Together,
`records:` plus FK edges mean the model can *walk* from any running
process to the database row that backs it, and on to that row's model,
cloud, and controller. That walk is the key to provenance -- see the
next section.

### Provenance and scope: faceted tags, not buckets

Every deployed entity in a stateful system belongs to one or more scopes
simultaneously: a model, a cloud, an availability zone, a namespace, an
owner. Naively, you represent this by drawing bounding regions -- one box per
model, one box per cloud. This works when the groupings are clean and
non-overlapping. It breaks the moment a node belongs to multiple orthogonal
hierarchies at once, producing nested or intersecting regions that are harder
to read than the inline text they were meant to replace.

The failure mode is Dewey vs. Ranganathan. Dewey's decimal system forces each
book into exactly one hierarchical location; a book on "the mathematics of
music" must choose a home. Ranganathan's faceted classification assigns each
book a set of independent facets (subject, form, language, era) that can be
combined freely. The shelf -- the physical location, the bucket -- is a
rendering decision made from the facets, not a classification decision made at
authoring time. Buckets can be generated from tags; tags cannot be recovered
from buckets.

The Grammar of Graphics arrives at the same place from the other direction:
**faceting** -- subset entities by the values of a variable and draw a
boundary or a panel per value -- is a *rendering* decision in ggplot2
(`facet_wrap`), not a modelling decision. The planned `group-by: scope.X`
is a facet declaration; the scope chip is that value's scale/guide
rendering on the node itself.

Applied to ggarch, provenance is therefore not something you declare;
it is something the model *derives*. The unit agent's record has a
foreign key to its application's record, that record to its model's,
and the model's to its cloud. A node's provenance is a walk over real,
typed, cardinality-bearing relationships -- never a hand-written
address string.

This matters because the tempting notation for provenance -- an address
like `C1/c1/m1/a1` (controller, cloud, model, application) -- pretends
to be a tree, and the system is not one. Each `/` in that address is a
different relationship: the controller *knows* the cloud
(many-to-many), the model is *deployed on* the cloud (many-to-one), the
model *contains* the application (one-to-many), the application
*realises* the unit (one-to-many). The ground truth is the
entity-relationship diagram with its crow's feet -- a graph, not a
spine. Facets keep this honest: a facet is the value of one real
relationship, and where that relationship is many-valued (two
controllers know this cloud), the facet simply is a set, and the
nesting rendering is correctly unavailable for it.

This is consistent with how `environment:` already works -- a
view-level decision that resolves which concrete nodes to show. The
gaps:

1. `records:` is not implemented -- the runtime face and the
   persistence face are separate nodes with no link between them.
2. There is no derivation mechanism -- the FK edges exist in data-model
   views, but no query walks from a runtime node through its record to
   the values of its provenance relationships.
3. There is no tag rendering -- the current `scope: "c1/m1"` property
   draws a chip from a free-form string with a hash-derived color: a
   drawing with no fact behind it (and the hash is salted per process,
   so colors are not even stable across builds).

**TODO: derive facets from relationships.** Define a node's scope
facets as query paths over `records:` + FK edges, each facet named for
the relationship it walks (`scope.model`, `scope.cloud`). Free-form
`properties` remain for anything that is not a real relationship.

**Unblocked (juju2 spike):** the record nodes now exist across both
databases and `records:` links runtime to persistence; the walk is
traceable by hand. The query mechanism itself (scope.model as a
derived facet) is still to be built.

**TODO: tag rendering for edges.** The short notation from
"Relationships and renderings": a chip on the node showing the value of
a chosen relationship, colored by a declared scale with a generated
guide. Replaces the current string chip. Multiple relationships can
share a chip (multi-segment) or take one each.

**TODO: `group-by:` as generated buckets.** A view-level option that
renders every edge of a chosen type as a bounding region --
`group-by: scope.model` draws one region per model, from the same
relationship the tag rendering shows. Regions remain a rendering
choice, not a modelling one: authors with overlapping provenance use
tags instead.

**Proposed, not settled: relationship axes.** The earlier open question
-- whether `records:`, `abstracts:`, and scope facets are instances of a
general "relationship axis" concept -- has a candidate resolution: they
are typed edges, and what varies is the rendering. Closing it is
premature: the renderings split is unimplemented, the entity-vs-edge
question above is unresolved, and there is no golden standard to score
the result against. Closing rule (discovery, not scoring): re-author one
existing view under the new scheme -- the K8s deployment topology is
the natural candidate -- then answer two questions. Did the current
grammar force a misrepresentation (something nested that is not really
N:1 containment; something drawn as an arrow that is really membership)?
Does the new scheme express a fact the real documents need that the
current one cannot (records, cross-model relations)? Keep the
generalisation only if at least one answer is yes.

**Spike verdict (juju2, 0.21.0).** Both closing questions were answered
by building, not scoring. Misrepresentation: none found -- the
triple-encoded "runs on" turned out to be three views of three related
but distinct facts (locality = nesting, association = data edge,
operation = behaviour), which is what one-model-many-views is for, and
the direction-convention mixing was authoring, not grammar. Newly
expressible facts: yes -- the full provenance walk (unit ->
application -> model -> cloud) is traceable on one drawing, record
chips surface the persistence face in topology views, and the endpoint
indirection is un-flattened -- all in the CURRENT grammar. The
renderings split (nesting-as-sugar, per-view renderings) was not
needed for any of it: deferred, with an explicit trigger -- a view that
needs the same association drawn as containment in one view and as
arrow or tag in another. `records:` stays an attribute (it links
entities without claiming identity, which sidesteps entity-vs-edge
rather than settling it); the operations bridge stays deferred
(behaviour labels carry it informally); the edge families stay
conceptual, one syntax.

---



## Scope

ggarch is for **distributed systems architecture documentation**: deployment
topologies, control-flow sequences, data model schemas, and class/component
structures of software systems running on cloud or on-premises infrastructure.

**In scope:** anything you would reasonably put in an architecture document for
a distributed system -- topology diagrams, sequence diagrams, ER/schema
diagrams, class diagrams, state machines, deployment environment views. After
phases 8–12 of the implementation plan, ggarch offers full expressive parity
with existing docs-as-code tools for this domain, with better layout guarantees
(Cassowary constraints) and stronger model consistency (single declared model,
all views derived from it) than any current alternative.

**Out of scope, permanently:** Gantt charts, git graphs, mindmaps, kanban
boards, BPMN process diagrams, mathematical/EBNF notation, packet/bit-field
wire formats, interactive walkthroughs, and programmatic model generation from
source code. These belong to different problem domains (project management,
version control, formal languages, interactive UX) or require dependencies and
execution models that conflict with ggarch's lightweight and secure-by-design
principles. See ADR-001 for the full rejection reasoning.

---


## Motivation

Every mainstream text-based diagram tool (Mermaid, D2, Graphviz, PlantUML)
conflates three concerns in a single syntax:

1. **What nodes exist and what they are**
2. **Where nodes are positioned**
3. **How nodes relate to each other**

The layout engine then infers positions from edge structure, which means
spatial intent is routinely overridden by global edge-crossing optimisation.
Annotations (dashed boxes, callout labels, region shading) have no first-class
home and either distort layout or don't exist at all.

But there is a deeper problem that no general-purpose tool addresses: **a
distributed system is not one diagram, it is a system that can be viewed from
many angles**. The same controller, unit agent, and charm appear in a
deployment topology, a control-flow diagram, a data-model diagram, and a
sequence diagram. Every existing tool makes you re-declare these entities for
each diagram, which means the diagrams diverge over time and an agent or reader
cannot tell that the "controller" in the topology is the same entity as the
"Controller" lifeline in the sequence diagram.

The closest existing tools are **Structurizr** (C4 model/view separation,
native deployment cardinality) and **Ilograph** (single-file declare-once,
multi-perspective with composable sequence views). Both score 3-4 out of 6 on
the capabilities distributed systems documentation actually requires. The two
universal gaps across every existing tool:

- **Lifecycle/temporal node properties** -- no tool natively models 'runs once
  at startup and exits' vs 'runs continuously'. This distinction is central to
  understanding systems like Juju (init containers, bootstrap sequences) and
  has no representation anywhere.
- **Cross-cutting semantic annotation regions** -- no text-based tool lets you
  draw a semantic boundary (e.g. 'intent & persistence') that cuts across a
  containment hierarchy without distorting layout or remodelling the tree.

ggarch addresses all of this by separating a diagram into independent,
composable layers -- the same insight that made ggplot2 productive for
statistical graphics -- and by making the system model a first-class,
separately declared artefact that all views share.

### Position is content

The criticism above -- layout engines that override spatial intent -- rests
on a claim worth making explicit: **in an architecture diagram, position is
content, not presentation**. "Controller in the centre, clouds as wings,
charmed apps to the right" is part of the diagram's argument; two diagrams
with identical nodes and edges but different arrangements say different
things.

The Grammar of Graphics handles this differently, and the difference is
instructive. In ggplot2, position is an aesthetic: x and y are derived from
data via scales. But even there, the *ordering* of a discrete scale --
which bar comes first -- is a narrative decision the author can and does
make (`factor(x, levels = c("v1", "v2", "v3"))`). Any order would be
"correct"; the chosen order is what makes the story land. ggarch extends
this from one axis of a bar chart to the whole canvas: the arrangement is
the pacing and chunking of the story, the difference between a list of
facts and a told story. This is why auto-layout must be a default that
produces a coherent, readable arrangement when the arrangement is not
load-bearing -- not a system with authority over arrangement. Where the
arrangement *is* load-bearing, the author declares it, and the solver's
job is to honour it exactly.

There is a second, deeper parallel. In ggplot2, the data frame is the
single source of truth and the plot is a projection that can never diverge
from it. In ggarch, the model is the goal state and the views are
projections of it -- the same intent/execution separation the Juju
architecture document describes for the controller database. Views cannot
drift from the model because they have no independent existence;
single-model multi-view consistency is a structural guarantee, not a
discipline.

**Auto-layout as default (0.25.0).** When the arrangement is not
load-bearing, the author omits the positions block entirely and gets a
coherent, readable layout: columns follow topological depth along the
visible edges (the main flow runs left-to-right, honouring edge
direction), nodes that share a column stack vertically in declaration
order, container children follow the container auto-layout, and cycles
are tolerated (back edges become floors). Edge endpoints resolve to
their top-level ancestors among the selected nodes, so edges between
containers' children drive the containers' placement (a Raft mesh
between Dqlite nodes lays out the controller nodes); the per-edge pair
constraints are declared at the effective (deepest distinct) endpoints,
matching the label-gap pass's pair-local resolution. Views that
declare any positions at all are untouched -- auto-layout is the floor,
not the ceiling. Staged: per-node override (auto nodes inside a
partially-declared view) is future work, triggered by a real case.

---

## Comparison

The table below scores eight capabilities against the tools most commonly used
for architecture documentation. Each capability is defined under the score.

A high score means parity with existing tools -- a floor, not a
ceiling: it says nothing about adequacy for a domain where no tool has
ever been adequate (see Background).

| Capability | Mermaid | D2 | Graphviz | PlantUML | Structurizr | Ilograph | **ggarch** |
|---|:---:|:---:|:---:|:---:|:---:|:---:|:---:|
| 1. Multiple views of one model | ✗ | ✗ | ✗ | ✗ | ✓ | ✓ | **✓** |
| 2. Constraint-based layout | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** |
| 3. Typed edges (semantic) | ✗ | ~ | ✗ | ~ | ~ | ✗ | **✓** |
| 4. Lifecycle and cardinality | ✗ | ✗ | ✗ | ✗ | ~ | ✗ | **✓** |
| 5. Sequence from same model | ✗ | ✗ | ✗ | ~ | ~ | ✓ | **✓** |
| 6. Cross-layer edges | ✗ | ✓ | ✓ | ~ | ✗ | ✓ | **✓** |
| 7. Types vs instances | ✗ | ✗ | ✗ | ✗ | ✗ | ✗ | **✓** |
| 8. Abstraction relationships | ✗ | ✗ | ✗ | ✗ | ~ | ✗ | **✓** |

✓ full support · ~ partial or workaround · ✗ not supported

---

### 1. Multiple views of one model

A system's nodes and edges are declared once. Any number of views -- topology,
sequence, data model, control flow -- draw from the same declaration. Renaming
a node renames it in every view automatically. Diagrams cannot drift out of
sync with each other because they share one source of truth.

**Mermaid / D2 / Graphviz / PlantUML:** Each diagram is a self-contained
document. Nodes and edges must be re-declared per diagram. Nothing prevents
the "Controller" box in one diagram from silently diverging from the
"controller" lifeline in another.

**Structurizr:** The C4 model/view separation is the closest prior art.
A workspace declares elements once; views select from them. The model is
genuinely shared. Gaps: the C4 model is hierarchical (Person → Software System
→ Container → Component) and every element must fit that hierarchy; free-form
node types are not supported.

**Ilograph:** Single-file declare-once with multiple perspective views,
including sequence views. The shared model is real. Proprietary format and
renderer; no open-source implementation.

---

### 2. Constraint-based layout

Node positions are determined by explicit spatial constraints
(`A left-of B gap: 40`, `C above D`, `E align-middle F`) solved by a
constraint solver (Cassowary). The author's spatial intent is guaranteed —
it cannot be overridden by an edge-crossing optimiser. Constraints compose:
adding a new node does not disturb the rest of the layout.

**All other tools:** Positions are inferred from edge structure. Graphviz,
Mermaid, PlantUML, and D2's ELK backend all run global optimisers that
trade spatial intent for crossing minimisation. The author can nudge but not
guarantee. D2's `near` keyword is a hint, not a constraint.

**Solver invariants (0.24.1, found while authoring the controller worker
tree).** Three behaviours an author must know, one fixed from friction
evidence:

- The first node in a view's `select` is anchored at (0, 0) with WEAK
  priority — the layout's origin. Make it the intended top-left node.
- Leaf node width and height are pinned at their natural (label-derived)
  size with STRONG priority. Before 0.24.1 width was unpinned: when the
  anchored first node also carried a required `align-centre`, the free
  width variable silently absorbed the conflict and the node ballooned to
  twice its centre offset. Three committed juju2 views had silently
  ballooned boxes (e.g. "Worker tree (machine cloud)"'s controller node
  at 197.6px for a 104px label) before this was found.
- **Label contract (0.25.4, ADR-002: strike avoidance).** Label
  placement is enforced by the solver, not left to authoring. solve()
  runs in two phases: the declared constraints solve first; then every
  labelled visible edge is measured through the renderer's own
  `label_geometry` (its longest leg, its wrap at the leg-minus-side-
  padding budget, its one-sided strip) and each measured strike
  reserves, at STRONG priority, clearance, re-solved against WEAK
  stays pinning the phase-one solution — only measured shortfalls
  move anything. Required constraints outrank the reservations, so an
  authored arrangement that cannot spare the clearance keeps the
  struck label rather than erroring. Reservations: a word wider than
  the leg reserves the word's width on the leg's dominant axis; a
  strip that would strike a node the stroke itself clears reserves
  the strip's perpendicular clearance; a strip that would cross its
  own container's padded wall grows the container. Labels no longer
  need on-axis room (the stroke is never cut), so authored-gap floors
  shrink to the widest word plus side padding and reservations are
  narrower than the 0.25.3 gap-mode ones. Label-vs-label clashes are
  measured by the audit (the step-3 router baseline; strips as the
  collision currency) — classification at 0.25.4: 11 of 16 involve
  diagonal legs (alignment step 2 / router step 3), 2 are the HA
  anti-parallel rows under REQUIRED constraints, the rest sit in
  crowded hub clusters where solver pushes cascade. The 0.24.1
  pair-local authoring rule below is superseded as a REQUIREMENT —
  it remains good practice for deliberate spacing.
- Label-gap resolution is pair-local, not transitive: a labelled edge
  whose endpoints have no *directly declared* spatial constraint (even
  if linked through a chain) gets its clearance from the measured
  label contract above, not from the declared-chain expansion.
  Before 0.25.3 the fallback here emitted both-direction horizontal
  STRONG separation — an error-minimising no-op on any separated
  pair — which is why stamped-subtree internals kept 20px child gaps
  with floating labels in both the authored and auto-layout twins.

---

### 3. Typed edges (semantic)

Every edge has a `type` drawn from a declared taxonomy with a defined meaning:
`api` (RPC/REST), `stream` (long-lived websocket/gRPC), `event` (one-way
notification), `data` (database read/write), `control` (process lifecycle),
`ipc` (Unix socket/pipe). Types are not just visual styles -- they carry
meaning. The type is part of the model and can be queried. Custom types can
be declared in the `style` block.

**Mermaid / Graphviz / Ilograph:** Edges have no semantic type. Visual
appearance (colour, dash pattern) can be customised, but there is no
queryable meaning attached. Readers must infer semantics from labels alone.

**D2:** Edge shapes and styles are customisable; a loose convention of arrow
labels conveys semantics. No formal type system.

**PlantUML / Structurizr:** Relationship stereotypes or technology annotations
exist but are free-form strings, not a closed enumerated taxonomy.

---

### 4. Lifecycle and cardinality

**Lifecycle** declares the temporal behaviour of a node:
`persistent` (runs continuously), `init` (runs once at startup then exits),
`ephemeral` (runs on demand then exits). Rendered as a visual cue (solid,
dashed, or dotted border). Central to understanding init containers, bootstrap
steps, and on-demand hook dispatch.

**Cardinality** declares multiplicity: `one-per-deployment`, `one-per-model`,
`one-per-application`, `one-per-unit`, `one-per-host`, or an integer. Rendered
as a badge. Lets a single node declaration represent "this runs once per unit
in a live deployment" without instantiating N copies.

**All other tools:** No tool natively models lifecycle. Cardinality exists in
Structurizr (deployment nodes can have `instances`) but is purely visual and
does not compose with the view system.

---

### 5. Sequence diagrams from the same model

A `sequence` view references the same model nodes as a `topology` view.
Lifelines are not re-declared; they are the same entities resolved from the
model. A behaviour -- a named sequence of `call`, `return`, `async`, `loop`,
and `alt` steps -- is declared in the model and rendered by the sequence view.
Renaming a node renames its lifeline in every sequence automatically.

**Mermaid:** Sequence diagrams are first-class and widely used, but entirely
separate from any topology diagram. Participants are re-declared inline.

**PlantUML:** Sequence support is mature; participants are re-declared per
diagram with no shared model.

**Structurizr:** Dynamic views show interaction but use a separate element
declaration; infrastructure nodes cannot be participants.

**Ilograph:** Perspectives include sequence-like interaction views over the
shared model. The closest prior art for this capability.

---

### 6. Cross-layer edges

Any declared node can be an edge endpoint or a behaviour participant,
regardless of its type. Infrastructure nodes (`type: external`,
`type: container`, a Kubernetes cluster) connect to software nodes. "K8s
schedules controller pod" and "bootstrap installs jujud" are first-class
edges, not workarounds. This makes bootstrap and provisioning sequences fully
expressible.

**Mermaid / PlantUML:** No formal layers; any node can connect to any other.
The gap is the absence of a shared model (capability 1), not connection
restrictions.

**D2:** No layer restrictions. Cross-layer connections work. The gap is
elsewhere (no shared model, no constraint layout).

**Structurizr:** C4 layers implicitly forbid certain connections. A
deployment node cannot be a participant in a dynamic view. Infrastructure
and software exist in separate diagram types with no shared participants.

---

### 7. Types vs instances

Model nodes are *types*, not unique instances. A node declared with
`cardinality: one-per-unit` represents a type that exists N times in a live
deployment. A view can render that type as a single abstract archetype box
*or* as N labelled instances -- the same declaration, two rendering modes.
Instance labels are specified in the view, not the model.

**All other tools:** Every declared element is a unique instance. To show
two application units with the same software, two separate elements must be
declared. They are visually and semantically unrelated even if they share
every property. Structurizr's `instances` on deployment nodes is the closest
approximation but does not compose with the view system.

---

### 8. Abstraction relationships

The `abstracts:` attribute declares that a concrete node is the runtime
realisation of one or more abstract nodes. `controller_pod [abstracts:
"controller"]` means the pod is the concrete deployment of the abstract
controller. This relationship is formal, not visual:

- Edges declared using the abstract id remain valid -- the validator accepts
  them as covered by the concrete node.
- Abstract ids can be used in overview diagrams; concrete ids in topology
  diagrams. The model knows they are the same entity at different zoom levels.
- Adding a behaviour step that uses an abstract id not covered by any concrete
  node is a validator error -- silent drift is caught at authoring time.

**All other tools:** No tool has a formal abstraction relationship. The
standard workaround is to duplicate the element at each zoom level and rely
on naming convention to keep them in sync. Structurizr's C4 hierarchy
(`SoftwareSystem` contains `Container` contains `Component`) encodes zoom
levels structurally but cannot express that two separately declared elements
at different levels are the same thing.

## Feature parity

Four capabilities were identified by surveying twelve competing tools and
filtering the raw gap list through the question: *what design principle
generalisation makes this capability fall out?*

The decision -- what is in scope, what is out of scope, and why -- is recorded
in [ADR-001](adr/001-feature-parity-via-principle-generalisation.md).

The four in-scope gaps, each derived from a principle generalisation:

1. **Node structure** -- nodes may declare named fields; `type: record` renders
   as table rows, `type: class` as UML compartments; edge endpoints may be
   field-qualified for per-field port anchoring.
2. **Richer behaviour steps** -- a behaviour is an interaction graph, not
   just a sequence; a `state` view renders it as a state machine. `guard`
   and `on` (trigger) are additive step attributes.
3. **Structured metadata** -- any model entity may carry a `properties` map
   and a `url`; a `legend` annotation renders the style block as a visual key.
4. **Deployment environments** -- an `environment` block in the model declares
   node presence and abstract-id resolution per environment; already specced
   in the grammar, not yet implemented.

Out of scope: Gantt, git graphs, mindmaps, kanban, BPMN, mathematical
notation, packet/bit fields, interactive walkthroughs, programmatic
generation. See ADR-001 for the rejection reasoning.

## Capability reference

Detailed syntax and behaviour for each capability. The table in the
Comparison section gives the one-line summary; this section gives the
full specification.

### 1. Multiple views of one model

A system is declared once in a `model` block. Views reference it. The
controller in the topology view and the Controller lifeline in the sequence
view are the same declared entity -- not two drawings that happen to share a
label. Views can be topology, control-flow, data-model, or sequence; all draw
from the same model.

### 2. Typed edges

Edges have a semantic `type` drawn from a declared taxonomy. Types are not
just visual styles -- they carry meaning that can be queried. Built-in types
for distributed systems:

- `api` -- RPC or REST over a network protocol
- `stream` -- long-lived connection (websocket, gRPC stream)
- `event` -- one-way notification
- `data` -- data read/write (database, object store)
- `control` -- process control (exec, signal, lifecycle management)
- `ipc` -- local inter-process (Unix socket, pipe, shared memory)
- `pebble` -- Pebble HTTP API (Juju-specific; illustrates custom types)

Custom types can be declared in the `model` and mapped to styles.

### 3. Lifecycle and cardinality on nodes

Every node can declare:

- `lifecycle: persistent | init | ephemeral`
  - `persistent` -- runs continuously (default)
  - `init` -- runs once at startup, then exits (K8s init containers, bootstrap
    steps)
  - `ephemeral` -- runs on demand, exits (hook dispatch, one-off jobs)
- `cardinality: one-per-deployment | one-per-model | one-per-application |
  one-per-unit | one-per-host | N`
  -- expresses the multiplicity of the entity in a live deployment. Rendered
  as a badge or visual multiplicity cue. Queryable from the JSON export.

Lifecycle maps directly to visual grammar: init nodes render with a dashed
border by default; ephemeral nodes with a dotted border. Both can be
overridden in the style layer.

### 4. Cross-cutting annotation regions

The `annotations` layer draws semantic regions on top of the solved layout
without participating in layout at all. A region can span any set of nodes
regardless of their position in the containment hierarchy. This is how
'intent & persistence boundary' and 'execution boundary' are expressed —
as annotations, not containers.

Multiple annotation sets can be defined and rendered selectively, giving
different 'lenses' onto the same base diagram.

### 5. Composable sequence diagrams

A `sequence` view references the same model entities as a `topology` view.
The lifelines in a sequence diagram are not re-declared -- they are the same
nodes, resolved from the model. This means a sequence diagram is automatically
consistent with the topology: renaming a node in the model renames it in every
view.

Sequence steps support: `call`, `return`, `async`, `loop`, `alt` (condition
branches). The unit agent's wait/snapshot/resolve/dispatch/commit loop, the
bootstrap sequences for K8s and machine clouds, and the hook execution sequence
in the Juju docs are all expressible as sequence views over the same model.

### 6. Deployment environments as views

A system can be deployed in multiple environments (Kubernetes, machine cloud,
LXD). These are not separate systems -- they are different deployment views of
the same model. ggarch treats them as `environment` variants, each specifying
which nodes are present and how they map to infrastructure. The K8s topology
and machine topology of Juju are two environment views of one model, not two
separate pictures.

### 7. Types vs instances -- the same software deployed many times

Structurizr treats every declared entity as unique. To show two application
units with the same software, you had to declare `App1Charm` and `App2Charm`
as separate containers -- abandoning the declare-once principle and making them
visually unrelated despite being the same software.

In ggarch the model's `nodes` block declares *types*, not instances. A node
with `cardinality: one-per-unit` is a type that exists N times in a live
deployment. A view can render that type as:

- A single abstract box (the archetype) -- for diagrams where you want to show
  the structure without committing to a specific number of instances
- N labelled instances -- for diagrams where the specific instances matter
  (e.g. "App 1 / Unit 0" and "App 2 / Unit 0")

```
// In the model -- declared once
unit_pod [type: container, label: "Unit pod", cardinality: one-per-unit] {
  unit_agent [type: juju-software, label: "Unit agent"]
  charm [type: charm, label: "Charm"]
  workload [type: workload, label: "Workload"]
}

// In a view -- render two specific instances
diagram "Two-application deployment" from "Juju" {
  select {
    nodes: controller_pod unit_pod
    instances: unit_pod [
      { id: app1_unit0, label: "App 1 / Unit 0" },
      { id: app2_unit0, label: "App 2 / Unit 0" }
    ]
  }
  positions {
    app1_unit0 left-of app2_unit0 gap: 40
    app1_unit0 below controller_pod gap: 60
    app2_unit0 below controller_pod gap: 60
  }
}
```

The charm type is declared once. Its label, lifecycle, cardinality, and style
are defined once. Individual instances inherit everything and can optionally
override their label in the view. Renaming the type renames all instances.

Since 0.22.0, instances are full subtree stamps with edge expansion;
since 0.23.0 the expansion has an explicit pairing vocabulary:

- **zip** (default): an edge between two archetype children is copied
  per instance, instance i wired to instance i -- the internal wiring
  that repeats verbatim in every copy.
- **fan**: an edge from outside an instanced subtree connects to every
  instance -- star wiring.
- **mesh** (`pairing: mesh`): an edge between copies -- every distinct
  pair, never a copy with itself. Full mesh is the truth for peer
  sync (e.g. Raft replication: the leader replicates to all peers; a
  drawn "ring" is a crowding convention).

Multiple `instances:` clauses accumulate (one per instanced type).

Known gap: specific declared pairs (a chain, an asymmetric topology) --
"only copy 1 to copy 2" -- cannot be expressed. The honest answer when
a real case appears is view-level edges; deferred (see the ggarch
HANDOFF).

### 8. Cross-layer edges -- software to infrastructure

Structurizr's C4 layers (Person / Software System / Container / Component)
are architectural zoom levels, not semantic types, and they implicitly forbid
certain connections. Dynamic views could not use deployment or infrastructure
nodes as sequence participants at all. "Provider provisions machine",
"Kubernetes schedules pod", "bootstrap installs jujud" are real statements
about how systems work -- but C4 has no representation for them.

In ggarch there are no artificial restrictions on what can connect to what.
Infrastructure nodes are declared in the model the same way as software nodes
(`type: infrastructure`, `type: cloud`, `type: k8s-cluster`). Any declared
node can be an edge endpoint or a behaviour participant. The only constraint
is that both endpoints are declared in the model. "K8s schedules controller
pod" is a `control` edge from `k8s` to `controller_pod`, declared in `edges`
and reusable in any `behaviour` that involves provisioning.

This makes bootstrap sequences fully expressible: the behaviour participants
include both the software being installed and the infrastructure doing the
installing, connected by the same declared edges.

### 9. Selective zoom -- mixing levels of detail in one view

Structurizr's C4 levels enforce uniform zoom. At container level, every system
opens to its containers; at context level, everything is a blob. You cannot
show the controller as a single opaque box while simultaneously showing the
unit pod fully expanded -- even though this is often exactly what a diagram
needs. The interesting detail is in one place; the rest is context.

In ggarch, `expand` and `collapse` are per-node instructions in the view's
`select` block. By default a node renders at the depth it has in the model.
`collapse` closes a container to a single box regardless of whether it has
children. `expand` opens it to show all children. You mix freely in one view.

```
diagram "Unit focus" from "Juju" {
  select {
    nodes: controller_pod unit_pod
    collapse: controller_pod   // opaque -- context only
    expand: unit_pod           // fully open -- show all children
  }
  positions {
    controller_pod above unit_pod gap: 80
  }
}
```

This means a single diagram can simultaneously show high-level context (the
controller as a blob) and fine-grained detail (the unit pod's internal
structure) -- without requiring separate diagrams or a zoom/drill-down
interaction. The reader sees the relationship between the two levels of
abstraction in one picture.

### 10. Abstraction relationships -- surviving multiple zoom levels

When a system is documented at multiple levels of abstraction (e.g. "Controller"
in an overview and "Controller pod" in a deployment topology), the model would
normally accumulate parallel nodes with no formal relationship. A change at
one zoom level doesn't propagate to the other -- silent drift.

The `abstracts:` attribute declares that a concrete node is the realisation of
one or more abstract nodes. This is a model-level relationship, not a visual one.

```
nodes {
  controller     [type: juju-software, label: "Controller"]    // abstract
  controller_pod [type: container, label: "Controller pod",
                  abstracts: "controller"] {                   // concrete
    jujud [type: juju-software, label: "jujud"]
  }
}
```

**What `abstracts` enables:**

- **Edge validity** -- edges and behaviour steps declared using `controller`
  are valid even though only `controller_pod` is a declared node. The
  validator accepts abstract ids that are covered by at least one `abstracts:`
  relationship.
- **Consistent renaming** -- `controller` can be used in overview diagrams
  and `controller_pod` in topology diagrams. They are the same thing at
  different zoom levels. The model knows this; diagrams don't have to.
- **Drift detection** -- if you add a new behaviour step using `controller`
  and forget to update the concrete deployment model, the validator catches
  it immediately (no concrete node abstracts the id).
- **Queryable** -- `model.abstractions_map()` returns `{abstract_id: concrete_id}`
  for programmatic queries and agent tooling.

A node can abstract multiple ids: `abstracts: "controller model_agent"`.
Multiple concrete nodes can abstract the same abstract id (K8s controller pod
and machine controller both abstract `controller`).


## Core idea: model and views

### The model is complete

A ggarch file contains one `model` block and one or more view blocks. The
model is the single source of truth for everything the system *is* and
*does*. It has four sub-blocks:

```
model "Juju" {
  nodes { ... }      // what exists: types, lifecycle, cardinality
  edges { ... }      // relationships: semantic types, protocols
  behaviours { ... } // named interaction sequences between model entities
  style { ... }      // visual grammar for node types and edge types
}
```

**The strict rule: everything that describes the system belongs in the model.
Views may not introduce new system facts.** A view that declares a node, edge,
or interaction step that does not exist in the model is a parse error.

This is the principle Structurizr stated but did not enforce. Structurizr's
`dynamic view` re-declared interaction steps at the view level -- breaking
declare-once and making sequence diagrams orphans that diverged silently from
the model. In ggarch, `behaviour` blocks in the model are first-class
declarations on equal footing with `nodes` and `edges`. Views project
behaviours; they do not define them.

### Views are projections only

A view selects from the model, controls spatial layout, and adds visual
annotations. That is all it can do.

```
// Topology view -- selects nodes, declares positions and annotations
diagram "K8s deployment" from "Juju" {
  select {
    nodes: controller_pod unit_pod
    edges: type api type stream   // filter by edge type
    environment: kubernetes
  }
  positions { ... }    // spatial constraints for this view only
  annotations { ... }  // overlaid regions and callouts for this view only
}

// Sequence view -- selects a behaviour, optionally filters participants
sequence "Hook execution" from "Juju" {
  select {
    behaviour: "hook execution"
    // participants: unit_agent charm controller  // optional filter
  }
  annotations { ... }  // optional: highlight regions on the sequence
}

// Environment view -- same model, different deployment surface
diagram "Machine deployment" from "Juju" {
  select {
    nodes: controller_machine unit_machine
    environment: machine
  }
  positions { ... }
}
```

Views have exactly three optional blocks: `select`, `positions`, `annotations`.
No `nodes`. No `edges`. No `behaviours`. No `style`. If a view needs to show
something not in the model, the model must be extended -- not the view.

This means:
- Renaming a node in the model renames it in every view and every behaviour
  automatically.
- A sequence view and a topology view that reference the same model entities
  are provably consistent.
- The JSON export of the model is a complete, queryable description of the
  system independent of any rendering.
- An agent reading the model block understands the full system; an agent
  reading a view block understands only a perspective on it.

**Design note -- view keyword unification (TODO):** The current grammar uses
separate keywords for different rendering modes: `diagram` for topology/ER/class
views, `sequence` for interaction views, `state` for state machine views. This
encodes the rendering mode in the keyword rather than deriving it from the
select content -- the wrong level of abstraction. A topology view and a sequence
view are both projections of the same model; they should both be introduced by
the same keyword. The rendering mode is fully determined by what the `select`
block contains: `behaviour:` implies sequence rendering; `nodes:`/`positions:`
implies topology rendering; `state:` implies state machine rendering. The unified
grammar would be:

```
view "K8s deployment" from "Juju" {
  select { nodes: controller_pod unit_pod
           edges: type api type stream }
  positions { ... }
}

view "Hook execution" from "Juju" {
  select { behaviour: "Hook execution" }
}
```

The Sphinx directive already implements this at the surface level -- `:view:`
resolves to whichever type matches the name. The grammar and parser still use
separate keywords. See Open questions item 7.


### Layers within a diagram view

When a `diagram` view is rendered, layers are evaluated in this order:
1. `select` -- filter model nodes and edges for this view
2. `positions` -- constraint solver produces node coordinates
3. edge routing -- uses solved positions, never influences them
4. `annotations` -- drawn last, on top, without affecting layout


## Design principles

### Secure by design

- **No code execution.** The diagram source is a pure data declaration. The
  parser produces a data structure; the renderer draws SVGs. No `eval`, no
  shell calls, no dynamic imports, no execution of diagram content as code.
- **No network calls.** Diagrams compile fully offline at build time. No
  calls to external rendering services (no Kroki, no CDN).
- **SVG safety.** All user-provided strings are escaped before embedding in
  XML. The renderer never emits raw user content into SVG attribute values or
  text nodes.
- **Minimal, audited dependencies.** Four dependencies: `lark` (parser),
  `kiwisolver` (constraint solver), `drawsvg` (SVG generation), `sphinx`
  (extension host). All MIT or BSD licensed. No binary builds, no npm, no
  Node.js, no headless browser.
- **Constrained file access.** The Sphinx extension reads only the fenced
  block content and writes only to the Sphinx `_build` directory. No file
  system traversal, no reading arbitrary paths from diagram source.

### Lightweight by design

- **No binary dependencies beyond Python.** `kiwisolver` is a small C
  extension already present in any environment that has matplotlib. Effective
  new dependencies are `lark` and `drawsvg` only.
- **No runtime infrastructure.** No Node.js, no headless browser, no
  Playwright, no Docker. Diagrams build wherever Python builds.
- **Fast compilation.** Parse → solve → render targets under 50ms per diagram,
  comparable to D2.
- **Offline first.** Installing the package is sufficient. No API keys, no
  login, no license server calls at build time.

### AI-friendly by design

- **Readable source.** The five-layer syntax is unambiguous to parse without
  running the tool. An agent reading a `{ggarch}` fenced block understands the
  diagram completely from the text: what nodes exist, their spatial
  relationships, the edges that connect them, and the annotations that
  overlay them. No implicit inference from edge structure required.
- **Generatable source.** An agent can write a valid ggarch diagram from a
  prose description. Every spatial decision is explicit in the positions layer
  -- there are no implicit defaults that require knowing the layout engine's
  internals. "Controller is in the centre, clouds is to its left, apps is
  below" translates directly to position constraints.
- **Required alt text.** The `:alt:` option is required, not optional. It
  emits a full prose description in the markdown/llms output so agents reading
  the page see the diagram's information content even in text-only rendering.
  A baseline alt text is auto-generated from nodes and edges if the author
  does not provide one, but the author's version takes precedence.
- **Diagrams as data.** Because the five layers are cleanly separated, the
  parsed diagram is a queryable data structure. A JSON export is a first-class
  output format alongside SVG. An agent or tool can answer: "which nodes are
  inside the intent & persistence annotation?", "what edges cross the execution
  boundary?", "which nodes have type juju-software?" without rendering the
  diagram at all.

---

## Layer 1: nodes (in the model)

Declares what exists. Nodes have an id, a label, a type, an optional
lifecycle, and an optional cardinality. Types map to the style grammar.
Nesting creates containment. These are declared in the `model`, not per
diagram -- so every view shares the same node definitions.

```
nodes {
  user [type: person, label: "User"]

  controller_pod [type: container, label: "Controller pod",
                  cardinality: one-per-model] {
    jujud [type: juju-software, label: "jujud",
           cardinality: one-per-model]
    config_seed [type: juju-software, label: "controller-config-seed",
                 lifecycle: init, cardinality: one-per-model]
    charm_init [type: juju-software, label: "charm-init",
                lifecycle: init, cardinality: one-per-model]
    apiserver [type: juju-software, label: "API-server container",
               cardinality: one-per-model]
    pebble [type: pebble, label: "Pebble",
            cardinality: one-per-unit]
  }

  unit_pod [type: container, label: "Unit pod",
            cardinality: one-per-unit] {
    unit_agent [type: juju-software, label: "Unit agent (containeragent)",
                cardinality: one-per-unit]
    charm [type: charm, label: "Charm",
           lifecycle: ephemeral, cardinality: one-per-unit]
    workload [type: workload, label: "Workload container",
              cardinality: one-per-unit]
  }
}
```

Node attributes:
- `type` -- maps to the style grammar; also used to filter nodes into views
- `label` -- display text; `\n` for line breaks
- `lifecycle: persistent | init | ephemeral` -- persistent (default) renders
  with a solid border; init with a dashed border; ephemeral with a dotted
  border. Can be overridden in the style layer.
- `cardinality: one-per-deployment | one-per-model | one-per-application |
  one-per-unit | one-per-host | N` -- rendered as a badge or multiplicity cue;
  queryable from JSON export
- `abstracts: "id1 id2 ..."` -- space-separated list of abstract node ids this
  concrete node realises. Enables edges and behaviour steps to use the abstract
  id while the concrete node is declared. See capability 10.
- `records: "unit_rec"` -- id of the record node that backs this runtime
  node (its persistence face). Validated: the target must be a declared
  `record`-type node. Rendered as an amber `rec: <id>` chip at the node's
  bottom-left. Implemented in 0.21.0; see "Runtime/persistence duality".

Nodes are pure model declarations -- no position, no edges. Containment is a
visual grouping hint; it does not imply edges or constraint priority.

---

## Layer 2: positions (in views)

Declares spatial constraints. The constraint solver (kiwisolver/Cassowary)
produces x/y coordinates that satisfy all constraints. Constraints are
relative, not absolute. Constraints are strict -- a conflict is an error, never
a silent override.

```
positions {
  // Cardinal placement
  clouds left-of juju gap: 60
  charmhub right-of juju gap: 60
  app1 below juju gap: 80
  user above juju gap: 60

  // Alignment
  clouds align-middle juju    // vertical centre aligned
  charmhub align-middle juju

  // Containment layout (how children are arranged inside a container)
  app1 direction: right
  juju direction: right

  // Size hints (optional; defaults to label size + padding)
  juju min-width: 120
}
```

Supported constraint types:
- `left-of`, `right-of`, `above`, `below` -- cardinal placement, optional `gap`
- `align-top`, `align-bottom`, `align-left`, `align-right`, `align-middle`,
  `align-centre`
- `same-width`, `same-height`, `same-size`
- `direction: left | right | up | down` -- layout direction for children
- `grid: rows cols` -- arrange children in a grid

---

## Layer 3: edges (in the model)

Declares relationships between model nodes. Edges carry a semantic `type`
in addition to a label. Edge types are not just visual -- they are queryable
and can be filtered by type in a view's `select` block.

```
edges {
  user -> controller [type: api, label: "declares intent"]
  client -> controller [type: api, label: "Juju API (websocket)",
                        protocol: "websocket-rpc"]
  controller -> clouds [type: control, label: "provisions infrastructure"]
  controller -> charmhub [type: api, label: "fetches charms"]
  controller -> unit_agent [type: stream, label: "watcher (websocket)"]
  unit_agent -> charm [type: control, label: "exec dispatch"]
  charm -> unit_agent [type: ipc, label: "hook commands (unix socket)"]
  charm -> pebble [type: api, label: "Pebble API (HTTP)",
                   protocol: "http"]
  pebble -> workload [type: control, label: "manages services"]
}
```

Edge attributes:
- `type` -- semantic type from the built-in taxonomy or a custom declared type:
  `api`, `stream`, `event`, `data`, `control`, `ipc`, `pebble`
- `protocol` -- optional protocol detail (e.g. `websocket-rpc`, `http`,
  `unix-socket`); rendered as a secondary label or tooltip
- `label` -- primary display text
- `style` -- dashed, dotted, solid; defaults from type via style grammar
- `arrow` -- none, forward (default), back, both

Custom edge types are declared in the `style` block and map to a visual style.

Family convention (conceptual, one syntax -- see "Truth kinds and edge
families"): `data` edges are **associations** -- structural truths,
multiplicity-bearing, drawn in semantic direction, never a protocol.
The interaction types (`api`, `stream`, `event`, `control`, `ipc`) are
**interactions** -- behavioral truths, protocol-bearing, genuinely
directional, never multiplicity-bearing. Custom association types are
declared in the style block like any other type; family membership is
by convention, not grammar.

Routing strategy (ADR-003, implemented 0.26.0): routes are
obstacle-aware shortest paths over strips, found by search, not
derived from endpoint geometry. A* runs over a Hanan grid (endpoint and
obstacle rect coordinates, duplicates collapsed with a tolerance) with
8-neighbour moves; cost = length + a fixed turn penalty K (40 px, tuned
on the corpus through the audit's turns-per-edge report: 0.40 (juju3) /
0.99 (juju4) bends per edge — a path bends only to clear an obstacle).
The search chooses exit and entry faces: anchor candidates are the face
centres, grid-line crossings on the faces, and centre +/- 6 px offsets,
so pairs and meshes find distinct offsets emergently; field-qualified
endpoints stay pinned — author speech outranks heuristics. The
collision currency is the strip: path + stroke width + arrowhead caps +
the one-sided ADR-002 label extent, measured by the shared geometry
module (ggarch.geometry) that the router, solver, renderer and audit
all import. Obstacles: node rects inflated by the corridor (ancestor-
or-self of either endpoint exempt — containers their edges live in are
passable), and earlier edges' strips (clipped near shared endpoints);
endpoint-sharing groups route greedily after independent edges.
Annotation boxes and regions are meta elements — never obstacles,
never notched. No box explosion: the arrangement is fixed input; when
no collision-free path exists the router returns the cheapest-collision
path and reports it, and the audit prints every residual (edge,
obstacle, blocker) — audited, never hidden. Diagonals are preserved by
default (cost keeps them without special-casing); declared orthogonal
routing becomes a 4-neighbour search with the same strip currency.
Rounded joins ship as stroke-linejoin="round" (v1; fillets deferred).

Label placement: ADR-002, implemented 0.25.4 — labels ride the longest
  leg on an SVG textPath, above the line in the text's local frame,
  one textPath per wrapped line stacked outward, mirrored on
  right-to-left legs (never upside-down), no background mask, the
  stroke never split. Every label anchors at the midpoint of its own
  leg: pairs route at distinct offsets (ADR-003), so the 1/3-2/3
  anchor workaround for coincident strokes is deleted.

Border notches are ports (ADR-003 decision 11): a container border is
notched only where exactly one endpoint of the edge is inside that
subtree — the notch reads as a port. Edges passing over a container
leave the border solid (their crossing is a routing defect the router
eliminates); internal edges do not notch their own container;
annotation boxes never notch. State-view transitions are routed strips
like any edge, and their labels ride the path — one label mechanism
across all three view kinds; the opaque background masks are gone.

Geometry audit (0.25.2, both twins measured): the defect classes are
SYSTEMIC, not auto-layout-specific. Audit of every diagram view's
solved+routed geometry (segment-vs-rect interior crossing test,
diagonal classification, replicated renderer gap/offset test):
juju4 (no positions) 31 crossing-edges / 26 diagonals / 11 offset
labels; juju3 (authored) 15 / 15 / 9. Authored positions halve the
defect rates by hand-compensating for the same root causes:

1. The router is obstacle-blind: every route is derived from the two
   endpoint rects alone. Straight lines cross intermediate nodes (fan
   edges cross stacked column-mates; mesh arrows traverse the target
   container's siblings) and L-route legs plow through unrelated nodes
   (the controller worker tree's leader-lease edge crosses api_server
   and http_server in its own column). Container exit paths even cross
   the endpoint's own container-mates.
2. Horizontal-dominant edges render face-centre to face-centre -- flat
   only when the centres coincide, otherwise diagonal. The mid-y
   flattening that field-qualified edges already get (router route())
   is not applied to plain edges; the synthesized floor declares no
   cross-column alignment, so centre offsets are the norm.
3. Label-space reservation is decoupled from the rendered geometry.
   The reservation axis is inferred from declared constraint kinds;
   undeclared pairs (stamped subtree internals) get a both-directions
   horizontal fallback at soft priority that cancels out on vertical
   stacks -- "runs"/"supervises" stay at 20px in BOTH twins. The
   reserved quantity is axis-aligned between effective endpoints; the
   renderer needs it along the actual segment (divided by the segment's
   horizontal component), with wrapping at segment width. And the
   reservation leaves zero slack: an edge reserved exactly 142px needs
   142px, so sub-pixel solver wiggle flips its label mode.
4. The synthesized floor is 1-D: columns with all-pairs left-of between
   neighbours and vertical stacks within columns -- no row structure
   across columns, no corridor budget for labels or spanning edges, no
   container-internal axis awareness (the HA containers lay children
   side-by-side while the containers themselves are in a row, forcing
   every mesh arrow through its target's agent sibling).
   **Step 1 verdict (0.25.3, label contract):** root cause 3 is FIXED.
   Measured post-change (same audit): offset labels juju4 11 -> 0,
   juju3 9 -> 0; every labelled edge in all five model files renders
   in gap mode. Crossings unchanged (31/15 — router work, step 3);
   diagonals effectively unchanged (27/15 — alignment and router
   work, steps 2-3). 36 of 43 views changed geometry, all by
   reservation-driven expansion; views without shortfalls were
   byte-identical.

   **0.25.4 verdict (ADR-002):** the gap/offset defect class is
   DISSOLVED — there is no label mode left to flip (one placement
   mechanism; the audit's offset-label metric is retired with it).
   Wall-crossings 0/0: the strike-avoidance contract reserves them.
   Pre-router baseline for ADR-003: juju3 15 crossing-edges / 11
   diagonals / 30 rotated labels / 3 node-strikes / 6 label-clashes;
   juju4 35 / 22 / 22 / 4 / 10.

   **0.26.0 verdict (ADR-003):** the obstacle-blind router is retired.
   Measured: juju3 0 crossing-edges / 6 diagonals / 31 rotated labels /
   1 node-strike / 2 label-clashes / turns-per-edge 0.40; juju4 2
   crossing-edges (both audited residuals of the tight-corridor
   "Integrate" mesh — the edge-aware floor, step 4, owns that
   capacity) / 9 diagonals / 18 rotated / 3 strikes / 1 clash /
   turns 0.99. Crossings 15/35 -> 0/2; label clashes 6/10 -> 2/1;
   node strikes 3/4 -> 1/3. New audit metrics: strip crossings
   (8/16, mostly chain/fan wedges just beyond the shared-endpoint hug
   allowance), router-reported residuals (2/14) and turns per edge.
   Known issue, recorded: juju3 rotated 31 vs the 30 baseline — the
   +2 rotated labels are the direct price of zero crossings (the
   u_app3 "watches" detour over the app columns) and emergent pair
   offsets (object_store's offset entry onto lease_manager); one
   rotated label was recovered elsewhere (endpoint_rec "belongs to").
   The staged auto-flip decision (rotated as its metric) and the
   edge-aware floor own the follow-up.

---

## Layer 4: behaviours (in the model)

Declares named interaction sequences between model entities. Behaviours are
first-class model declarations -- not view-level constructs. Every participant
in a behaviour must be a node declared in `nodes`. Every interaction must
traverse an edge declared in `edges`. Violations are parse errors.

```
behaviours {
  behaviour "hook execution" {
    unit_agent -> charm: call "exec dispatch"
    loop "during hook" {
      charm -> unit_agent: call "hook command (unix socket)"
      unit_agent -> controller: call "serve via API"
      controller -> unit_agent: return
      unit_agent -> charm: return
    }
    alt "exit 0" {
      charm -> unit_agent: return "success"
      unit_agent -> controller: call "flush writes"
    } else "failure" {
      charm -> unit_agent: return "failure"
      unit_agent -> controller: call "discard writes"
      unit_agent -> controller: call "set unit error"
    }
  }

  behaviour "bootstrap k8s" {
    client -> k8s: call "authenticate"
    k8s -> client: return "OK"
    client -> k8s: call "create namespace, deploy controller pod"
    k8s -> client: return "pod scheduled"
    config_seed -> config_seed: self "run once" [lifecycle: init]
    charm_init -> charm_init: self "run once" [lifecycle: init]
    jujud -> jujud: self "start API server"
    jujud -> controller_db: call "initialise database"
    jujud -> client: return "API ready"
  }

  behaviour "unit deploy" {
    client -> controller: call "deploy application"
    controller -> controller_db: call "write goal state"
    controller -> clouds: call "provision machine/pod"
    controller -> charmhub: call "fetch charm"
    controller -> unit_agent: async "watcher fires"
    unit_agent -> charm: call "install hook"
    charm -> workload: call "install workload"
    charm -> unit_agent: return "success"
    unit_agent -> controller: call "flush writes"
  }
}
```

Behaviour step types:
- `call` -- synchronous invocation; renders as solid arrow
- `return` -- response to a prior call; renders as dashed return arrow
- `async` -- fire-and-forget notification; renders as open arrowhead
- `self` -- self-call (a node acting on itself); renders as loop arrow
- `loop "label" { ... }` -- repeated sequence
- `alt "condition" { ... } else "condition" { ... }` -- conditional branches
- `par { ... }` -- parallel steps

Because behaviours are in the model, they are:
- **Consistent** -- renaming `unit_agent` renames it in every behaviour
- **Validatable** -- a step referencing a node not in `nodes` is a parse error
- **Queryable** -- "which nodes participate in bootstrap?" answerable from JSON
- **Projectable** -- a `sequence` view selects a behaviour and renders it with
  no re-declaration


## Layer 5: annotations (in views)

Overlaid on top of the solved layout. Annotations do not affect node positions
or edge routing.

```
annotations {
  box [nodes: client controller,
       label: "intent & persistence",
       style: dashed, color: "#666"]

  callout [anchor: clouds, position: above,
           text: "cloud knowledge lives here"]

  separator [between: controller app1,
             label: "execution boundary",
             style: dashed]
}
```

Annotation types:
- `box` -- rectangle enclosing a set of nodes, with optional label
- `callout` -- text label anchored to a node or region
- `separator` -- a line between two groups of nodes
- `badge` -- a small label on a node (e.g. "(init)" on Pebble)

Annotations are a separate layer, so multiple annotation sets can be defined
and applied selectively to the same base layout.

---

## Layer 6: style (in the model)

Declares the visual grammar. Node types map to style rules. Defined once,
applied everywhere. Ships with a built-in `juju` preset.

```
style {
  extends: juju   // built-in preset; override below

  person {
    shape: person
    fill: none
    stroke: none
  }

  juju-software {
    fill: "#E95420"
    font-color: white
    stroke: "#C74210"
  }

  charm {
    fill: white
    stroke: "#E95420"
    font-color: black
  }

  workload {
    fill: "#4A90D9"
    font-color: white
    stroke: "#2C6FAC"
  }

  external {
    fill: "#F5F5F5"
    stroke: "#AAA"
    font-color: "#444"
  }

  # Edge type rules use the `edge` keyword -- the name is otherwise
  # ambiguous with a node type of the same name.
  edge cloud-call {
    stroke: "#8E44AD"
    stroke-width: 2
  }


  @dark {
    external {
      fill: "#2A2A2A"
      stroke: "#666"
      font-color: "#CCC"
    }
    # Dark overrides for edge types use the same form.
    edge cloud-call {
      stroke: "#BB8FCE"
    }
  }
}
```

---

## Output

Two SVGs per diagram: light and dark.

SVG structure:
- Each node: `<g>` containing `<rect>` (or `<path>` for person/cylinder) and
  `<text>`.
- Containers: `<g>` wrapping children with a background rect.
- Edges: `<path>` elements.
- Annotations: `<g>` group drawn last, `pointer-events: none`.
- Colours via CSS custom properties for optional single-SVG light/dark
  switching.

JSON output (for agents and tooling):
- Parsed diagram as a structured JSON document.
- Includes solved node coordinates, edge endpoint anchors, and annotation
  bounds.
- Emitted alongside SVG when `--json` flag is passed to the CLI.

---

## Sphinx extension

```markdown
    ```{ggarch}
    :alt: User declares intent to Client. Client calls Juju API on Controller.
          Controller provisions infrastructure from Clouds and fetches charms
          from Charmhub. Controller drives Application units via websocket.
    diagram "..." {
      ...
    }
    ```
```

The extension:
1. Parses the ggarch source at build time.
2. Solves constraints (kiwisolver).
3. Routes edges.
4. Renders two SVGs (light + dark).
5. Emits light/dark image pair with lightbox anchors, following the same
   pattern as `sphinxcontrib_d2.py`.
6. In markdown/llms output: emits the ggarch source verbatim as a fenced
   `ggarch` code block so agents see the full diagram structure, preceded by
   an HTML comment containing the alt text.

---

## Implementation plan

Phases 1–6 are complete. Phase 7 is blocked. Phases 8–11 are planned,
derived from the feature parity analysis in ADR-001.

### Phase 1 -- parser + data model ✓
Parse the model/view syntax into a Python data structure. Validate: node ids
unique, edge endpoints exist, behaviour participants exist in nodes, behaviour
steps traverse declared edges, view `select` targets exist in model.
Library: `lark` (MIT).

### Phase 2 -- constraint solver ✓
Translate position constraints into kiwisolver expressions. Solve to produce
(x, y, width, height) for every node in a view. Handle containment (parent
bounds contain all children). Library: `kiwisolver` (BSD).

### Phase 3 -- straight-line edge routing ✓
Compute start/end anchor points on node boundaries. Route straight lines and
⌐-shaped elbows. Straight-horizontal snap threshold (10px) absorbs minor
solver artefacts from nested containers.

### Phase 4 -- SVG renderer ✓
Render nodes (lifecycle/cardinality visual cues), edges (type styling,
arrowheads, labels), annotations (box, callout, separator, badge) to SVG
using `drawsvg` (MIT). Light and dark variants. Shapes: rectangle, person
(stick figure), cylinder (database), container (with header strip).

### Phase 5 -- sequence view renderer ✓
Render `sequence` views as sequence diagrams with lifelines sourced from the
model. Steps: `call`, `return`, `async`, `self`, `loop`, `alt`/`else`.
`par` is parsed but not yet rendered (see phase 8).

### Phase 6 -- Sphinx extension ✓
`sphinxcontrib_ggarch.py`: `{ggarch}` directive with `:view:`, `:sequence:`,
`:file:`, `:alt:` options. Light/dark SVG pair. Expand button with fullscreen
modal (inline SVG icons, `type=button`, no lightbox dependency). Markdown
visitor emits source verbatim. File mtime in cache hash.

### Phase 7 -- orthogonal routing (blocked)
Plug in adaptagrams libavoid when a production-ready Python binding exists.
No maintained binding currently available. Straight-line routing remains the
default; revisit when one appears.

### Phase 8 -- sequence completeness
Complete the `par` block renderer in `sequence_renderer.py`. Add activation
bars (shaded rect on the lifeline during call/return pairs). Add `opt` block
(optional sequence, single branch alt). These are rendering additions only —
the grammar and model already support `par`.

### Phase 9 -- node fields and structured rendering
*(Derived from ADR-001 Gap 1: node structure)*

Grammar change: add `fields { }` block inside a node declaration, with
per-field `id`, `label`, `type`, and optional key markers (`pk`, `fk`, `uk`,
`null`). Edge endpoint syntax: `node.field_id` for field-qualified anchors.
Validator: field ids are unique within a node; field-qualified edge endpoints
reference declared fields.

Rendering: nodes with fields and `type: record` render as tables (header row
+ field rows). Nodes with fields and `type: class` render as UML compartment
boxes (name compartment + fields compartment + methods compartment). The
router anchors field-qualified edges at the field row's right/left face
rather than the node centroid. Crow's-foot arrowhead styles (zero-or-one,
one, zero-or-more, one-or-more) added to the style layer as edge arrow types.

### Phase 10 -- metadata and legend
*(Derived from ADR-001 Gap 3: structured metadata)*

Grammar change: `properties { key: "value" ... }` block on any node, edge,
or behaviour step. `url: "https://..."` attribute on nodes and edges.

Rendering: `url` wraps the SVG element in `<a href="...">`. Properties are
emitted in the JSON export only (not rendered visually). New annotation type:
`legend` -- renders the node types and edge types from the style block as a
visual key in the diagram. No new model data; legend is a projection of the
existing style layer.

### Phase 11 -- state view renderer
*(Derived from ADR-001 Gap 2: richer behaviour steps)*

Grammar change: additive step attributes -- `guard: "[condition]"` and
`on: "event"` on any behaviour step. Existing sequence rendering ignores
unknown attributes (backward compatible).

New view type: `state "Name" from "Model" { select { behaviour: "..." } }`.
Renderer: each unique node that appears as `self` step source or as
source/target of a directed step becomes a state node. Directed steps become
transition edges labelled `on / [guard] / label`. `self` steps with `on`/
`guard` are entry/exit/internal actions on the state. `alt` blocks become
choice pseudostates. `loop` blocks become loop regions. `par` blocks become
concurrent regions (horizontal separator).

### Phase 12 -- deployment environments
*(Derived from ADR-001 Gap 4: deployment environments as model data)*

Grammar change: `environment "name" { present: id id ... abstracts { id:
concrete_id ... } }` block in the model. Extends `abstracts:` from a
node-level attribute to a model-level grouping.

Validator: a view selecting `environment: "name"` resolves all abstract ids
in the view's node list and behaviour participants to their environment-
specific concrete ids. Existing node-level `abstracts:` remains valid as a
shorthand for the common case of a single concrete realisation.

---

## Dependencies

| Dependency   | License | Purpose           |
|--------------|---------|-------------------|
| `lark`       | MIT     | Grammar / parser  |
| `kiwisolver` | BSD     | Constraint solver |
| `drawsvg`    | MIT     | SVG generation    |
| `sphinx`     | BSD     | Extension host    |

No copyleft. No binary builds. No npm. No network at build time.
Phases 8–12 add no new dependencies.

---

## Open questions

1. **Shorthand syntax.** The model/view structure is verbose for simple
   one-off diagrams. Consider a `diagram` block without an explicit `model`
   that inlines all five layers, for cases where multi-view reuse is not
   needed. Deferred; the `:file:` option covers the common case.

2. **Constraint relaxation policy.** Conflicts are errors. This is the right
   choice -- silent relaxation is how ELK and dagre caused problems in
   practice. Closed: error is the policy.

3. **Cardinality rendering.** Badge (current) vs stacked boxes (UML instance
   notation). Badge implemented and working. Stacked boxes deferred until a
   use case requires it.

4. **Edge type taxonomy.** The built-in types (`api`, `stream`, `event`,
   `data`, `control`, `ipc`) cover the Juju case well. Custom types via the
   style block cover everything else. Closed: the built-in set is the right
   size; extend via style, not built-ins.

5. **Style presets.** `juju` ships built-in. Third-party presets via Python
   packages (`ggarch-style-juju`) are a future distribution concern. Deferred.

6. **`abstracts:` rendering.** Currently affects validation only. Phase 12
   implements the rendering side: view selection substitutes the concrete node
   when an abstract id is selected. Tracked in phase 12.

7. **View keyword unification.** The current grammar uses separate top-level
   keywords -- `diagram`, `sequence`, `state` -- for different rendering modes.
   This encodes the renderer in the keyword rather than deriving it from the
   select content, which is the wrong level of abstraction. All views are
   projections of the same model; they should share one keyword. The rendering
   mode is fully determined by what the `select` block contains: `behaviour:`
   implies sequence rendering; `nodes:`/`positions:` implies topology rendering;
   `state:` implies state machine rendering. The target grammar is a single
   `view` keyword throughout. The Sphinx directive already implements this at
   the surface level (`:view:` resolves either type by name); the grammar,
   parser, model dataclasses, and CLI need to follow.
   **TODO:** Migrate `diagram`/`sequence`/`state` to `view` in the grammar and
   parser. Keep `diagram`/`sequence` as deprecated aliases during a transition
   window; remove them in the next MINOR version bump.

8. **Contextual edge descriptions -- the label multiplicity problem.**
   The current grammar has two places where edges are described:

   - `edges {}` in the model assigns one canonical label per edge
     (e.g. `unit_agent -> charm [type: control, label: "runs"]`).
   - `behaviours {}` step labels shadow that canonical label in the context
     of a specific interaction
     (e.g. `unit_agent -> charm: call "exec dispatch"`).

   The shadowing is informal -- the grammar has no concept of what is
   happening. This creates a real design tension: both descriptions are
   correct. "runs" is the right description at the topology level; "exec
   dispatch" is the right description in the context of the hook execution
   sequence. Neither is more true than the other. Labels are not intrinsic
   properties of edges; they are properties of (edge, context) pairs.

   This is the same principle as `abstracts:` -- same structural entity,
   different description at a different level of abstraction -- but applied
   to edge descriptions rather than node identity. ggarch's placement of
   behaviours inside the model is a meaningful conceptual improvement over
   Structurizr's dynamic views (which were declared at the view level,
   breaking rename propagation and declare-once). But it does not yet fully
   resolve the label multiplicity: step labels in behaviours are implicitly
   contextual refinements of edge labels, but the grammar provides no formal
   account of that relationship.

   The correct resolution would make the (edge, context) pairing explicit.
   Candidate approaches:

   - **Contextual labels on edges.** Allow multiple named label slots per
     edge: `unit_agent -> charm [type: control, label: "runs",
     label.dispatch: "exec dispatch"]`. A behaviour or view selects which
     slot to use. Explicit, but verbose.
   - **Behaviours as formal context declarations.** A behaviour formally
     declares that it provides contextual descriptions for a subset of edges.
     Step labels are then recognised as contextual overrides, not shadow
     values. The validator could check that step labels only appear on edges
     that are declared in `edges {}`.
   - **Accept the current implicit shadowing**, document it as intentional,
     and trust that the behaviour name provides sufficient context. This is
     the current state.

   **TODO:** Decide whether the implicit shadowing should be formalised or
   left as a deliberate convention. Collect evidence from real diagram
   authoring (does the ambiguity cause errors or confusion in practice?)
   before committing to a grammar change.

9. **Where the view declaration lives -- .ggarch vs .md.** The current
   split: the whole view (select, positions, annotations) is declared in
   the .ggarch file; the caption, legend toggle, alt text, and slide
   captions are options on the `{ggarch}` directive in the .md. But the
   view layer is *deliberately presentational* -- `select` is an editorial
   choice about what to show, made in service of a specific passage of
   prose. Two arguments pull in opposite directions:

   - **Keep select in .ggarch:** selecting is easier when you can look at
     what you are selecting -- the view is chosen against the model it
     selects from, and the .ggarch file keeps that context. Rename
     propagation and the validator also operate on the view where it lives
     today.
   - **Move the view to .md:** the view's presentational nature would be
     explicit in its location. The caption is as much a property of the
     diagram as the select is; the diagram must fit the surrounding text,
     so the document context participates in the view definition either
     way. An inline view block in the .md (see open question 1, inline
     syntax) would make the view a property of the document that borrows
     entities from the model, rather than a property of the model file.

   Either way, authoring always involves considering both the document and
   the model; the question is which artefact the view belongs to, and
   therefore where the reader -- and an agent -- looks for editorial
   intent. Currently open; the `:file:` + `:view:` indirection covers the
   common case.

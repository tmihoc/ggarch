# ggarch -- Specification

A Grammar of Architecture Diagrams.

A text-based, constraint-layout diagram tool for architecture documentation,
inspired by the Grammar of Graphics (Wilkinson 2005) and its R implementation
ggplot2. Like ggplot2, ggarch separates a diagram into independent, composable
layers that are declared separately and rendered in a defined order.

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

The current state of ggarch: it has reached full expressive parity with the
best existing docs-as-code tools, and exceeds them on several dimensions
(Cassowary constraint layout, first-class lifecycle and cardinality, typed
edges, single-model multi-view consistency, deployment environment resolution,
state machine views). The next design challenge is **expressive power for
distributed systems specifically** -- identifying the diagram patterns that
genuinely communicate system architecture to readers who need to understand a
complex, distributed, event-driven system, and ensuring those patterns are
first-class ggarch citizens.

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
both ends of the spectrum, and the middle, equally first-class -- not
penalise the inline path, and not obscure the model path.

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
  or a new built-in. ✓ Supported; custom types exist. TODO: verify the legend
  renders custom types correctly so the reader can distinguish them.

- **Sub-node labels / record-style nodes in topology.** The controller's
  "relation data bag" for app A and app B are conceptually inside the
  controller node, not separate nodes. Expressing "data lives here, not there"
  requires either record-style nodes (PK/FK table rows) or a way to annotate
  a sub-region of a node. ✓ Record nodes exist; TODO: verify they compose
  cleanly with the topology renderer and that edges can target individual
  fields in a topology (not just an ER diagram).

- **Lifecycle on workers.** The compute provisioner runs as a persistent worker;
  hook execution is ephemeral (runs once per hook invocation, then exits).
  These are first-class lifecycle values (`persistent`, `ephemeral`). ✓
  Supported. TODO: confirm the visual distinction (solid vs dotted border) is
  legible at typical diagram sizes.

- **State machine transitions with guards and triggers.** The uniter's
  operation executor has precise states (preparing → executing → committing)
  with labeled transitions (guard: "exit 0", trigger: "hook fails"). ✓ State
  view exists with `guard:` and `on:` attributes. TODO: assess whether the
  current state view layout (single-row) handles the uniter state machine
  (6–8 states) without becoming unreadable. Multi-row or hierarchical layout
  may be needed.

- **Async vs sync edges in sequence diagrams.** Watcher notifications are
  async fire-and-forget; API calls are sync request/response. ggarch sequence
  has `call` (sync) and `async` step kinds. ✓ Supported. TODO: verify the
  visual distinction is clear when both appear on the same lifeline.

- **In-process vs cross-process calls.** The unit agent runs inside the machine
  agent (nested engine); hook tools connect to an in-process Unix socket server.
  These are architecturally important distinctions. ggarch has `ipc` edge type
  for local IPC and `control` for process lifecycle. TODO: assess whether
  "nested process" containment (unit agent inside machine agent process) is
  expressible without either creating a false node boundary or losing the
  in-process nature.

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

Current state: node `type` is already a free string with preset fallback; edge
types support `CUSTOM` with a style block. The mechanism is right; the API is
implicit.

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
Nothing is decorated for its own sake; every visual element is semantically
load-bearing.

**Current state:** colour already encodes ownership/provenance cleanly (Juju
orange, workload blue, external gray, charm white+orange border). Shape encodes
categorical entity type with a small honest vocabulary: rect (process/software),
cylinder (storage), person (actor). All shapes fill their bounding box to the
same margin so the constraint solver's geometry is honest for every type.

**Decisions made:**

- Workload nodes use `external` styling (gray), not a distinct blue. Blue added
  no semantic information orthogonal to what colour was already encoding and
  created visual noise.
- Person nodes are a rounded rect with a small head+shoulders badge in the
  top-right corner. The badge is the type indicator; the label is centred
  inside the box. Same bounding-box convention as every other shape.
- The shape vocabulary is intentionally small: rect, cylinder, person. C4-style
  shape proliferation (person, software system, container, component, database,
  queue...) is avoided because C4's hierarchy encodes abstraction level via
  shape, which ggarch handles better through multi-view + `abstracts:`.

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
conflates compute boundary with software container. A future `compute` type
would separate them. The complete list of recurring infrastructure components
worth standardising is an open design question.

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

**TODO: `records:` relationship.** Introduce a `records:` attribute on nodes,
symmetric with `abstracts:` but on the persistence axis rather than the
abstraction axis. Example: `unit_agent [records: "unit_rec"]` declares that the
`unit_agent` node's runtime state is persisted as the `unit_rec` data model
node. This relationship would:
- Be declared in the model, not in views.
- Allow topology views to optionally surface data-model links as annotations
  or cross-references ("show me the persistence face of everything in this view").
- Allow data-model views to optionally show which runtime entities write to each
  record.
- Be validated: a `records:` target must be a declared `record`-type node.

**TODO: model-scoped node annotations.** In Juju, every deployed entity belongs
to a model (namespace in the controller database). A topology diagram spanning
multiple models currently has no way to indicate model membership. A
`model: "controller"` or `model: "prod-k8s"` attribute on a node, rendered as
a subtle label or boundary annotation, would let operators connect what they
see in a diagram to what they see in `juju status` and `juju models`.

**TODO: investigate.** Whether `records:` and `abstracts:` are instances of a
more general **relationship axis** concept -- where a node can declare its
relationship to other nodes along named axes (abstraction, persistence,
model-membership, lifecycle-phase) -- rather than accumulating ad hoc
attributes. This may be the right generalisation but needs more evidence from
real diagram authoring before committing to a grammar change.

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

---

## Comparison

The table below scores eight capabilities against the tools most commonly used
for architecture documentation. Each capability is defined under the score.

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

Routing strategy: straight lines by default. Orthogonal routing as an opt-in
per diagram or per edge, pending a production-ready Python binding for
adaptagrams libavoid.

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

  @dark {
    external {
      fill: "#2A2A2A"
      stroke: "#666"
      font-color: "#CCC"
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

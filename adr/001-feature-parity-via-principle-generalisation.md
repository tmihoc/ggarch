# ADR-001: Feature parity via principle generalisation

**Date:** 2026-09-01  
**Status:** Accepted  

## Context

A survey of twelve competing docs-as-code diagram tools — Mermaid, D2,
Graphviz, PlantUML, Structurizr, Ilograph, Pikchr, Nomnoml, C4-PlantUML,
DBML, blockdiag/packetdiag, and Kroki — identified roughly twenty expressive
capabilities that ggarch does not currently support. The raw list included:
ER/entity-relationship diagrams with crow's-foot cardinality and PK/FK
markers; class compartments with field/method structure; SQL table shapes with
per-row port anchoring; state machines with guarded transitions and composite
states; Gantt charts with task dependencies and date axes; git branch topology;
mindmaps and WBS; packet/bit-field wire formats; mathematical notation
(AsciiMath/LaTeX); arbitrary key-value metadata and URL hyperlinks on model
entities; deployment environment modelling; interactive walkthroughs and
progressive disclosure; programmatic/scripted model generation; and legend
auto-generation from tags.

The question was not "which of these do we add" but "what *design principle
generalisation* makes a given capability fall out naturally, rather than being
bolted on as a special case?"

## Decision

Four capabilities are added via principle generalisations. The rest are
explicitly out of scope.

**In scope (principle generalisations):**

1. **Node structure** — the principle "nodes have a label and type" is
   generalised to "nodes may declare named fields". A field is a first-class
   model entity with its own id, label, type, and optional attributes. ER
   tables, class compartments, SQL schemas, and per-field port anchoring all
   fall out of this one extension. Node type determines the rendering mode:
   `record` → table rows; `class` → UML compartments. Edge endpoints may be
   field-qualified (`node.field_id`) to anchor at a specific field.

2. **Richer behaviour steps** — the principle "a behaviour is a sequence of
   steps rendered as a sequence diagram" is generalised to "a behaviour is an
   interaction graph; a view chooses the rendering". A `state` view renders
   the same behaviour as a state transition diagram. Guards (`guard: "[cond]"`)
   and triggers (`on: "event"`) are additive step attributes; they do not
   break existing sequence rendering.

3. **Structured metadata on model entities** — the principle "the model is
   complete and queryable" already implies that any system fact belongs in the
   model. Extending it: any model entity (node, edge, step) may carry a
   `properties` map (arbitrary key-value) and a `url`. A `legend` annotation
   type that renders the style block as a visual key falls out of the existing
   style + annotations layers.

4. **Deployment environments as model data** — already specced (`select {
   environment: <id> }`), not yet implemented. The `abstracts:` relationship
   is generalised from a node attribute to a model-level `environment` block
   that declares which nodes are present per environment and which abstract
   ids they realise. A view selecting `environment: kubernetes` automatically
   resolves abstract ids to their Kubernetes-specific concrete nodes.

**Out of scope:**

- **Gantt / timeline / scheduling** — requires a date/arithmetic DSL and a
  chart layout engine. A separate tool family; out of scope.
- **Git graphs** — domain-specific to version control, not architecture.
- **Mindmaps / WBS / kanban / BPMN** — project management or process
  modelling. Out of scope.
- **Mathematical / EBNF / regex notation** — requires a separate renderer
  (LaTeX/AsciiMath). Violates the no-binary-dependencies principle.
- **Packet / bit-field wire formats** — byte-level layout; a separate domain.
- **Interactive walkthroughs / progressive disclosure** — incompatible with
  static SVG output. A future concern for an interactive renderer, not the
  current Sphinx extension.
- **Programmatic model generation** (`!script`, `!plugin`, computed nodes
  from code) — violates the no-code-execution security principle.

## Reasoning

**Why principle generalisation rather than ad hoc addition?**

An ad hoc addition is a feature that requires its own grammar construct, its
own renderer, and its own validation rules with no connection to existing
concepts. It adds surface area to the language without making the language
more expressive per concept. The result over time is a tool like PlantUML:
~20 diagram types that do not compose, each with its own syntax, each siloed
from the others.

A principle generalisation is a feature that falls out of making an existing
rule more general. It adds one concept that unlocks many capabilities. Node
fields are not "an ER feature" — they are a natural extension of the node
vocabulary that also covers class diagrams, SQL tables, and port anchoring.
The language becomes more expressive per concept added.

**Why not ER cardinality notation specifically (crow's-foot, min/max)?**

Cardinality on an edge between two record-type nodes (`one-to-many`, `zero-or-
one`) is a property of the *edge* in the model, not of the rendering. The
existing `label` attribute on edges already carries this information as free
text. The principle generalisation (node fields + field-qualified endpoints)
is the structural foundation; cardinality notation is a style concern that
maps to existing edge attributes once the structural foundation is in place.
Crow's-foot arrowhead styles are added to the style layer, not a new grammar
concept.

**Why not interactive walkthroughs?**

Ilograph's walkthrough slides are compelling, but they require a JavaScript
runtime and DOM interaction. The Sphinx extension's output is static SVG. The
design principle "offline first, no runtime infrastructure" rules it out for
the current output target. If ggarch ever has an interactive renderer
(separate from the Sphinx extension), walkthrough support is a natural
addition at that point — the model structure already supports it.

**Why not programmatic generation?**

Structurizr's `!script`/`!plugin`/`!components` features are powerful for
large codebases where the model can be derived from source code. They violate
ggarch's "no code execution" security principle: the diagram source is a pure
data declaration, never executable. A separate tool that reads code and emits
a `.ggarch` model file is the right answer — it keeps the diagram source
auditable and the renderer safe.

## Consequences

**Easier:**
- ER diagrams, class diagrams, and SQL table diagrams are expressible within
  the existing model-and-views framework without a new diagram type.
- State machine diagrams reuse existing behaviour declarations — no new model
  concepts for authors who already use behaviours.
- Model entities can carry structured metadata queryable from JSON export,
  enabling richer agent tooling.
- Deployment environments become first-class, enabling the same model to
  project different deployment topologies without duplication.

**Harder:**
- Node field rendering adds a new rendering mode to the SVG renderer.
- Field-qualified edge endpoints require changes to the grammar, validator,
  router, and renderer.
- The `state` view type requires a new renderer (state diagram layout is
  different from sequence diagram layout).
- Environment block resolution requires changes to the validator and the
  view projection logic.

**Explicitly ruled out:**
- Gantt, git graph, mindmap, kanban, BPMN, mathematical notation, packet/bit
  fields, interactive walkthroughs, programmatic generation are not part of
  ggarch's scope and will not be added.

**Definition of done for feature parity:**
Once phases 8–12 of the implementation plan are complete, ggarch has full
expressive parity with existing docs-as-code tools for distributed systems
architecture documentation. Anything a practitioner would reasonably put in an
architecture document — topology, sequence, ER schema, class hierarchy, state
machine, deployment environment view — is expressible in ggarch with stronger
layout guarantees and model consistency than any current alternative. The
out-of-scope items above are the deliberate boundary; they will not be revisited
unless the scope statement in the SPEC changes first.

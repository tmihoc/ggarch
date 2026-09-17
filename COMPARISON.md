# ggarch vs other diagram tools

ggarch is a diagrams-as-code tool. The comparison that matters is against other
diagrams-as-code tools. Freehand tools are a different trade-off: they can look
exactly as you want and draw anything, but they are manual by design — no text
source, no diffs, no rename propagation, no AI assistance. If your use case is
a one-off whiteboard sketch or a polished marketing diagram that will never
need updating, a freehand tool is the right answer and ggarch competes for the other
case. If your use case is architecture documentation that lives in a
repository and must stay current as the system evolves, you need DaC, and the
comparison below is the one that matters.

---

## Summary

Three properties determine whether a DaC tool is adequate for serious
architecture documentation:

- **Branding** -- does the output look intentional? Can you match your
  project's identity -- colour palette, font, light/dark theme -- without
  fighting the tool?

- **Expressive power** -- can the tool communicate what actually needs
  communicating? This is broader than "which node types are supported." It
  includes a coherent visual grammar where colour, shape, and line style
  encode meaning; layout (where you place things says something -- putting
  Charmhub below the controller and apps to the right is an argument about
  architectural role, not an aesthetic choice); semantic edge types (a
  dashed arrow that means "watch" communicates differently from a solid
  arrow that means "call"); conceptual vocabulary (lifecycle, cardinality,
  abstraction relationships, intent vs execution, runtime vs persistence);
  and presentation (slideshows, pacing, what you show when). How you embed
  meaning matters as much as what you declare.

- **Maintainability** -- all DaC tools are text-based; that is the baseline
  and is assumed. The meaningful bar is higher: does a rename propagate to
  every diagram automatically? Is there a single source of truth that the
  validator enforces? Can diagrams stay in sync with each other and with the
  system they describe?

| Tool | Branding | Expressive power | Maintainability |
|---|:---:|:---:|:---:|
| Mermaid | ✗ | ✗ | ~ |
| D2 | ~ | ~ | ~ |
| Graphviz | ✗ | ~ | ~ |
| PlantUML | ~ | ~ | ~ |
| Structurizr | ~ | ~ | ✓ |
| Ilograph | ✗ | ~ | ~ |
| **ggarch** | **✓** | **✓** | **✓** |

✓ fully addressed · ~ partial or limited · ✗ not addressed

The pattern: every tool here is text-based (that much is free), but
re-declaration tools -- where every diagram is its own world -- are only
superficially maintainable. The meaningful maintainability bar, a shared
model with propagation, is met only by Structurizr and ggarch. On branding
and expressive power, no existing tool comes close to combining both.

---

## Mermaid

**One-line summary:** The easiest on-ramp, the lowest ceiling.

Mermaid is GitHub-native and AI-fluent. It is the right default for simple
diagrams that don't need to grow. The problems appear when you push it:

**Branding:** Mermaid has light and dark themes and nothing else; every edge
is a line, and colour and dash are decorative. A reader
looking at the diagram sees arrows and boxes -- the semantic distinction
between a synchronous API call, an async notification, and a process
lifecycle event falls to the labels. Labels carry all the weight, and labels
clutter small diagrams.

**Expressive power:** Layout is graph-based; Mermaid decides where nodes go,
and declaration order is a hint at best. Every diagram is a self-contained
document: the "Controller" box in a topology and the "Controller" lifeline
in a sequence are two separate declarations that silently diverge the moment
one is edited. No typed edges, no lifecycle, no shared model, no abstraction
relationships, no cross-cutting annotations.

**Maintainability:** Text-based, plain syntax, widely supported in editors
and CI pipelines, and the diagram language AI assistants know best. But
every diagram is a self-contained document: rename "Controller" in the
topology and the "Controller" lifeline in the sequence is untouched. No
shared model, no validator, no propagation. Maintainable in the trivial
sense; the meaningful bar is higher.

**The gap:** Mermaid works well for simple directed graphs. Push it toward
nested deployment topology, init vs persistent vs ephemeral processes, or
two diagrams that need to show the same system from different angles, and
it runs out of vocabulary.

---

## D2

**One-line summary:** Better layout control than Mermaid, same re-declaration ceiling.

D2 is more recent and deliberately addresses some of Mermaid's limits.
Layout is more controllable (`near`, ELK backend, custom directions), style
is more expressive, and the syntax is cleaner. It is a meaningful step up.

**Branding:** D2 has themes and per-element style control. Style is applied
manually per element or per class rather than derived from a type system --
the look is yours to choose, derived from taste rather than meaning.

**Expressive power:** Layout is better than Mermaid but `near` is a hint,
not a guarantee; the engine can still override spatial intent. Every diagram
is a self-contained document. No shared model, no typed edges, no lifecycle,
no abstraction relationships. D2 supports SQL table nodes and UML-like class
diagrams as separate syntactic modes, each its own world rather than views
of a shared model.

**Maintainability:** Plain text, clean diff, good editor support. Same
re-declaration problem as Mermaid: every diagram is its own world, diagrams
drift silently, rename propagation is absent.

**The gap:** D2 gets you further than Mermaid on layout and style but hits
the same fundamental ceiling: every diagram is its own world. The controller
in your topology and the Controller lifeline in your sequence are independent
declarations with no shared source of truth.

---

## Graphviz / DOT

**One-line summary:** Unmatched for graph rendering; built for graphs, not
architecture documentation.

Graphviz produces excellent results for dependency graphs, call graphs, and
automaton diagrams. The DOT language is expressive for directed graphs and has
the deepest AI training coverage of any diagram language.

**Branding:** Styles are set per-element via a CSS-like attribute bag. The
output looks like a graph -- which is accurate, because that is what it is.

**Expressive power:** Graphviz's layout algorithms (dot, neato, fdp) are
optimised for graph aesthetics. Override positions with `pos=` and the result
fights the engine. Nested subgraphs exist but behave as visual clusters, not
containment hierarchies. No shared model, no typed edges, no lifecycle, no
sequences.

**Maintainability:** Text-based. Same re-declaration problem as every other
tool in this category: diagrams describing the same system are independent
documents that diverge over time.

**The gap:** Graphviz is the right tool for a graph. An architecture diagram
is a system viewed from a particular angle -- the angles need to share a
source of truth, and graphs have no such concept.

---

## PlantUML

**One-line summary:** The broadest diagram type coverage; a different diagram
language per type.

PlantUML supports sequence, class, activity, component, state, deployment,
ER, and timing diagrams, all in one tool. For teams that need all of those
types, it is attractive.

**Branding:** `skinparam` gives real theming control. You can match a visual
identity and produce consistent output across diagram types -- the closest
to ggarch on branding among the existing tools. Colour and style are
author-applied rather than type-derived; there is no semantic visual grammar.

**Expressive power:** Each diagram type has its own syntax and its own
renderer. A component diagram and a sequence diagram are separate files;
the `DatabaseService` component and the `DatabaseService` lifeline are
two independent declarations with no shared source of truth. Layout is
auto-generated; PlantUML's layout for complex deployment topologies is
notoriously hard to control. Edge types in component diagrams are free-form
strings or arrow style variants, each diagram's own convention.

**Maintainability:** Text-based and widely supported. The same re-declaration
problem applies across all diagram types: a component and the lifeline
representing the same process are independent declarations. The broad syntax
surface also means different authors tend to know different subsets.

**The gap:** PlantUML proves you can cover many diagram types in one tool.
The open question is making those types views of the same declared model,
so diagrams describing the same system share a source of truth.

---

## Structurizr

**One-line summary:** The closest prior art on shared model and views; the
C4 hierarchy is both its strength and its constraint.

Structurizr introduced the idea that the architecture model should be
declared once and views derived from it. This is the right insight and
Structurizr deserves credit for it. C4 (the model behind Structurizr) is
the most widely adopted structured approach to architecture documentation.

**Branding:** C4 has a defined visual convention -- people are yellow, software
systems are blue, containers are blue/teal, components are green. It is a
semantic grammar of sorts, but it is C4's grammar. Adapting it to a different
brand means overriding the defaults throughout. A single default theme; output
style varies by renderer (Structurizr DSL, C4-PlantUML, Mermaid C4 mode each
produce different output).

**Expressive power:** The shared model is real and it works. The gaps:

- The C4 hierarchy is rigid: Person → Software System → Container →
  Component. Every element must fit one of these four levels. A Kubernetes
  pod, a machine agent, a database record, and a charm process resist the
  mapping -- you either force them into the wrong
  level or leave important distinctions unmodelled.
- Layout is auto-generated; Structurizr gives very limited positional control.
- Dynamic views (the sequence equivalent) cannot include infrastructure nodes
  (deployment nodes) as participants. A bootstrap sequence that involves the
  K8s API falls outside the model's vocabulary.
- No lifecycle or cardinality on elements.
- No abstraction relationships (the C4 hierarchy encodes abstraction
  structurally, but cannot express that two elements at different levels
  are the same thing).

**Maintainability:** Strong, and in the meaningful sense: the Structurizr DSL
is clean text, rename propagates through the shared model, and the validator
catches uses of undeclared elements. This is what maintainability actually
means for architecture documentation.

**The gap:** Structurizr is the right architecture -- shared model, views --
but the C4 type hierarchy is too prescriptive for systems outside the
Person/System/Container/Component ladder. When the model is the right shape,
Structurizr is good. Outside that shape, you either distort the system to fit
C4 or reach for something else.

---

## Ilograph

**One-line summary:** The closest prior art on single-model, multi-view
including sequences; proprietary, closed toolchain.

Ilograph gets the single-model/multi-view architecture right, including
sequence (perspective) views that reference the same declared entities as
topology views. It is the closest existing tool to what architecture
documentation actually needs.

**Branding:** Dark-only theme. Node style is author-applied. The output looks
professional; the style grammar is visual rather than semantic.

**Expressive power:** The shared model is real and sequences use it properly
-- lifelines are the declared nodes, not re-declared participants. The gaps:
layout is auto-generated with limited override; no typed edges; no lifecycle
or cardinality; no abstraction relationships; no constraint-based positioning.

**Maintainability:** The model architecture is right -- single source of
truth, rename propagation. The toolchain is proprietary: diagrams render
only in Ilograph's own web application or VS Code extension, with no
open-source renderer, no CI integration, no Sphinx pipeline. Source
maintainability is real; toolchain maintainability is a vendor dependency.

**The gap:** The right architecture, a proprietary toolchain. ggarch was
partly motivated by Ilograph having found the correct design and then
closing it.

---

## What ggarch adds

The table above shows where text-based alone falls short of maintainability.
Re-declaration tools (Mermaid, D2, Graphviz, PlantUML) are all plain text,
but every diagram is its own world: rename one thing and everything else is
unaware. The meaningful maintainability bar -- shared model, rename
propagation, validator enforcement -- is met only by Structurizr and ggarch
among the tools surveyed. On branding and expressive power, ggarch is the
only tool that combines both.

The specific capabilities ggarch has that no existing tool has:

**Constraint-based layout.** `a left-of b gap: 60` is a constraint, not a
hint. Cassowary solves it. Adding a new node leaves the existing ones in place.
The spatial story you intend to tell is the spatial story the reader sees.
Where you place things says something -- Charmhub below the controller and
apps fanned to the right is an argument about architectural role, not an
aesthetic choice -- and ggarch is the only DaC tool that guarantees that
argument survives rendering.

**Semantic edge types.** `type: stream` renders as a dashed arrow and means
"long-lived watch connection". `type: ipc` renders dotted and means "Unix
socket". The visual grammar is consistent across every diagram in the project;
a reader who learns it once reads every diagram correctly. When the built-in
vocabulary runs out, custom edge types carry their own name and styling
declared in the model's `style` block -- end to end, including the legend.

**Lifecycle.** `lifecycle: init` (dashed border) means "runs once at startup
then exits". `lifecycle: ephemeral` (dotted border) means "runs on demand
then exits". `lifecycle: persistent` (solid border, default) means "runs
continuously". Central to understanding any system with init containers,
bootstrap sequences, or on-demand workers -- a distinction ggarch is alone
in modelling.

**Cross-cutting annotations.** A `box` annotation draws a semantic region
over any set of nodes -- "intent & persistence", "execution boundary" --
regardless of where those nodes sit in the containment hierarchy. The
annotation is a separate layer: it does not distort layout, move nodes, or
create implicit containers. No other text-based tool has layout-transparent
cross-cutting regions.

**Selective zoom.** `collapse` and `expand` are per-node instructions in the
view's `select` block. One view can show the controller as an opaque box
(context only) while showing the unit pod fully expanded (detail). Mix levels
freely in a single diagram -- the interesting detail is in one place; the
rest is context.

**Deployment environments as views.** K8s and machine-cloud are two
deployment views of the same model, not two separate files. An `environment:`
block in the select resolves which concrete nodes are present for that surface
and how abstract ids map to infrastructure. The system is declared once; the
deployment differences are view-level projections.

**Abstraction relationships.** `controller_pod [abstracts: "controller"]`
declares formally that the pod is the concrete deployment of the abstract
controller. Overview diagrams use the abstract id; topology diagrams use the
concrete id. Edges declared at either level stay valid. Renaming propagates.
The validator catches drift immediately if a behaviour step references an
abstract id with no concrete realisation. No other tool has this.

**Types vs instances.** A node with `cardinality: one-per-unit` is a type,
not a unique instance. A view renders it as a single archetype box or
stamps it as N labelled instances -- full subtree stamps: an instance of
a container carries everything inside it, and model edges expand to the
copies by an explicit pairing vocabulary (zip: internal wiring repeated
verbatim in every copy; fan: outside-to-every-copy; mesh: every copy
with every other). Same declaration, many rendering modes; the copies
derive, they do not re-declare.

**Slideshow presentation.** Architecture documentation is an argument, and
arguments have pacing. When a concept spans multiple diagrams that build on
each other, dropping them one after another is visually overwhelming and the
thread gets lost. ggarch lets you group related views into a slideshow
carousel: a static label frames the whole substory, per-slide captions update
as the reader navigates, and a single expand button opens the active slide in
a lightbox. Because the slides are views of a shared model, they are
provably showing the same system from different angles -- coherence the reader
can trust rather than infer.

**Secure and lightweight by design.** No code execution, no network calls at
build time, no Node.js, no headless browser. Four Python dependencies. Builds
offline, runs in CI without special tooling. SVG output is sanitised; all
user strings are escaped before embedding. The Sphinx extension writes only
to `_build`.

**AI-friendly by design.** The five-layer syntax is unambiguous to read and
write without running the tool. An agent can understand a diagram fully from
the source, generate valid ggarch from a prose description, and revise it
without knowing the layout engine's internals -- every spatial decision is
explicit in the positions layer. Required `:alt:` text ensures the diagram's
information content survives text-only rendering. The parsed diagram is a
queryable data structure; JSON export lets an agent answer "which nodes have
type juju-software?" without rendering.

**Runtime/persistence duality.** Every significant entity in a stateful
system has two faces: the process that runs and the database record
that backs it. ggarch's `records:` attribute links a runtime node to
the record node that backs it -- validated (the target must be a
declared record), rendered as a chip on the node, queryable from the
parsed model. One model holds both faces: topology views surface the
persistence face on the runtime boxes; ER views show which processes
each record backs. No existing tool addresses this at all.

**Open source, embeddable.** Apache-2.0. Renders to SVG via a Python library,
a CLI, and a Sphinx extension. Runs anywhere: CI pipelines, Sphinx builds,
local scripts, no vendor account required.

# ggarch — Specification

A Grammar of Architecture Diagrams.

A text-based, constraint-layout diagram tool for architecture documentation,
inspired by the Grammar of Graphics (Wilkinson 2005) and its R implementation
ggplot2. Like ggplot2, ggarch separates a diagram into independent, composable
layers that are declared separately and rendered in a defined order.

**Licence: Apache-2.0.** ggarch is an open source project. Apache-2.0 is
Canonical's standard licence for infrastructure and developer tooling (Juju,
LXD, and most of the ecosystem use it). It permits unrestricted use,
modification, and embedding — including in commercial docs pipelines — with no
conditions beyond attribution and preserving the licence notice. It includes an
explicit patent grant. Generated SVG output is not a derived work of the tool
and carries no licence obligations regardless. GPL-3 was considered; Apache-2.0
was chosen because copyleft friction on embedding would limit adoption without
meaningfully protecting the project.

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

- **Lifecycle/temporal node properties** — no tool natively models 'runs once
  at startup and exits' vs 'runs continuously'. This distinction is central to
  understanding systems like Juju (init containers, bootstrap sequences) and
  has no representation anywhere.
- **Cross-cutting semantic annotation regions** — no text-based tool lets you
  draw a semantic boundary (e.g. 'intent & persistence') that cuts across a
  containment hierarchy without distorting layout or remodelling the tree.

ggarch addresses all of this by separating a diagram into independent,
composable layers — the same insight that made ggplot2 productive for
statistical graphics — and by making the system model a first-class,
separately declared artefact that all views share.

---

## Distributed systems capabilities

These six capabilities are what distributed systems documentation specifically
requires. They are first-class in ggarch; none are fully covered by any
existing text-based tool.

### 1. Multiple views of one model

A system is declared once in a `model` block. Views reference it. The
controller in the topology view and the Controller lifeline in the sequence
view are the same declared entity — not two drawings that happen to share a
label. Views can be topology, control-flow, data-model, or sequence; all draw
from the same model.

### 2. Typed edges

Edges have a semantic `type` drawn from a declared taxonomy. Types are not
just visual styles — they carry meaning that can be queried. Built-in types
for distributed systems:

- `api` — RPC or REST over a network protocol
- `stream` — long-lived connection (websocket, gRPC stream)
- `event` — one-way notification
- `data` — data read/write (database, object store)
- `control` — process control (exec, signal, lifecycle management)
- `ipc` — local inter-process (Unix socket, pipe, shared memory)
- `pebble` — Pebble HTTP API (Juju-specific; illustrates custom types)

Custom types can be declared in the `model` and mapped to styles.

### 3. Lifecycle and cardinality on nodes

Every node can declare:

- `lifecycle: persistent | init | ephemeral`
  - `persistent` — runs continuously (default)
  - `init` — runs once at startup, then exits (K8s init containers, bootstrap
    steps)
  - `ephemeral` — runs on demand, exits (hook dispatch, one-off jobs)
- `cardinality: one-per-deployment | one-per-model | one-per-application |
  one-per-unit | one-per-host | N`
  — expresses the multiplicity of the entity in a live deployment. Rendered
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
The lifelines in a sequence diagram are not re-declared — they are the same
nodes, resolved from the model. This means a sequence diagram is automatically
consistent with the topology: renaming a node in the model renames it in every
view.

Sequence steps support: `call`, `return`, `async`, `loop`, `alt` (condition
branches). The unit agent's wait/snapshot/resolve/dispatch/commit loop, the
bootstrap sequences for K8s and machine clouds, and the hook execution sequence
in the Juju docs are all expressible as sequence views over the same model.

### 6. Deployment environments as views

A system can be deployed in multiple environments (Kubernetes, machine cloud,
LXD). These are not separate systems — they are different deployment views of
the same model. ggarch treats them as `environment` variants, each specifying
which nodes are present and how they map to infrastructure. The K8s topology
and machine topology of Juju are two environment views of one model, not two
separate pictures.

---

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
`dynamic view` re-declared interaction steps at the view level — breaking
declare-once and making sequence diagrams orphans that diverged silently from
the model. In ggarch, `behaviour` blocks in the model are first-class
declarations on equal footing with `nodes` and `edges`. Views project
behaviours; they do not define them.

### Views are projections only

A view selects from the model, controls spatial layout, and adds visual
annotations. That is all it can do.

```
// Topology view — selects nodes, declares positions and annotations
diagram "K8s deployment" from "Juju" {
  select {
    nodes: controller_pod unit_pod
    edges: type api type stream   // filter by edge type
    environment: kubernetes
  }
  positions { ... }    // spatial constraints for this view only
  annotations { ... }  // overlaid regions and callouts for this view only
}

// Sequence view — selects a behaviour, optionally filters participants
sequence "Hook execution" from "Juju" {
  select {
    behaviour: "hook execution"
    // participants: unit_agent charm controller  // optional filter
  }
  annotations { ... }  // optional: highlight regions on the sequence
}

// Environment view — same model, different deployment surface
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
something not in the model, the model must be extended — not the view.

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
1. `select` — filter model nodes and edges for this view
2. `positions` — constraint solver produces node coordinates
3. edge routing — uses solved positions, never influences them
4. `annotations` — drawn last, on top, without affecting layout


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
  — there are no implicit defaults that require knowing the layout engine's
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
diagram — so every view shares the same node definitions.

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
- `type` — maps to the style grammar; also used to filter nodes into views
- `label` — display text; `\n` for line breaks
- `lifecycle: persistent | init | ephemeral` — persistent (default) renders
  with a solid border; init with a dashed border; ephemeral with a dotted
  border. Can be overridden in the style layer.
- `cardinality: one-per-deployment | one-per-model | one-per-application |
  one-per-unit | one-per-host | N` — rendered as a badge or multiplicity cue;
  queryable from JSON export

Nodes are pure model declarations — no position, no edges. Containment is a
visual grouping hint; it does not imply edges or constraint priority.

---

## Layer 2: positions (in views)

Declares spatial constraints. The constraint solver (kiwisolver/Cassowary)
produces x/y coordinates that satisfy all constraints. Constraints are
relative, not absolute. Constraints are strict — a conflict is an error, never
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
- `left-of`, `right-of`, `above`, `below` — cardinal placement, optional `gap`
- `align-top`, `align-bottom`, `align-left`, `align-right`, `align-middle`,
  `align-centre`
- `same-width`, `same-height`, `same-size`
- `direction: left | right | up | down` — layout direction for children
- `grid: rows cols` — arrange children in a grid

---

## Layer 3: edges (in the model)

Declares relationships between model nodes. Edges carry a semantic `type`
in addition to a label. Edge types are not just visual — they are queryable
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
- `type` — semantic type from the built-in taxonomy or a custom declared type:
  `api`, `stream`, `event`, `data`, `control`, `ipc`, `pebble`
- `protocol` — optional protocol detail (e.g. `websocket-rpc`, `http`,
  `unix-socket`); rendered as a secondary label or tooltip
- `label` — primary display text
- `style` — dashed, dotted, solid; defaults from type via style grammar
- `arrow` — none, forward (default), back, both

Custom edge types are declared in the `style` block and map to a visual style.

Routing strategy: straight lines by default. Orthogonal routing as an opt-in
per diagram or per edge, pending a production-ready Python binding for
adaptagrams libavoid.

---

## Layer 4: behaviours (in the model)

Declares named interaction sequences between model entities. Behaviours are
first-class model declarations — not view-level constructs. Every participant
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
- `call` — synchronous invocation; renders as solid arrow
- `return` — response to a prior call; renders as dashed return arrow
- `async` — fire-and-forget notification; renders as open arrowhead
- `self` — self-call (a node acting on itself); renders as loop arrow
- `loop "label" { ... }` — repeated sequence
- `alt "condition" { ... } else "condition" { ... }` — conditional branches
- `par { ... }` — parallel steps

Because behaviours are in the model, they are:
- **Consistent** — renaming `unit_agent` renames it in every behaviour
- **Validatable** — a step referencing a node not in `nodes` is a parse error
- **Queryable** — "which nodes participate in bootstrap?" answerable from JSON
- **Projectable** — a `sequence` view selects a behaviour and renders it with
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
- `box` — rectangle enclosing a set of nodes, with optional label
- `callout` — text label anchored to a node or region
- `separator` — a line between two groups of nodes
- `badge` — a small label on a node (e.g. "(init)" on Pebble)

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

### Phase 1 — parser + data model
Parse the model/view syntax into a Python data structure. Validate: node ids
unique, edge endpoints exist, behaviour participants exist in nodes, behaviour
steps traverse declared edges, view `select` targets exist in model.
Library: `lark` (MIT).

### Phase 2 — constraint solver
Translate position constraints into kiwisolver expressions. Solve to produce
(x, y, width, height) for every node in a view. Handle containment (parent
bounds contain all children). Library: `kiwisolver` (BSD).

### Phase 3 — straight-line edge routing
Compute start/end anchor points on node boundaries. Route straight lines (or
two-segment elbows for same-axis nodes). No external dependency.

### Phase 4 — SVG renderer
Render nodes (with lifecycle and cardinality visual cues), edges (with type
styling), and annotations to SVG using `drawsvg` (MIT). Light and dark
variants. Correct font sizing, text wrapping, multi-line labels. JSON export.

### Phase 5 — sequence view renderer
Render `sequence` views as sequence diagrams with lifelines sourced from the
model. Steps: `call`, `return`, `async`, `loop`, `alt`.

### Phase 6 — Sphinx extension
`sphinxcontrib_ggarch.py` following the pattern of `sphinxcontrib_d2.py`.
`{ggarch}` directive with `view` selector, required `:alt:`, light/dark pair
output, markdown visitor that emits source verbatim.

### Phase 7 — orthogonal routing (optional)
Plug in adaptagrams libavoid when a production-ready Python binding exists.
Straight-line routing remains the default.

---

## Dependencies

| Dependency  | License | Purpose          |
|-------------|---------|------------------|
| `lark`      | MIT     | Grammar / parser |
| `kiwisolver`| BSD     | Constraint solver |
| `drawsvg`   | MIT     | SVG generation   |
| `sphinx`    | BSD     | Extension host   |

No copyleft. No binary builds. No npm. No network at build time.

---

## Open questions

1. **Shorthand syntax.** The model/view structure is verbose for simple
   one-off diagrams. Consider a `diagram` block without an explicit `model`
   that inlines all five layers — equivalent to the original spec, for cases
   where multi-view reuse is not needed.

2. **Model file vs inline.** Should the model be declarable in a separate
   `.ggarch` file and referenced by multiple doc pages? This would let all
   the Juju architecture diagrams share one canonical model file.

3. **Constraint relaxation policy.** If constraints conflict: error (current
   plan) or relax lowest-priority constraint with a warning? Error — silent
   relaxation is how ELK and dagre caused problems in practice.

4. **Cardinality rendering.** Badge vs multiplicity cue (stacked boxes) vs
   text annotation. Stacked boxes (like UML instance notation) may be clearest
   but add visual noise. Start with a badge and revisit.

5. **Edge type taxonomy.** The built-in types (`api`, `stream`, `event`,
   `data`, `control`, `ipc`) cover the Juju case. Are they general enough for
   other distributed systems? Should the built-in set be smaller (fewer
   assumptions) or richer?

6. **Style presets.** `juju` ships built-in. Mechanism for third-party presets
   distributed as Python packages (`ggarch-style-juju`)?

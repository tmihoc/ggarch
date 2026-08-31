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

Every mainstream text-based diagram tool (Mermaid, D2, Graphviz) conflates
three concerns in a single syntax:

1. **What nodes exist and what they are**
2. **Where nodes are positioned**
3. **How nodes relate to each other**

The layout engine then infers positions from edge structure, which means
spatial intent is routinely overridden by global edge-crossing optimisation.
Annotations (dashed boxes, callout labels, region shading) have no first-class
home and either distort layout or don't exist at all.

ggarch separates these concerns into independent, composable layers — the same
insight that made ggplot2 productive for statistical graphics.

---

## Core idea: layers

A ggarch diagram is a stack of layers applied in order. Each layer is
independently declared and does not affect the concerns of other layers.

```
diagram "Juju architecture" {
  nodes { ... }        // layer 1: what exists
  positions { ... }    // layer 2: where things go
  edges { ... }        // layer 3: how things connect
  annotations { ... }  // layer 4: overlaid callouts and regions
  style { ... }        // layer 5: visual grammar
}
```

Layers are always evaluated in this order. Positions are solved before edges
are routed. Annotations are drawn last, on top of everything else.

---

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

## Layer 1: nodes

Declares what exists. Nodes have an id, a label, and an optional type.
Types map to the style grammar. Nesting creates containment.

```
nodes {
  user [type: person, label: "User"]

  juju [type: juju-software, label: "Juju"] {
    client [type: juju-software, label: "Client"]
    controller [type: juju-software, label: "Controller"]
  }

  clouds [type: external, label: "Clouds\n(AWS, GCP, K8s…)"]
  charmhub [type: external, label: "Charmhub"]

  app1 [type: unit, label: "Application 1 unit"] {
    agent1 [type: juju-software, label: "Unit agent"]
    charm1 [type: charm, label: "Charm"]
    workload1 [type: workload, label: "Workload"]
  }
}
```

Nodes are pure declarations — no position, no edges. Containment is a visual
grouping hint; it does not imply edges or constraint priority.

---

## Layer 2: positions

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

## Layer 3: edges

Declares relationships. Edges are routed after positions are solved, so
routing never influences layout.

```
edges {
  user -> juju.client [label: "declares intent"]
  juju.client -> juju.controller [label: "Juju API"]
  juju.controller -> clouds [label: "provisions infrastructure"]
  juju.controller -> charmhub [label: "fetches charms"]
  juju.controller -> app1.agent1 [label: "Juju API\n(websocket)"]
  app1.agent1 -> app1.charm1 [label: "dispatch"]
  app1.charm1 -> app1.workload1 [label: "operates"]
}
```

Edge attributes:
- `label` — text on the edge
- `style` — dashed, dotted, solid (default)
- `arrow` — none, forward (default), back, both
- `color` — override style grammar colour

Routing strategy: straight lines by default. Orthogonal routing (horizontal/
vertical segments only) as an opt-in per diagram or per edge, pending a
production-ready Python binding for adaptagrams libavoid.

---

## Layer 4: annotations

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

## Layer 5: style

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
Parse the five-layer syntax into a Python data structure. Validate: node ids
unique, edge endpoints exist, constraint targets exist. Library: `lark` (MIT).

### Phase 2 — constraint solver
Translate position constraints into kiwisolver expressions. Solve to produce
(x, y, width, height) for every node. Handle containment (parent bounds
contain all children). Library: `kiwisolver` (BSD).

### Phase 3 — straight-line edge routing
Compute start/end anchor points on node boundaries. Route straight lines (or
two-segment elbows for same-axis nodes). No external dependency.

### Phase 4 — SVG renderer
Render nodes, edges, annotations to SVG using `drawsvg` (MIT). Light and dark
variants. Correct font sizing, text wrapping, multi-line labels. JSON export.

### Phase 5 — Sphinx extension
`sphinxcontrib_ggarch.py` following the pattern of `sphinxcontrib_d2.py`.
`{ggarch}` directive, required `:alt:`, light/dark pair output, markdown
visitor that emits source verbatim.

### Phase 6 — orthogonal routing (optional)
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

1. **Shorthand syntax.** The five-section structure is verbose for small
   diagrams. Consider allowing `positions`, `edges`, `annotations`, `style`
   to be omitted, defaulting to auto-layout (top-down), no edges, no
   annotations, and the `juju` style preset.

2. **Multi-diagram files.** A single `.ggarch` file containing multiple named
   diagrams referenceable by name from different doc pages.

3. **Constraint relaxation policy.** If constraints conflict: error (current
   plan) or relax lowest-priority constraint with a warning? Leaning toward
   error — silent relaxation is how ELK and dagre caused problems in practice.

4. **Style presets.** `juju` ships built-in. Mechanism for
   third-party presets distributed as Python packages
   (`ggarch-style-juju`)?

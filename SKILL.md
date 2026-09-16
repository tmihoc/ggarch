# SKILL.md -- How to use ggarch

This file explains how to write and edit ggarch diagrams. It is written for
both human authors and AI coding assistants working on a ggarch codebase.

---

## Mental model

An `.ggarch` file has two parts:

1. **The model** -- declares what exists: nodes, edges, behaviours, style.
   This is the system's source of truth.
2. **Views** -- select subsets of the model and arrange them. Each view
   produces one diagram. The same node can appear in many views; you declare
   it once.

The key rule: **everything describing the system goes in the model. Views
have only `select`, `positions`, and `annotations`.**

A single `.ggarch` file can hold one model and arbitrarily many views of it.
Large systems may use multiple `.ggarch` files, each with its own model, but
sharing is done by co-locating related concerns in one model rather than by
importing between files.

---

## File anatomy

```
// Comments use //

model "Name" {

  nodes {
    id [type: TYPE, label: "Human label"]
    id [type: TYPE, label: "Label", lifecycle: LIFECYCLE]
    parent [type: container, label: "Pod"] {
      child [type: juju-software, label: "Agent"]   // nested = contained
    }
  }

  edges {
    source -> target [type: EDGE_TYPE]
    source -> target [type: EDGE_TYPE, label: "describes the relationship"]
  }

  behaviours {
    behaviour "Name" {
      a -> b: call  "step label"
      b -> a: return
      a -> a: self  "internal step"
      c -> d: async "fire and forget"
      loop "label" { ... }
      alt "condition" { ... } else "other" { ... }
    }
  }

  style { extends: juju }   // use the Juju colour preset

}

diagram "View name" from "Model Name" {
  select {
    nodes: id1 id2 id3          // which nodes to show
    edges: type api type stream  // which edge types to include
    collapse: id4               // show id4 as an opaque box (hide children)
  }
  positions {
    a left-of b gap: 60
    a align-middle b
    c above b gap: 40
    c align-centre b
    fan [x y z] right-of b gap: 40   // fan layout for a list of nodes
    b direction: right               // lay out b's children left-to-right
  }
  annotations {
    box [nodes: "id1 id2", label: "annotation label",
         style: "dashed", color: "#888"]
    legend [position: "bottom-right",
            juju-software: "Juju process",
            stream: "watch (async)"]
  }
}

sequence "View name" from "Model Name" {
  select { behaviour: "Behaviour name" }
}
```

---

## Node types

| Type | Rendered as | Meaning |
|---|---|---|
| `juju-software` | Orange rect | Juju process or agent |
| `container` | Warm orange tint, rounded | Juju-owned pod or machine |
| `charm` | White rect, orange border | Charm code |
| `workload` | Gray rect | Application workload |
| `pebble` | Light blue rect | Pebble supervisor |
| `external` | Gray rect, solid border | Outside Juju's ownership |
| `person` | Gray rect + head icon | Human actor |
| `database` | Amber cylinder | Database or storage |
| `record` | Amber table | Database record / ER row |
| `class` | Amber compartment | Class or component |

Any string not in this list falls back to the default style. Custom types can
be defined in the `style` block.

### Node attributes

```
id [type: TYPE, label: "Label"]
id [type: TYPE, label: "Label", lifecycle: init]       // dashed border
id [type: TYPE, label: "Label", lifecycle: ephemeral]  // dotted border
id [type: TYPE, label: "Label", lifecycle: persistent] // solid border (default)
id [type: TYPE, label: "Label", cardinality: one-per-unit]
id [type: TYPE, label: "Label", scope: "cloud1/model1"]  // scope chip
id [type: TYPE, label: "Label", abstracts: "abstract_id"]
```

Multi-line labels use `\n`:

```
id [type: juju-software, label: "Unit agent\n(jujud)"]
```

### Nesting

Indent child nodes inside a parent's `{}` block. The parent must have a
container-like type (e.g. `container`). Any node can technically have
children, but `container` is the idiomatic choice for pods and machines.

```
unit_pod [type: container, label: "Unit pod"] {
  unit_agent [type: juju-software, label: "Unit agent"]
  charm      [type: charm,         label: "Charm"]
}
```

---

## Edge types

| Type | Dash pattern | Meaning |
|---|---|---|
| `api` | solid | RPC or REST call |
| `control` | solid | process lifecycle / drives |
| `data` | solid | database read/write |
| `stream` | `6,3` dashed | long-lived connection, watch |
| `event` | `6,3` dashed | one-way async notification |
| `ipc` | `2,2` dotted | Unix socket / in-process |

`stream` is the most load-bearing: dashed communicates "this is a watch, not
a direct call" to readers who would otherwise read a solid arrow as synchronous.

```
a -> b [type: stream, label: "watches for changes on"]
```

---

## Writing a diagram: step by step

### 1. Identify the nodes

List every entity that needs to appear in at least one diagram. Assign each a
short lowercase `id` (no spaces; use `_`). Choose a `type` from the table
above. Write the label as the reader would see it.

### 2. Declare containment

If a node runs inside another (a process inside a pod, a worker inside an
agent), make it a child. The containment hierarchy determines what `collapse`
and `expand` mean in views.

### 3. Declare edges in the model

All edges go in `edges {}`, regardless of which views will show them. A view's
`select { edges: type X }` filter decides which edges appear in that view.

Edges reference nodes by id, not by label. An edge between a parent and a
child is valid even if the parent is later collapsed in a view -- the
collapsed box inherits the edge.

### 4. Declare behaviours for sequences

A `behaviour` is a named ordered list of steps over model nodes. Steps:

```
a -> b: call  "label"    // synchronous call (solid arrow, activation bar)
b -> a: return "label"   // return
a -> b: async "label"    // fire-and-forget (open arrowhead)
a -> a: self  "label"    // self-call

loop "label" {
  a -> b: call "in loop"
}

alt "success" {
  a -> b: call "happy path"
} else "failure" {
  a -> b: call "error path"
}

par "parallel fragment" {
  a -> b: async "lane 1"
  c -> d: async "lane 2"
}

opt "optional fragment" {
  a -> b: call "only sometimes"
}
```

Labels are optional on `return` and on steps inside blocks.

### 5. Write diagram views

A `diagram` view selects nodes and edges, positions them, and optionally
annotates. Start with a minimal select and add constraints one at a time.

**Node selection:**

```
select { nodes: id1 id2 parent_id }
```

Selecting a parent automatically includes all its children. To show a parent
as an opaque box:

```
select {
  nodes: id1 parent_id
  collapse: parent_id
}
```

**Edge selection:**

```
edges: type api type stream    // include edges of these types
edges: id1 -> id2              // include this specific edge
```

Without `edges:`, no edges are shown.

**Positions:**

Every node in the select must be positioned. Constraints compose; you cannot
over-constrain (the solver will error). Common patterns:

```
// Horizontal chain
a left-of b gap: 60
a align-middle b
b left-of c gap: 60
b align-middle c

// Satellite (thing above and below a central node)
cloud above hub gap: 40
cloud align-centre hub
db    below hub  gap: 40
db    align-centre hub

// Fan (spread a list evenly around a central node)
fan [x y z] right-of hub gap: 60

// Container children ordered left to right
container_id direction: right

// Size constraints
a same-width b
a min-width: 160
```

`gap:` is a floor -- the solver expands it if edge labels need more space.

### 6. Write sequence views

A sequence view needs only one line:

```
sequence "View name" from "Model Name" {
  select { behaviour: "Behaviour name" }
}
```

Lifelines are generated from the participants of the selected behaviour. Their
order in the rendered diagram follows the order of first appearance in the
behaviour steps.

---

## Annotations

### Box annotation

Draws a dashed (or solid) region around a set of nodes:

```
annotations {
  box [nodes: "id1 id2",
       label: "intent & persistence",
       style: "dashed", color: "#888"]
}
```

The box is layout-transparent: it does not affect constraint solving.

### Legend annotation

Documents the visual grammar used in this view:

```
annotations {
  legend [position: "bottom-right",
          person: "operator",
          juju-software: "Juju process",
          external: "cloud / external",
          stream: "watch (async)",
          ipc: "hook command (local socket)"]
}
```

Keys are node types or edge types. Values are the human-readable label for
that entry. Include only entries a reader needs to decode the diagram
independently -- things the caption already covers can be left out.

---

## Abstraction relationships

A concrete node can declare that it realises an abstract node:

```
controller_pod [type: container, label: "Controller pod",
                abstracts: "controller"]
```

This means:
- Edges declared using `controller` are valid -- the validator treats them
  as covered by `controller_pod`.
- High-level views can use `controller`; deployment views use `controller_pod`.
- The model knows they are the same entity at different zoom levels.

Use `abstracts:` when you want both an overview view (showing the abstract
node) and a topology view (showing the concrete node); edges declared once
at either level stay valid in both.

---

## Sphinx extension

In `conf.py`:

```python
extensions = ["ggarch.sphinxcontrib_ggarch"]
```

In a Markdown (MyST) document:

````
```{ggarch}
:file: path/to/file.ggarch
:view: View name
:caption: Human-readable caption shown below the diagram.
:alt: Alt text for accessibility.
```
````

For sequence views use `:sequence:` instead of `:view:`.

**Slideshow** -- render multiple views as a carousel with prev/next navigation:

````
```{ggarch}
:file: path/to/file.ggarch
:slides: View one | View two | View three
:caption: A static label that frames the whole slideshow.
:slide-captions: Caption for slide 1. | Caption for slide 2. | Caption for slide 3.
:alt: Alt text for accessibility.
```
````

`:caption:` in slideshow mode is a static label rendered above the carousel --
it frames the whole story and stays constant as the reader navigates.
`:slide-captions:` supplies the per-slide text in the figcaption, updated on
each nav step. Both are optional independently. Views and sequences can be
mixed freely in `:slides:`.

Options:

| Option | Effect |
|---|---|
| `:file:` | Path to `.ggarch` file, relative to the document |
| `:view:` | Name of the diagram view to render |
| `:sequence:` | Name of the sequence view to render |
| `:slides:` | Pipe-separated view/sequence names for a slideshow |
| `:caption:` | Single diagram: figure caption. Slideshow: static label above carousel. |
| `:slide-captions:` | Pipe-separated per-slide captions; updated on navigation |
| `:alt:` | Alt text |
| `:no-legend:` | Suppress the HTML legend strip |

The extension caches rendered SVGs by hashing the source file content, view
name, theme, and ggarch version. After changing renderer Python code, bump
`__version__` in `src/ggarch/__init__.py` and run:

```bash
rm -f _build/_images/ggarch-*.svg && make rebuild-ggarch
```

---

## Editing workflow

**Validate without rendering:**

```bash
ggarch check my-system.ggarch
```

This runs the parser and validator and reports any errors: unknown node ids,
duplicate ids, edges referencing non-existent nodes, and constraint
conflicts.

**Render a single view to SVG:**

```bash
ggarch render my-system.ggarch "View name" --out view.svg
ggarch render my-system.ggarch "View name" --out view-dark.svg --dark
```

**Render all views programmatically:**

```python
from ggarch import parse, validate, solve, route, render
from ggarch.sequence_renderer import render_sequence

f = parse(open("my-system.ggarch").read())
validate(f)
for d in f.diagrams:
    m = f.get_model(d.model_name)
    svg = render(route(solve(d, m), m, d.select), m, d)
    open(f"{d.name}.svg", "w").write(svg)
for s in f.sequences:
    svg = render_sequence(s, f.get_model(s.model_name))
    open(f"{s.name}.svg", "w").write(svg)
```

**Live preview with Sphinx:**

```bash
make run    # from the docs directory
# http://127.0.0.1:8000/
```

The server rebuilds on every `.ggarch` or `.md` save.

---

## Common patterns

### Collapse one half, expand the other

```
diagram "Unit focus" from "My system" {
  select {
    nodes: controller_pod unit_pod
    collapse: controller_pod   // opaque box, context only
  }
  positions {
    controller_pod left-of unit_pod  gap: 80
    controller_pod align-middle unit_pod
    unit_pod direction: right
  }
}
```

### Show different zoom levels of the same entity

Declare the abstract node in the model. Mark the concrete node with
`abstracts:`. Use the abstract id in overview views; the concrete id in
topology views:

```
// Model
controller     [type: juju-software, label: "Controller"]
controller_pod [type: container, label: "Controller pod",
                abstracts: "controller"]

// High-level view
select { nodes: user client controller agents }

// Detailed view
select { nodes: controller_pod unit_pod }
```

### Multiple units as instances

Declare one type node with `cardinality: one-per-unit`. In a view, render
it as multiple labelled instances:

```
// Model
unit_pod [type: container, label: "Unit pod", cardinality: one-per-unit]

// View
select { nodes: controller unit_pod }
instances { unit_pod: ["postgresql/0", "pgbouncer/0"] }
```

### Scope chips (provenance tags)

Add `scope: "label"` to a node. A small colored pill appears at the
bottom-right corner:

```
capp1 [type: charm, label: "app 1", scope: "cloud1/model1"]
```

Color is derived deterministically from the scope string. Useful for showing
that nodes belong to different models or clouds in the same diagram.

---

## Troubleshooting

**"Unknown node id"** -- the id used in an edge or view does not match any
node declared in the model. Check for typos; ids are case-sensitive.

**"Duplicate id"** -- two nodes share the same id. Each id must be unique
within a model.

**Constraint conflict / solver error** -- two position constraints contradict
each other (e.g. `a left-of b` and `b left-of a` with no room to satisfy
both). Remove one or increase the gap.

**Stale SVG in Sphinx** -- after changing renderer Python code, the cache may
serve the old output. Run `rm -f _build/_images/ggarch-*.svg && make
rebuild-ggarch`.

**Edge not showing** -- check that the edge's type is included in the view's
`select { edges: type X }` filter. Edges are opt-in per view.

**Children not showing** -- if the parent node appears in the select but its
children don't, the parent defaults to expanded. If it's collapsed, add
`collapse: parent_id` to the select. If it should be expanded, ensure the
children's types and the edges between them are also selected.

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
    instances: id1 [            // stamp a type as N labelled copies (see Instances)
      { id: copy1, label: "copy 1" }
    ]
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
| `juju-software` | Grey rect + Juju badge (orange "J") | Juju process or agent |
| `container` | Warm orange tint, rounded | Juju-owned pod or machine |
| `charm` | Grey rect, orange border + empty badge | Charm code (external software wrapped in Juju packaging) |
| `workload` | Gray rect | Application workload |
| `pebble` | Light blue rect | Pebble supervisor |
| `external` | Gray rect, solid border | Outside Juju's ownership |
| `person` | Gray rect + head icon | Human actor |
| `database` | Amber cylinder | Database or storage |
| `record` | Amber table (+ record badge on plain records) | Database record / ER row |
| `class` | Amber compartment | Class or component |

Node kinds carry a ~14px corner badge (the person's head icon is the
precedent); fills go light/grey across the board and the badge — not
the fill — says what the node is (round 24, verdict A).

Any string not in this list falls back to the default style. Custom node and
edge types are defined in the `style` block:

```
style {
  extends: juju

  my-node-type { fill: "#123456" stroke: "#456" }     // custom node type
  edge my-edge-type { stroke: "#8E44AD" stroke-width: 2 }  // custom edge type

  @dark {
    edge my-edge-type { stroke: "#BB8FCE" }          // dark-mode override
  }
}
```

Edge rules accept `stroke`, `stroke-width`, `stroke-dash`, `font-color`,
`font-size`. An edge whose type is neither built-in nor styled in the style
block is a validation error (catches typos).

### Node attributes

```
id [type: TYPE, label: "Label"]
id [type: TYPE, label: "Label", lifecycle: init]       // dashed border
id [type: TYPE, label: "Label", lifecycle: ephemeral]  // dotted border
id [type: TYPE, label: "Label", lifecycle: persistent] // solid border (default)
id [type: TYPE, label: "Label", cardinality: one-per-unit]
id [type: TYPE, label: "Label", scope: "cloud1/model1"]  // scope chip
id [type: TYPE, label: "Label", abstracts: "abstract_id"]
id [type: TYPE, label: "Label", records: "unit_rec"]  // record backing this node
                                                      // (chip derives: DDL ground or
                                                      // record label — never the id;
                                                      // upward-closed to containers)
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

Edge identity is three channels (ADR-004): **rhythm** (dash = timing),
**arrowhead** (commitment: filled = the end commits, open =
fire-and-forget, none = headless), **colour** (ownership). A reader
learns the three channels once and reads every diagram.

| Type | Rhythm | Head | Colour | Meaning |
|---|---|---|---|---|
| `api` | solid | filled | `#555555` | RPC or REST call |
| `control` | solid | filled | `#555555` | process lifecycle / drives (visually = `api`, ratified) |
| `data` | solid | filled | amber | pointer / persistence (see **Data model views**) |
| `stream` | `6,3` | filled | `#555555` | long-lived connection, watch |
| `event` | `6,3` | open | `#888888` | one-way async notification |
| `ipc` | `2,2` | filled | `#888888` | Unix socket / in-process |

`stream` is the most load-bearing: dashed communicates "this is a watch, not
a direct call" to readers who would otherwise read a solid arrow as synchronous.
`event` carries the open head: a notification commits nothing.

Any other type name is custom: declare it in the style block
(`edge <name> { ... }`, see **Node types** above) or validation fails.
Custom types compose the declared channels:

```
edge notify { stroke-dash: "6,3" arrowhead: open }   // async family
edge memo   { arrowhead: none }                      // headless
```

`arrowhead` is a closed enum — `filled | open | none`; anything else is
a validation error. The per-edge `arrow:` attribute (forward / back /
both / none) says *which ends* state the fact and composes with the
head shape.

```
a -> b [type: stream, label: "watches for changes on"]
```

Edges between children of an instanced type expand per copy according
to their **pairing** -- zip by default, `pairing: mesh` for
between-copies wiring. See **Instances** below.

---

## Label wording

An edge label has two flows to respect: the arrow's (geometry) and the
sentence's (semantics). Both follow one taste: **flip the least thing
that restores flow; never let two channels argue.**

1. **Alignment.** The label's subject is the arrow's source; its
   object is the target. `unit -> application: "belongs to"` reads
   with the arrowhead. The same fact phrased against an unchanged
   arrow ("application has units" on a unit->application edge) is the
   passive voice -- the reading sense runs counter to the arrow. Fix
   the wording, not the arrow: converse phrasing *with* a flipped
   arrow is a different fact, not a paraphrase.
2. **Composition.** Where a view argues a chain, keep it one directed
   path; each label's object becomes the next label's subject
   ("a relation has 2 endpoints; each belongs to one application").
   Chain direction is the view's argument.
3. **Menu honesty.** Prefer idiomatic aligned verbs. When the verb
   menu has no idiomatic aligned phrase ("belongs to"), the awkward
   aligned one beats the natural counter-flowing one.
4. **Counts don't travel.** A multiplicity quantifies the target set
   per subject ("each application has 0..N units"). Rephrase to the
   converse and you change the quantifier's domain: swap the count to
   the other half or drop it -- never carry it across. One half per
   label by default; a full-ratio parenthetical (subject-side first:
   "1..N" becomes "N..1" when the phrase flips) only when the view
   needs both halves, the verb underdetermines, or the count is the
   message.
5. **Truth-makers.** Every number carries a witness: the FK-stored
   half where a schema governs; `0..N` as the unwitnessed honest
   default; a positive minimum requires a named invariant
   (subordinate applications have zero units until a relation acquires
   one -- `1..N` on application->unit is false, not merely unproven).
6. **Directionless phrasing.** The arrowhead carries all direction;
   the label names the relationship ("api", "watch", "belongs to").
   Direction-bearing wording is a smell: it usually means you wanted
   two edges, or the arrow points the wrong way.
7. **One verb per facet.** The same channel drawn in several views (an
   edge of one type between the same kinds of nodes) carries the SAME
   label everywhere. The view chooses which facet to draw, not a new
   verb for it. (Measured drift: the agent-to-controller api facet
   shipped as "connects to", "connects via Juju API", "calls Juju API"
   and unlabelled across view eras -- normalized 2026-09-21 to "makes
   API calls to".)

Two sub-policies:

- The parenthetical doubles as the collective/distributive marker.
  Counts read distributively over the subject ("each application
  has..."); a total over internal structure says so:
  `"has 2 (one per side)"`.
- Mixing exact words and ranges is policy, not drift: exact small
  counts as words ("(one)", "2"), unbounded as ranges ("0..N").

On labels and length: **labels name, annotations explain.** If edge
text stops fitting its leg, the model wants an annotation (box,
callout), not a longer label.

### Data model views: where the pointers live

An association is non-directional; a relational schema is not. The DDL
stores exactly one directed fact per association: **which column holds
the pointer** (child table's FK column → parent table's PK). A Data
model view is a portrait of that fact -- nothing more, nothing less.

Crow's-foot glyphs (round 24, verdict B): `data` edges whose label
carries the cardinality vocabulary grow a multiplicity glyph at the
TARGET end — a fork for many (`0..N`, `1..N`), a bar for one
(`(one)`, `1:1`, `1..1`, `0..1`). The verb stays in the label (ADR-002);
the glyph is draw-only (no anchor moves, the audit sees the same
geometry).

- Arrows run FK → PK: the only direction the storage layer states.
  Labels align to that arrow, child-first ("belongs to").
- **Field badges are the count witnesses.** `fk:` (non-null) asserts
  "exactly one" on the child half; `?` widens it to 0..1. The parent
  half (0..N) is derivable and is never drawn. Edge-label counts
  appear only when the view argues a count (a junction chain, say) --
  bare verbs are the default and are compliant.
- **Every FK column is drawn exactly once.** One column has one FK
  target; two arrows from one column assert a schema-impossible
  reference. The validator enforces this (see Troubleshooting:
  "originates N data edges"). An M:N is drawn as its junction: both
  FK columns, each with its own arrow.
- Full truth is the model's job (grounded to the DDL), never one
  view's. A view asserts the half its angle argues; the shared model
  holds the association itself.

Crow's-foot notation states both halves inline but drops direction
and cannot locate the FK when the association is 1:1. Drawing the
pointer wins for a grounded tool: it is the only half with a
truth-maker.

---

## Writing a diagram: step by step

### 0. Scaffolding from DDL (data-model diagrams)

For entity-relationship views, scaffold instead of hand-writing the
record nodes: `ggarch scaffold <file>.ddl --db model --tables a,b,c`
emits a valid model fragment — record nodes (fields with
`pk:`/`fk:`/`null:` markers), data edges (FK column → parent PK
column, one pointer per distinct target), and `ground:` pointers into
the DDL. The transitive FK-parent closure of the requested tables is
auto-included (pruning a referenced parent would hide the pointer).
The fragment validates by construction — FK-completeness holds at
birth — so your curation (trim tables, name the relationships with
aligned verbs, build the views) happens with the validator watching.

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

**View options (0.26.1):**

```
select {
  nodes: id1 id2
  edges: type api type control
  routing: orthogonal        # axis-aligned legs only (snap-to-grid)
  sizing: uniform            # all selected leaf nodes render one size
  except: client -> cloud app -> charm [type: api]   # curate edges out
  records: shown             # render the runtime->record bridges
  records: hidden            # suppress the derived chips on this view
}
```

- `routing: orthogonal` — the router rejects diagonal legs; every route
  is straight-axis-aligned, an L, or a U. For worker-tree / dependency
  views that read better on a grid.
- `sizing: uniform` — no node gets visual emphasis merely because its
  label is longer: all selected top-level leaf nodes render the same
  size. Containers keep their content-driven size.
- `except:` — view-level curation: drop declared edges from this view
  (source/target pairs, optional `[type: x]` qualifier). The model stays
  complete; each view tells the story it exists to tell. Multiple refs,
  space-separated.
- `records: shown` / `records: hidden` — the bridges render when
  declared (below); `hidden` suppresses the derived chips on this view
  even where nodes carry `records:` (for views whose label crowding the
  chips worsen — the chip design is under review, 2026-09-20).
- `records: shown` — render the runtime→record **bridges** (ADR-005):
  one synthetic edge per recorded node, amber, solid, headless (the
  persistence axis states no call and no pointer; the pointer is the
  data-model view's FK→PK argument). Record nodes auto-include.
  `records:` itself stays a model attribute; the bridge is its
  rendering.

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

Omit the positions block entirely and ggarch auto-lays-out the view:
columns follow topological depth along the selected edges (main flow
left-to-right), branch targets stack in their column, and edges between
containers' children drive the containers' placement. Auto-layout is for
views where any coherent arrangement would do; where the arrangement IS
the argument, declare it -- constraints compose, and you cannot
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

**Solver rules to know:**

- The **first node in `select`** is anchored at (0, 0) — make it the
  intended top-left node of the layout.
- Leaf nodes hold their **natural (label-derived) size**; only
  `min-width` / `same-width` floors can raise it.
- **Label contract (0.25.4, ADR-002)**: labels ride the arrow (along
  the longest leg, above the line — the stroke is never cut). After
  the declared constraints solve, every labelled edge is measured and
  the solver reserves clearance only where the label would strike
  content: a word too wide for the leg, a label strip that would hit
  a node the stroke clears, or a strip crossing its container's wall.
  Declaring `left-of` / `above` between labelled endpoints still
  controls *where* clearance is taken. `gap:` is a floor for the
  widest word plus side padding; labels wrap to the leg, so short
  arrows get multi-line labels, never floating ones.


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

### 7. Write state views

A state view renders a behaviour as a state machine: unique step
participants become states, directed steps become transitions, and
`guard:` / `on:` label them. As with any behaviour, each step must
traverse an edge declared in `edges {}`.

Layout is automatic and layered: the main flow runs left-to-right by
topological depth, branch states stack below their entry column, and
back edges (returns to an earlier state) bow outside the machine. No
positions are declared for state views.

```
behaviour "executor" {
  idle    -> running: call "start"
  running -> idle:    return "stop" [guard: "clean", on: "stopped"]
  running -> error:   async "fail" [guard: "dirty"]
}

state "Executor" from "Model Name" {
  select { behaviour: "executor" }
}
```

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
The canvas expands automatically to fit boxes that extend beyond node bounds.

**Padding** -- `padding` sets uniform space (px) between the annotated nodes'
bounding rect and the box edge. Default is 10. Per-side overrides
`padding-top`, `padding-right`, `padding-bottom`, `padding-left` take
precedence over `padding` for their respective edges. Use per-side padding
when the box needs to extend further in one direction -- for example, wider
horizontally to cross container walls but tight vertically to avoid
overlapping sibling nodes.

**Label placement** -- `label-position` controls where the label appears.
Outside positions place it 14px clear of the box edge. Inside positions
reserve space within the box and place the label in that reserved strip.

| Value | Position |
|---|---|
| `top` | outside, above the box (default) |
| `bottom` | outside, below the box |
| `left` | outside, left of the box |
| `right` | outside, right of the box |
| `inside-top` | inside, strip at the top |
| `inside-bottom` | inside, strip at the bottom |

```
annotations {
  box [nodes: "dqlite1 dqlite2 dqlite3",
       label: "Raft replicaset (strongly consistent)",
       style: "dashed", color: "#888",
       padding: 30, label-position: inside-bottom]
}
```

`inside-bottom` is the right choice when the annotated nodes sit in a row
and the label should read as a caption for the whole region. `top` (the
default) works when there is clear space above the box. `bottom` works when
the label can live outside below the diagram content.

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

## Instances

A view can stamp a declared type as N labelled copies. The copies are
full subtree stamps: an instance of a container renders with everything
inside it, and internal edges redraw per copy.

```
// Model -- declared once
unit_pod [type: container, label: "Unit pod", cardinality: one-per-unit] {
  unit_agent [type: juju-software, label: "Unit agent"]
  charm      [type: charm,         label: "Charm"]
}

// View -- stamped as two copies
select {
  nodes: controller unit_pod
  instances: unit_pod [
    { id: pg0,  label: "postgresql/0" },
    { id: pgb0, label: "pgbouncer/0" }
  ]
}
```

Each instance carries the archetype's type, lifecycle, `records:`, and
whole subtree; its label overrides the archetype label per copy. Stamped
child ids are `<instance>/<child path>` (e.g. `pg0/unit_agent`) --
positions and annotation boxes can reference them.

Model edges expand to the copies by **pairing**:

- **zip** (default): an edge between two archetype children is copied
  per instance, instance i wired to instance i -- the internal wiring
  that repeats verbatim in every copy.
- **fan**: an edge from outside the instanced subtree connects to every
  copy -- star wiring. `controller -> unit_pod` reaches both.
- **mesh** (`pairing: mesh`): an edge between copies -- every distinct
  pair, never a copy with itself:

  ```
  dqlite -> dqlite [type: stream, label: "Raft sync", pairing: mesh]
  ```

  Three instances render six arrows: every node talks to every other.
  This is the truth for peer sync -- Raft replication is full-mesh.

Multiple `instances:` clauses accumulate (one per instanced type).
Instances are view-local: they exist only in the view that declares
them; the model holds the type. Known gap: specific declared pairs
("only copy 1 to copy 2") cannot be expressed; view-level edges are the
answer if a real case appears.

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

`:view:` works for diagram, sequence, and state views -- the directive
searches diagrams first, then sequences, then states. `:sequence:` is
kept as an alias. State views are not yet slideshow-capable.

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
each nav step. Both are optional independently. Views, sequences, and state
machines can be mixed freely in `:slides:`.

Options:

| Option | Effect |
|---|---|
| `:file:` | Path to `.ggarch` file, relative to the document |
| `:view:` | Name of any view to render (diagram, sequence, or state machine) |
| `:sequence:` | Alias for `:view:`; backwards compatible |
| `:slides:` | Pipe-separated view/sequence/state names for a slideshow |
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

Declare one type node. In a view, stamp it as N labelled copies (see
**Instances** above):

```
// Model
unit_pod [type: container, label: "Unit pod", cardinality: one-per-unit]

// View
select {
  nodes: controller unit_pod
  instances: unit_pod [
    { id: pg0,  label: "postgresql/0" },
    { id: pgb0, label: "pgbouncer/0" }
  ]
}
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

**"fk field ... originates N data edges; exactly 1 expected"** -- a
record's `fk:` column has no arrow (N=0: the pointer is hidden) or
several (N>1: one column cannot have two FK targets). Every FK column
is drawn exactly once; see **Data model views** above.

**"data edge ... starts at field ... not marked fk"** -- a data edge is
anchored at a plain field, asserting a pointer with no storage. Mark
the column `fk: true`, or anchor the edge at the node (unqualified) if
no column stores it.

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

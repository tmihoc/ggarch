# ggarch examples

Each `.ggarch` file demonstrates one diagram type or capability. Pre-rendered
SVGs live alongside every source file. To regenerate:

```
cd /path/to/ggarch
.venv/bin/python3 examples/render-examples.py
```

SVGs are named `<file>-light.svg` / `<file>-dark.svg` (one view per file)
or `<file>-0-light.svg` / `<file>-1-light.svg` ... (multiple views per file).

---

## topology.ggarch — deployment topology

**What it shows:** nested containers, typed edges (`control`, `stream`, `api`,
`ipc`, `data`), lifecycle (`init` nodes render with a dashed border), the Juju
colour preset.

**Views (2):**
- `topology-0` — K8s deployment topology: Kubernetes cloud above, controller
  pod with init containers annotated, unit pod to the right with the full
  agent→charm→Pebble→workload chain.
- `topology-1` — Unit focus: controller pod collapsed to a single opaque box
  (context only); unit pod fully expanded to show internal structure.

---

## collapse-expand.ggarch — selective zoom

**What it shows:** `collapse` and `expand` in a single view. One node is
rendered as an opaque box (collapsed); the other shows all its children
(expanded). Both appear in the same diagram with a `callout` annotation.

**Views (1):** `collapse-expand` — controller collapsed, unit pod open.

---

## instances.ggarch — type instantiation

**What it shows:** a single declared node type (`unit_pod`) rendered as
multiple labelled instances in one view. Instances inherit the type's
label, style, and children. Renaming the type renames all instances.

**Views (1):** `instances` — controller pod (collapsed) above two unit
instances labelled `postgresql/0` and `pgbouncer/0`.

---

## sequence.ggarch — sequence diagrams

**What it shows:** sequence views over model behaviours; `call`, `return`,
`async`, `self` step kinds; `loop` blocks; `alt`/`else` conditional branches;
activation bars.

**Views (2):**
- `sequence-0` — Hook execution: the unit agent's watcher→snapshot→resolve→
  dispatch→hook loop, with alt branches for success and failure.
- `sequence-1` — Bootstrap K8s: CLI authenticates with the cluster, deploys
  the controller pod, waits for jujud to start its API server.

---

## sequence-par-opt.ggarch — par and opt blocks

**What it shows:** `par` blocks (green-tinted parallel lanes), `opt` blocks
(optional fragment), and activation bars on call/return pairs.

**Views (1):** `sequence-par-opt` — the integrate operation: controller fans
out to two unit agents in parallel, then conditionally notifies one of a data
change.

---

## er-diagram.ggarch — entity-relationship diagram

**What it shows:** `record` nodes with named fields; PK/FK/nullable markers;
right-aligned field types; field-qualified edge endpoints that anchor at the
exact field row rather than the node centroid.

**Views (1):** `er-diagram` — the five core Juju model-database tables
(application, unit, machine, charm, relation) with their FK relationships.

---

## class-diagram.ggarch — class diagram

**What it shows:** `class` nodes with visibility markers (`+` public, `-`
private, `#` protected); method signatures with return types; typed edges
expressing `implements` and `extends` relationships.

**Views (1):** `class-diagram` — four Juju agent worker types in a class
hierarchy: `Worker` interface → `baseWorker` → `unitWorker`, plus
`charmRunner` as a dependency.

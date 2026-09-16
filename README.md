# ggarch

**Architecture diagrams as code, expressive and on-brand.**

[![License: Apache-2.0](https://img.shields.io/badge/License-Apache--2.0-blue.svg)](LICENSE)
[![Version: 0.20.8](https://img.shields.io/badge/version-0.20.8-orange.svg)](SPEC.md)

> **The problem:** Diagrams-as-code tools are maintainable but limited --
> layout overrides your spatial intent, edges carry no semantic meaning,
> every diagram is a separate file that drifts from the rest, and branding
> is an afterthought. Tools with genuine expressive power (Excalidraw,
> hand-tuned SVG) require manual drawing: slow, error-prone, and resistant
> to AI assistance.
>
> **The fix:** A grammar that hits all three. Looks right: Juju/Canonical
> branding out of the box (Ubuntu font, Juju orange, light and dark themes),
> with a style grammar designed for customisation. Says what you mean:
> constraint layout, typed edges, lifecycle, one model shared by every view.
> Stays current: plain text, AI-writable, rename a node once and it
> propagates everywhere.

See [COMPARISON.md](COMPARISON.md) for a detailed comparison with Mermaid,
D2, Graphviz, PlantUML, Structurizr, and Ilograph.

## What you get

1. **Branding** -- ships with Juju/Canonical branding: Ubuntu font, Juju
   orange, light and dark themes. A coherent visual grammar where colour
   encodes ownership and dash pattern encodes edge semantics. The `style`
   block lets any project override colours and shapes without touching
   ggarch itself; a clean API for registering named presets and swapping
   fonts is on the roadmap.
2. **Expressive power** -- nodes with types, lifecycle (`init`, `persistent`,
   `ephemeral`), cardinality, and scope; typed edges (`api`, `stream`,
   `event`, `control`, `ipc`, `data`); constraint-based layout (`left-of`,
   `above`, `fan`, `gap:`) solved by Cassowary; topology, sequence, ER,
   class, and state machine views; annotations that cut across the
   containment hierarchy, layout-transparent.
3. **Maintainability** -- declare your system once in a model; derive every
   diagram from it. Rename a node once; it updates in every view. Plain text:
   diffs cleanly, reviews in a PR, and an AI coding assistant can write and
   revise it fluently.

A **Sphinx extension** ships with the package: drop `{ggarch}` directives
into your docs and diagrams rebuild on source changes, with light and dark
themes and an optional expand modal.

## Sneak peek

<div align="center">
  <img src=".github/ggarch-demo.gif?v=3"
       alt="Three-slide walkthrough: juju.ggarch source file, the Markdown file with ggarch directives, and the rendered Sphinx page with diagram, expand button, and caption."
       width="100%">
</div>

*From `juju.ggarch` to a Markdown file with `{ggarch}` directives to a live
Sphinx page -- with the diagram, expand button, and caption all rendered.
Source: [`docs/juju.ggarch`](https://github.com/tmihoc/juju/blob/4.0-docs-rewrite-juju-architecture-juju-9632/docs/juju.ggarch).*

## Get started

ggarch is installed from source:

```bash
git clone https://github.com/tmihoc/ggarch
cd ggarch
pip install -e .
```

For Sphinx integration add the optional dependency:

```bash
pip install -e ".[sphinx]"
```

**Write a diagram.** Create `my-system.ggarch`:

```
model "My system" {
  nodes {
    api     [type: juju-software, label: "API server"]
    db      [type: database,      label: "Database"]
    client  [type: person,        label: "User"]
  }
  edges {
    client -> api [type: api,  label: "HTTP"]
    api    -> db  [type: data, label: "SQL"]
  }
  style { extends: juju }
}

diagram "Overview" from "My system" {
  select { nodes: client api db }
  positions {
    client left-of api gap: 60
    client align-middle api
    api    left-of db  gap: 60
    api    align-middle db
  }
}
```

**Check and render:**

```bash
ggarch check my-system.ggarch
ggarch render my-system.ggarch "Overview" --out overview.svg
```

**Use in Sphinx** (`conf.py`):

```python
extensions = ["ggarch.sphinxcontrib_ggarch"]
```

Then in any `.md` or `.rst` file:

```
{ggarch}
:file: my-system.ggarch
:view: Overview
:caption: The system at a glance.
```

For the full grammar, all node types, edge types, annotation kinds, sequence
syntax, and deployment environment resolution, see [SPEC.md](SPEC.md).

For step-by-step instructions on writing and editing diagrams -- including
how to work with an AI coding assistant -- see [SKILL.md](SKILL.md).

## Versioning

The minor version tracks the grammar. A MINOR bump may change the `.ggarch`
syntax or rendered output in a way that requires updating existing diagram
files. PATCH means fixes and renderer tweaks with no source changes required.
`1.0` is reserved for once the grammar is stable enough to freeze.

## License

Copyright (C) 2026 Teodora Mihoc.

Licensed under [Apache-2.0](LICENSE). Generated SVG output is not a derived
work of the tool and carries no licence obligations.

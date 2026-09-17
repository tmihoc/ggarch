"""Instance materialization.

A view's `instances:` stamps a type node's whole subtree: the instance
box carries the archetype's children (ids prefixed "<instance>/<child>"),
so an instance of a container renders with everything inside it.

Model edges are expanded per instance:

- both endpoints outside instanced subtrees: unchanged;
- both endpoints inside instanced subtrees: copied per instance, zipped
  (instance i wired to instance i -- the in-instance wiring);
- one endpoint inside: fanned to every instance.

The solver (layout) and the router (edges) both call
``materialize_instances``, so they see the same stamped nodes and
expanded edges for a given view.
"""
from __future__ import annotations

import dataclasses

from ggarch.model import Edge, Model, Node, SelectClause


# ---------------------------------------------------------------------------
# Subtree stamping
# ---------------------------------------------------------------------------

def _stamp_subtree(node: Node, root_id: str, label: str = "") -> Node:
    """Deep-copy a node subtree under a new root id, with an optional
    label override (the instance label replaces the type label)."""
    children = [_stamp_child(c, root_id) for c in node.children]
    return dataclasses.replace(node, id=root_id, label=label or node.label,
                               children=children)

def _stamp_child(child: Node, prefix: str) -> Node:
    """Stamp one child as ``<prefix>/<child>``; descendants carry the path."""
    new_id = f"{prefix}/{child.id}"
    children = [_stamp_child(c, new_id) for c in child.children]
    return dataclasses.replace(child, id=new_id, children=children)


def _descendant_paths(node: Node, path: str = "") -> list[tuple[str, str]]:
    """Return [(descendant_id, relative_path)] for the whole subtree.

    The path is the chain of ancestor ids below the type node, matching
    the stamped ids ("<instance>/<path>").
    """
    pairs: list[tuple[str, str]] = []
    for child in node.children:
        child_path = f"{path}/{child.id}" if path else child.id
        pairs.append((child.id, child_path))
        pairs.extend(_descendant_paths(child, child_path))
    return pairs


def _replace_in_tree(nodes: list[Node], stamps: dict[str, list[Node]]) -> list[Node]:
    """Replace every stamped type node, wherever it sits in the tree."""
    out: list[Node] = []
    for n in nodes:
        if n.id in stamps:
            out.extend(stamps[n.id])
            continue
        if n.children:
            children = _replace_in_tree(n.children, stamps)
            if children != n.children:
                n = dataclasses.replace(n, children=children)
        out.append(n)
    return out


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def materialize_instances(
    select: SelectClause,
    model: Model,
) -> tuple[list[Node], list[Edge]]:
    """Return (nodes, edges) with instanced types stamped out."""
    if not select.instances:
        return list(model.nodes), list(model.edges)

    stamps: dict[str, list[Node]] = {}
    remap: dict[str, list[str]] = {}
    for spec in select.instances:
        type_node = model.find_node(spec.type_id)
        if type_node is None:
            continue
        stamps.setdefault(spec.type_id, []).append(
            _stamp_subtree(type_node, spec.instance_id, spec.label))
        # The type node's own id remaps to the instance roots; its
        # descendants remap to "<instance>/<child path>".
        remap.setdefault(spec.type_id, []).append(spec.instance_id)
        for d, path in _descendant_paths(type_node):
            remap.setdefault(d, []).append(f"{spec.instance_id}/{path}")

    nodes = _replace_in_tree(list(model.nodes), stamps)

    edges: list[Edge] = []
    for edge in model.edges:
        srcs = remap.get(edge.source, [edge.source])
        tgts = remap.get(edge.target, [edge.target])
        pairing = edge.properties.get("pairing", "")
        if edge.source in remap and edge.target in remap:
            if pairing == "mesh":
                # Between copies: every distinct-instance pair, never a
                # copy with itself (full mesh -- e.g. Raft peers).
                for s in srcs:
                    for t in tgts:
                        if s.split("/", 1)[0] == t.split("/", 1)[0]:
                            continue
                        edges.append(dataclasses.replace(edge, source=s, target=t))
            else:
                # Both endpoints inside instanced subtrees: per-instance
                # copies, zipped (instance i to instance i).
                for s, t in zip(srcs, tgts):
                    edges.append(dataclasses.replace(edge, source=s, target=t))
        else:
            # One endpoint inside: fan to every instance.
            for s in srcs:
                for t in tgts:
                    edges.append(dataclasses.replace(edge, source=s, target=t))
    return nodes, edges

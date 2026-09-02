"""ggarch constraint solver.

Translates a DiagramView's positions block into kiwisolver (Cassowary)
constraints and solves for the (x, y, width, height) of every node.

Design:
- Every node gets four kiwisolver variables: x, y, w, h.
- Minimum size constraints are added for all nodes (from label text).
- Container nodes get additional constraints: their bounds must contain
  all children with padding.
- User-declared constraints (left-of, above, align-*, etc.) are added
  on top.
- The solver is run once; results are read back into SolvedNode/SolvedLayout.

Constraint strictness:
- Min-size constraints: STRONG (solver may exceed them but not go below).
- Containment constraints: REQUIRED (a container must contain its children).
- User-declared constraints: REQUIRED. If the user's constraints conflict,
  kiwisolver raises UnsatisfiableConstraint — we surface that as a
  ValidationError, never silently relax.
"""
from __future__ import annotations

from kiwisolver import Solver, Variable, UnsatisfiableConstraint  # type: ignore

from ggarch.errors import ValidationError
from ggarch.layout import (
    CONTAINER_PAD,
    CONTAINER_PAD_TOP,
    MIN_NODE_HEIGHT,
    MIN_NODE_WIDTH,
    Rect,
    SolvedLayout,
    SolvedNode,
    field_node_min_size,
    min_size,
)
from ggarch.model import (
    Constraint,
    DiagramView,
    GgarchFile,
    Lifecycle,
    Model,
    Node,
    SelectClause,
)


# ---------------------------------------------------------------------------
# Per-node variable bundle
# ---------------------------------------------------------------------------

class _NodeVars:
    """The four kiwisolver variables for one node."""

    def __init__(self, node_id: str) -> None:
        self.x = Variable(f"{node_id}.x")
        self.y = Variable(f"{node_id}.y")
        self.w = Variable(f"{node_id}.w")
        self.h = Variable(f"{node_id}.h")

    @property
    def x2(self):
        return self.x + self.w

    @property
    def y2(self):
        return self.y + self.h

    @property
    def cx(self):
        return self.x + self.w / 2

    @property
    def cy(self):
        return self.y + self.h / 2


# ---------------------------------------------------------------------------
# Main solver entry point
# ---------------------------------------------------------------------------

def solve(diagram: DiagramView, model: Model) -> SolvedLayout:
    """Solve layout for diagram view and return a SolvedLayout.

    Raises ValidationError if user constraints are unsatisfiable.
    """
    # Determine which nodes are included in this view.
    selected = _selected_nodes(diagram.select, model)

    # Build variable bundles for every node (including nested children).
    vars_by_id: dict[str, _NodeVars] = {}
    for node in selected:
        _register_vars(node, vars_by_id)

    # Alias abstract ids → concrete vars for environment + node-level abstracts.
    # This allows constraints like `controller left-of unit_agent` to work even
    # when `controller` is resolved to `controller_k8s` in the current env.
    abs_map = (model.environment_abstractions_map(diagram.select.environment)
               if diagram.select.environment else model.abstractions_map())
    for abstract_id, concrete_id in abs_map.items():
        if concrete_id in vars_by_id and abstract_id not in vars_by_id:
            vars_by_id[abstract_id] = vars_by_id[concrete_id]

    # Also register instance ids (view-local expansions of a type node).
    instance_map: dict[str, str] = {}
    for spec in diagram.select.instances:
        instance_map[spec.instance_id] = spec.type_id
        if spec.instance_id not in vars_by_id:
            vars_by_id[spec.instance_id] = _NodeVars(spec.instance_id)

    solver = Solver()

    # Add minimum-size and non-negativity constraints.
    _add_min_size_constraints(solver, selected, vars_by_id, diagram.select)

    # Add min-size for instance vars (same size as their type node).
    for spec in diagram.select.instances:
        type_node = model.find_node(spec.type_id)
        if type_node and spec.instance_id in vars_by_id:
            iv = vars_by_id[spec.instance_id]
            solver.addConstraint((iv.x >= 0) | "required")
            solver.addConstraint((iv.y >= 0) | "required")
            solver.addConstraint((iv.w >= MIN_NODE_WIDTH)  | "required")
            solver.addConstraint((iv.h >= MIN_NODE_HEIGHT) | "required")
            mw, mh = min_size(spec.label or type_node.label, bool(type_node.children))
            solver.addConstraint((iv.w >= mw) | "strong")
            solver.addConstraint((iv.h >= mh) | "strong")

    # Add containment constraints (parent must contain all children).
    _add_containment_constraints(solver, selected, vars_by_id, diagram.select)

    # Anchor the layout: the top-left node starts at (0, 0) by default.
    # Without this the system is under-constrained (translatable).
    _add_origin_anchor(solver, selected, vars_by_id)

    # Auto-layout container children using direction constraints.
    # This runs before user constraints so user constraints can override.
    direction_map = _collect_directions(diagram.constraints)
    _add_auto_layout_pass(solver, selected, vars_by_id, diagram.select, direction_map)

    # Add user-declared constraints.
    _add_user_constraints(solver, diagram.constraints, vars_by_id, diagram.name)

    # Solve.
    try:
        solver.updateVariables()
    except UnsatisfiableConstraint as exc:
        raise ValidationError(
            f"diagram {diagram.name!r}: unsatisfiable layout constraints — {exc}",
            hint="check for contradictory position constraints",
        ) from exc

    # Read results back.
    return _build_layout(selected, vars_by_id, model, diagram.select)


# ---------------------------------------------------------------------------
# Node selection
# ---------------------------------------------------------------------------

def _selected_nodes(select: SelectClause, model: Model) -> list[Node]:
    """Return the top-level model nodes included in this view.

    If select.environment is set, abstract node ids in select.node_ids are
    resolved to their environment-specific concrete ids.
    """
    abs_map = (model.environment_abstractions_map(select.environment)
               if select.environment else model.abstractions_map())

    if not select.node_ids:
        return list(model.nodes)

    result = []
    for nid in select.node_ids:
        concrete_id = abs_map.get(nid, nid)
        node = model.find_node(concrete_id)
        if node is not None:
            result.append(node)
    return result


def _register_vars(node: Node, vars_by_id: dict[str, _NodeVars]) -> None:
    vars_by_id[node.id] = _NodeVars(node.id)
    for child in node.children:
        _register_vars(child, vars_by_id)


# ---------------------------------------------------------------------------
# Minimum size constraints
# ---------------------------------------------------------------------------

def _add_min_size_constraints(
    solver: Solver,
    nodes: list[Node],
    vars_by_id: dict[str, _NodeVars],
    select: SelectClause,
) -> None:
    for node in nodes:
        _add_min_size_for_node(solver, node, vars_by_id, select)


def _add_min_size_for_node(
    solver: Solver,
    node: Node,
    vars_by_id: dict[str, _NodeVars],
    select: SelectClause,
) -> None:
    v = vars_by_id[node.id]
    is_container = bool(node.children)
    collapsed = node.id in select.collapse

    # Person nodes: pin to exact figure width early, before any REQUIRED mins
    # that would conflict.
    if node.type == "person":
        from ggarch.renderer import _PERSON_SIZE
        fig_w = round(_PERSON_SIZE * 0.78 * 0.7) + 16
        fig_h = _PERSON_SIZE
        solver.addConstraint((v.x >= 0)       | "required")
        solver.addConstraint((v.y >= 0)       | "required")
        solver.addConstraint((v.w == fig_w)   | "required")
        solver.addConstraint((v.h == fig_h)   | "required")
        return  # skip generic min-size — person has exact dimensions

    # Non-negativity — REQUIRED.
    solver.addConstraint((v.x >= 0) | "required")
    solver.addConstraint((v.y >= 0) | "required")
    solver.addConstraint((v.w >= MIN_NODE_WIDTH) | "required")
    solver.addConstraint((v.h >= MIN_NODE_HEIGHT) | "required")

    if node.fields:
        min_w, min_h = field_node_min_size(node.label, len(node.fields))
    else:
        min_w, min_h = min_size(node.label, is_container and not collapsed)
    solver.addConstraint((v.w >= min_w) | "strong")
    solver.addConstraint((v.h >= min_h) | "strong")

    if not collapsed:
        for child in node.children:
            _add_min_size_for_node(solver, child, vars_by_id, select)


# ---------------------------------------------------------------------------
# Containment constraints
# ---------------------------------------------------------------------------

def _add_containment_constraints(
    solver: Solver,
    nodes: list[Node],
    vars_by_id: dict[str, _NodeVars],
    select: SelectClause,
) -> None:
    for node in nodes:
        if node.children and node.id not in select.collapse:
            _add_containment_for_node(solver, node, vars_by_id, select)


def _add_containment_for_node(
    solver: Solver,
    node: Node,
    vars_by_id: dict[str, _NodeVars],
    select: SelectClause,
) -> None:
    parent = vars_by_id[node.id]
    for child in node.children:
        cv = vars_by_id[child.id]
        # Child must sit inside parent with padding — REQUIRED.
        solver.addConstraint(
            (cv.x >= parent.x + CONTAINER_PAD) | "required"
        )
        solver.addConstraint(
            (cv.y >= parent.y + CONTAINER_PAD_TOP) | "required"
        )
        solver.addConstraint(
            (cv.x2 <= parent.x2 - CONTAINER_PAD) | "required"
        )
        solver.addConstraint(
            (cv.y2 <= parent.y2 - CONTAINER_PAD) | "required"
        )
        # Recurse.
        if child.children and child.id not in select.collapse:
            _add_containment_for_node(solver, child, vars_by_id, select)


# ---------------------------------------------------------------------------
# Origin anchor
# ---------------------------------------------------------------------------

def _add_origin_anchor(
    solver: Solver,
    nodes: list[Node],
    vars_by_id: dict[str, _NodeVars],
) -> None:
    """Anchor the first top-level node at (0, 0) with WEAK priority.

    This prevents the layout from floating to arbitrary coordinates while
    still allowing user constraints to override the position.
    """
    if not nodes:
        return
    first = vars_by_id[nodes[0].id]
    solver.addConstraint((first.x == 0) | "weak")
    solver.addConstraint((first.y == 0) | "weak")


# ---------------------------------------------------------------------------
# Auto-layout pass — sequential child placement
# ---------------------------------------------------------------------------

def _collect_directions(constraints: list[Constraint]) -> dict[str, str]:
    """Return a map of node_id -> direction from direction constraints."""
    d: dict[str, str] = {}
    for c in constraints:
        if c.kind == "direction" and c.value:
            d[c.subject] = c.value
    return d


def _add_auto_layout_pass(
    solver: Solver,
    nodes: list[Node],
    vars_by_id: dict[str, _NodeVars],
    select: SelectClause,
    direction_map: dict[str, str],
) -> None:
    """Add MEDIUM-priority sequential placement for container children.

    Uses the direction declared in the positions block (default: right).
    MEDIUM priority means user REQUIRED constraints override these.
    """
    for node in nodes:
        if node.children and node.id not in select.collapse:
            direction = direction_map.get(node.id, "right")
            _auto_layout_children(solver, node, vars_by_id, direction)
            # Recurse into children that are themselves containers.
            _add_auto_layout_pass(
                solver, node.children, vars_by_id, select, direction_map
            )


# ---------------------------------------------------------------------------
# User-declared constraints
# ---------------------------------------------------------------------------

_GAP_DEFAULT = 20  # px — default gap when not specified


def _add_user_constraints(
    solver: Solver,
    constraints: list[Constraint],
    vars_by_id: dict[str, _NodeVars],
    view_name: str,
) -> None:
    for c in constraints:
        try:
            _add_one_constraint(solver, c, vars_by_id)
        except UnsatisfiableConstraint as exc:
            raise ValidationError(
                f"diagram {view_name!r}: constraint {c.kind!r} on "
                f"{c.subject!r} is unsatisfiable — {exc}",
                hint="check for contradictory position constraints",
            ) from exc
        except KeyError as exc:
            raise ValidationError(
                f"diagram {view_name!r}: constraint references unknown node {exc}",
            ) from exc


def _add_one_constraint(
    solver: Solver,
    c: Constraint,
    vars_by_id: dict[str, _NodeVars],
) -> None:
    s = vars_by_id[c.subject]
    gap = c.gap if c.gap else _GAP_DEFAULT

    kind = c.kind

    if kind == "left-of":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x2 + gap <= o.x) | "required")

    elif kind == "right-of":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x >= o.x2 + gap) | "required")

    elif kind == "above":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y2 + gap <= o.y) | "required")

    elif kind == "below":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y >= o.y2 + gap) | "required")

    elif kind == "align-left":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x == o.x) | "required")

    elif kind == "align-right":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x2 == o.x2) | "required")

    elif kind == "align-top":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y == o.y) | "required")

    elif kind == "align-bottom":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y2 == o.y2) | "required")

    elif kind == "align-middle":
        # Vertical centres aligned.
        o = vars_by_id[c.object]
        solver.addConstraint((s.cy == o.cy) | "required")

    elif kind == "align-centre":
        # Horizontal centres aligned.
        o = vars_by_id[c.object]
        solver.addConstraint((s.cx == o.cx) | "required")

    elif kind == "same-width":
        o = vars_by_id[c.object]
        solver.addConstraint((s.w == o.w) | "required")

    elif kind == "same-height":
        o = vars_by_id[c.object]
        solver.addConstraint((s.h == o.h) | "required")

    elif kind == "same-size":
        o = vars_by_id[c.object]
        solver.addConstraint((s.w == o.w) | "required")
        solver.addConstraint((s.h == o.h) | "required")

    elif kind == "min-width":
        # gap field holds the value for min-width/height.
        solver.addConstraint((s.w >= c.gap) | "required")

    elif kind == "min-height":
        solver.addConstraint((s.h >= c.gap) | "required")

    elif kind in ("direction", "grid"):
        # Direction and grid affect child layout — handled by the
        # auto-layout pass (Phase 2b), not direct constraints.
        # For now, direction/grid constraints are accepted but ignored
        # so the grammar round-trips cleanly.
        pass

    else:
        # Unknown constraint kind — warn but don't fail.
        import warnings
        warnings.warn(f"ggarch: unknown constraint kind {kind!r} — ignored")


# ---------------------------------------------------------------------------
# Auto-layout for children without explicit constraints
# ---------------------------------------------------------------------------

def _auto_layout_children(
    solver: Solver,
    node: Node,
    vars_by_id: dict[str, _NodeVars],
    direction: str = "right",
) -> None:
    """Add sequential placement constraints for children that have no
    explicit mutual constraints.

    direction: 'right' places children left-to-right;
               'down' places them top-to-bottom.
    """
    children = node.children
    if len(children) < 2:
        return
    gap = _GAP_DEFAULT
    for i in range(1, len(children)):
        prev = vars_by_id[children[i - 1].id]
        curr = vars_by_id[children[i].id]
        if direction == "right":
            solver.addConstraint((curr.x >= prev.x2 + gap) | "medium")
            solver.addConstraint((curr.y == prev.y) | "medium")
        else:  # down
            solver.addConstraint((curr.y >= prev.y2 + gap) | "medium")
            solver.addConstraint((curr.x == prev.x) | "medium")


# ---------------------------------------------------------------------------
# Read results back into SolvedLayout
# ---------------------------------------------------------------------------

def _build_layout(
    nodes: list[Node],
    vars_by_id: dict[str, _NodeVars],
    model: Model,
    select: SelectClause,
) -> SolvedLayout:
    # Exclude type nodes that have active instances — the instances replace them.
    instanced_type_ids = {spec.type_id for spec in select.instances}
    solved_nodes = [
        _build_solved_node(node, vars_by_id, model, select)
        for node in nodes
        if node.id not in instanced_type_ids
    ]

    # Build SolvedNode entries for view-local instances.
    for spec in select.instances:
        if spec.instance_id in vars_by_id:
            type_node = model.find_node(spec.type_id)
            iv = vars_by_id[spec.instance_id]
            rect = Rect(iv.x.value(), iv.y.value(), iv.w.value(), iv.h.value())
            solved_nodes.append(SolvedNode(
                id=spec.instance_id,
                rect=rect,
                label=spec.label or (type_node.label if type_node else spec.instance_id),
                type=type_node.type if type_node else "default",
                lifecycle=type_node.lifecycle.value if type_node else "persistent",
                cardinality="",
                fields=[],
            ))

    # Compute overall bounding box.
    if solved_nodes:
        min_x = min(n.rect.x for n in solved_nodes)
        min_y = min(n.rect.y for n in solved_nodes)
        max_x = max(n.rect.x2 for n in solved_nodes)
        max_y = max(n.rect.y2 for n in solved_nodes)
        bounds = Rect(min_x, min_y, max_x - min_x, max_y - min_y)
    else:
        bounds = Rect(0, 0, 0, 0)

    return SolvedLayout(nodes=solved_nodes, bounds=bounds)


def _build_solved_node(
    node: Node,
    vars_by_id: dict[str, _NodeVars],
    model: Model,
    select: SelectClause,
) -> SolvedNode:
    v = vars_by_id[node.id]
    rect = Rect(
        x=v.x.value(),
        y=v.y.value(),
        w=v.w.value(),
        h=v.h.value(),
    )
    collapsed = node.id in select.collapse
    children = []
    if node.children and not collapsed:
        children = [
            _build_solved_node(child, vars_by_id, model, select)
            for child in node.children
        ]
    return SolvedNode(
        id=node.id,
        rect=rect,
        children=children,
        label=node.label,
        type=node.type,
        lifecycle=node.lifecycle.value,
        cardinality=node.cardinality.value
            if hasattr(node.cardinality, "value") else
            str(node.cardinality) if node.cardinality else "",
        fields=node.fields,
        url=node.url,
    )

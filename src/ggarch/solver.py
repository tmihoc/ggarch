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
from ggarch.instances import materialize_instances
from ggarch.model import (
    Constraint,
    FanConstraint,
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
    # Materialize instances (stamped subtrees) before selection; the
    # router performs the same expansion via ggarch.instances.
    mat_nodes, mat_edges = materialize_instances(diagram.select, model)
    selected = _selected_nodes(diagram.select, model, mat_nodes)

    # Build variable bundles for every node (including nested children).
    vars_by_id: dict[str, _NodeVars] = {}
    for node in selected:
        _register_vars(node, vars_by_id)

    # Alias abstract ids → concrete vars for environment + node-level abstracts.
    # This allows constraints like `controller left-of unit_agent` to work even
    # when `controller` is resolved to `controller_k8s` in the current env.
    abs_map = (model.environment_abstractions_map(diagram.select.environment)
               if diagram.select.environment else {})
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
            solver.addConstraint((iv.w >= mw) | "required")
            solver.addConstraint((iv.h >= mh) | "required")

    # Add containment constraints (parent must contain all children).
    _add_containment_constraints(solver, selected, vars_by_id, diagram.select)

    # Anchor the layout: the top-left node starts at (0, 0) by default.
    # Without this the system is under-constrained (translatable).
    _add_origin_anchor(solver, selected, vars_by_id)

    # Expand fan constraints into ordinary constraints before layout passes.
    # Pass solver and vars_by_id so even-N fans can emit centroid constraints directly.
    expanded_constraints = _expand_fan_constraints(diagram.constraints, solver, vars_by_id)

    # Auto-layout container children using direction constraints.
    # This runs before user constraints so user constraints can override.
    direction_map = _collect_directions(expanded_constraints)
    _add_auto_layout_pass(solver, selected, vars_by_id, diagram.select, direction_map, model)
    # Add user-declared constraints, with label-aware gap expansion.
    _add_user_constraints(solver, expanded_constraints, vars_by_id, diagram.name, model)
    # Ensure sufficient separation for every labelled edge (covers auto-layout children).
    if model is not None:
        _add_label_gap_constraints(
            solver, mat_nodes, mat_edges, vars_by_id, expanded_constraints)

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

def _selected_nodes(
    select: SelectClause, model: Model, mat_nodes: list[Node],
) -> list[Node]:
    """Return the top-level nodes included in this view, from the
    materialized tree.

    If select.environment is set, abstract node ids in select.node_ids
    are resolved to their environment-specific concrete ids. Instanced
    type ids resolve to their stamped instance roots.
    """
    abs_map = (model.environment_abstractions_map(select.environment)
               if select.environment else {})
    inst_by_type: dict[str, list[str]] = {}
    for spec in select.instances:
        inst_by_type.setdefault(spec.type_id, []).append(spec.instance_id)

    if not select.node_ids:
        return list(mat_nodes)

    result = []
    for nid in select.node_ids:
        concrete_id = abs_map.get(nid, nid)
        if concrete_id in inst_by_type:
            for iid in inst_by_type[concrete_id]:
                node = _find_in_tree(mat_nodes, iid)
                if node is not None:
                    result.append(node)
            continue
        node = _find_in_tree(mat_nodes, concrete_id)
        if node is not None:
            result.append(node)
    return result


def _find_in_tree(nodes: list[Node], node_id: str) -> Node | None:
    for n in nodes:
        if n.id == node_id:
            return n
        if n.children:
            found = _find_in_tree(n.children, node_id)
            if found:
                return found
    return None


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

    # Non-negativity — REQUIRED.
    solver.addConstraint((v.x >= 0) | "required")
    solver.addConstraint((v.y >= 0) | "required")
    solver.addConstraint((v.w >= MIN_NODE_WIDTH) | "required")
    solver.addConstraint((v.h >= MIN_NODE_HEIGHT) | "required")

    if node.fields:
        min_w, min_h = field_node_min_size(node.label, len(node.fields))
    else:
        min_w, min_h = min_size(node.label, is_container and not collapsed)
    solver.addConstraint((v.w >= min_w) | "required")
    solver.addConstraint((v.h >= min_h) | "required")
    # For leaf nodes, also pin height at min_h at STRONG priority so align-middle
    # doesn't cause unbounded height growth.
    if not is_container and not collapsed:
        solver.addConstraint((v.h == min_h) | "strong")
        # Same for width: without it, the origin anchor's weak x==0 can
        # conflict with a required align-centre and the free width variable
        # silently absorbs the error (nodes balloon to 2x their centre).
        solver.addConstraint((v.w == min_w) | "strong")

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
    model: "Model | None" = None,
) -> None:
    """Add MEDIUM-priority sequential placement for container children.

    Uses the direction declared in the positions block (default: right).
    MEDIUM priority means user REQUIRED constraints override these.
    """
    for node in nodes:
        if node.children and node.id not in select.collapse:
            direction = direction_map.get(node.id, "right")
            _auto_layout_children(solver, node, vars_by_id, direction, model)
            _add_auto_layout_pass(
                solver, node.children, vars_by_id, select, direction_map, model
            )


# ---------------------------------------------------------------------------
# Fan constraint expansion
# ---------------------------------------------------------------------------

def _expand_fan_constraints(
    constraints: list[Constraint | FanConstraint],
    solver: Solver | None = None,
    vars_by_id: dict | None = None,
) -> list[Constraint]:
    """Expand FanConstraints into ordinary Constraints.

    For each fan, emits:
    - One cardinal constraint per member (correct plane relative to anchor).
    - Sequential spacing constraints chaining members along the fan axis.
    - Centering: for odd N, pins the middle member's perpendicular axis to
      the anchor's. For even N, directly constrains
      (left_cx + right_cx) == 2 * anchor_cx (requires solver + vars_by_id).
    - Perpendicular alignment between all members (clean row or column).

    Fan axis conventions:
      above / below      → horizontal row, centred on anchor cx.
      left-of / right-of → vertical column, centred on anchor cy.
    """
    result: list[Constraint] = []
    for c in constraints:
        if not isinstance(c, FanConstraint):
            result.append(c)
            continue

        members = c.members
        anchor  = c.anchor
        n       = len(members)
        gap     = c.gap
        spacing = c.spacing
        horiz   = c.direction in ("above", "below")

        # -- 1. Place each member in the correct plane relative to anchor --
        for m in members:
            result.append(Constraint(kind=c.direction, subject=m, object=anchor, gap=gap))

        if horiz:
            # -- 2. Chain left-to-right with spacing --
            for i in range(n - 1):
                result.append(Constraint(kind="left-of", subject=members[i],
                                         object=members[i + 1], gap=spacing))
            # -- 3. All members on the same horizontal row --
            for m in members:
                result.append(Constraint(kind="align-middle", subject=m, object=members[0]))
            # -- 4. Centre group on anchor cx --
            if n % 2 == 1:
                # Odd N: pin middle member cx to anchor cx.
                result.append(Constraint(kind="align-centre",
                                         subject=members[n // 2], object=anchor))
            elif solver is not None and vars_by_id is not None:
                # Even N: (left_of_centre.cx + right_of_centre.cx) == 2 * anchor.cx
                left  = vars_by_id[members[n // 2 - 1]]
                right = vars_by_id[members[n // 2]]
                anch  = vars_by_id[anchor]
                solver.addConstraint(
                    (left.cx + right.cx == 2 * anch.cx) | "required"
                )
        else:
            # -- 2. Chain top-to-bottom with spacing --
            for i in range(n - 1):
                result.append(Constraint(kind="above", subject=members[i],
                                         object=members[i + 1], gap=spacing))
            # -- 3. All members on the same vertical column --
            for m in members:
                result.append(Constraint(kind="align-centre", subject=m, object=members[0]))
            # -- 4. Centre group on anchor cy --
            if n % 2 == 1:
                result.append(Constraint(kind="align-middle",
                                         subject=members[n // 2], object=anchor))
            elif solver is not None and vars_by_id is not None:
                top    = vars_by_id[members[n // 2 - 1]]
                bottom = vars_by_id[members[n // 2]]
                anch   = vars_by_id[anchor]
                solver.addConstraint(
                    (top.cy + bottom.cy == 2 * anch.cy) | "required"
                )

    return result


# ---------------------------------------------------------------------------
# User-declared constraints
# ---------------------------------------------------------------------------

# These constants mirror the renderer so the solver knows how much space
# a label needs. Keep in sync with renderer.py.
_LABEL_CHAR_W   = 5.5
_LABEL_LINE_H   = 9 * 1.5   # font_size * 1.5
_LABEL_PADDING  = 0          # px each side of gap — keep in sync with renderer.py
_LABEL_MIN_TAIL = 16         # px of visible arrow on each side of gap


def _label_min_gap_h(label: str) -> float:
    """Minimum gap for a horizontal arrow: label width + padding + tails."""
    lines = label.split("\\n")
    max_line_w = max(len(l) for l in lines) * _LABEL_CHAR_W
    return max_line_w + _LABEL_PADDING * 2 + _LABEL_MIN_TAIL * 2


def _label_min_gap_v(label: str) -> float:
    """Minimum gap for a vertical arrow: wrapped label height + padding + tails.

    For vertical arrows the label is rendered horizontally above the arrow;
    the gap size is the wrapped text height.  We estimate wrapping using a
    conservative path width of 60px (typical inter-node vertical gap).
    """
    TYPICAL_PATH_PX = 60
    lines_raw = label.split("\\n")
    max_chars = max(int(TYPICAL_PATH_PX / _LABEL_CHAR_W), 1)
    wrapped_lines = 0
    for raw in lines_raw:
        words = raw.split()
        if not words:
            wrapped_lines += 1
            continue
        cur = words[0]
        for w in words[1:]:
            if len(cur) + 1 + len(w) <= max_chars:
                cur += " " + w
            else:
                wrapped_lines += 1
                cur = w
        wrapped_lines += 1
    text_h = _LABEL_LINE_H * wrapped_lines
    return text_h + _LABEL_PADDING * 2 + _LABEL_MIN_TAIL * 2


_GAP_DEFAULT = 20  # px — default gap when not specified

def _add_label_gap_constraints(
    solver: Solver,
    nodes: list[Node],
    edges: list,
    vars_by_id: dict[str, _NodeVars],
    constraints: list,
) -> None:
    """Emit STRONG-priority minimum-separation for every labelled edge.

    Operates on top-level ancestors so container nodes get pushed.
    Only emits horizontal constraints for horizontally-related pairs and
    vertical constraints for vertically-related pairs, to avoid displacing
    nodes that are related on the perpendicular axis.
    """
    # Build parent map.
    parent: dict[str, str] = {}
    def _walk(node: "Node", pid: str | None) -> None:
        if pid is not None:
            parent[node.id] = pid
        for child in node.children:
            _walk(child, node.id)
    for node in nodes:
        _walk(node, None)

    def _solver_ancestors(nid: str) -> list[str]:
        """Return [nid, parent, grandparent, ...] stopping at nodes not in vars_by_id."""
        chain = []
        while nid in vars_by_id:
            chain.append(nid)
            nid = parent.get(nid, "")
        return chain

    def _effective_id(src: str, tgt: str) -> tuple[str, str]:
        """Return the lowest solver-tracked ancestor of each node that is
        distinct from the other's ancestry — i.e. the nodes that the solver
        will actually push apart when we add a gap constraint.
        Walks up from the node rather than straight to the top, so two nodes
        inside sibling containers resolve to those containers, not the shared
        grandparent container.
        """
        src_chain = _solver_ancestors(src)
        tgt_chain = _solver_ancestors(tgt)
        tgt_set   = set(tgt_chain)
        src_set   = set(src_chain)
        # Deepest src ancestor not in tgt's ancestry
        eff_src = next((n for n in src_chain if n not in tgt_set), src_chain[-1] if src_chain else src)
        # Deepest tgt ancestor not in src's ancestry
        eff_tgt = next((n for n in tgt_chain if n not in src_set), tgt_chain[-1] if tgt_chain else tgt)
        return eff_src, eff_tgt

    # Build axis relationship sets from expanded constraints.
    right_of: set[tuple[str,str]] = set()  # (right_node, left_node)
    above_of:  set[tuple[str,str]] = set()  # (above_node, below_node)
    for c in constraints:
        if not isinstance(c, Constraint):
            continue
        if c.kind == "right-of":
            right_of.add((c.subject, c.object))
        elif c.kind == "left-of":
            right_of.add((c.object, c.subject))
        elif c.kind == "above":
            above_of.add((c.subject, c.object))
        elif c.kind == "below":
            above_of.add((c.object, c.subject))

    for edge in edges:
        if not edge.label:
            continue
        src_id, tgt_id = _effective_id(edge.source, edge.target)
        if src_id == tgt_id:
            continue
        src = vars_by_id.get(src_id)
        tgt = vars_by_id.get(tgt_id)
        if src is None or tgt is None:
            continue
        pair = (src_id, tgt_id)
        rpair = (tgt_id, src_id)
        h_related = pair in right_of or rpair in right_of
        v_related = pair in above_of or rpair in above_of
        if not h_related and not v_related:
            # No declared spatial relationship — emit horizontal STRONG only
            # (covers auto-layout children with direction: right).
            min_h = _label_min_gap_h(edge.label)
            solver.addConstraint((tgt.x - src.x2 >= min_h) | "strong")
            solver.addConstraint((src.x - tgt.x2 >= min_h) | "strong")
        elif h_related:
            # Horizontal relationship — emit horizontal STRONG in correct direction.
            min_h = _label_min_gap_h(edge.label)
            if pair in right_of:
                solver.addConstraint((src.x - tgt.x2 >= min_h) | "strong")
            else:
                solver.addConstraint((tgt.x - src.x2 >= min_h) | "strong")
        # v_related: vertical relationship handled by _label_min_gap_v in
        # _add_user_constraints (above/below constraint label expansion).
        # Don't emit horizontal STRONG — it would push nodes sideways.

def _add_user_constraints(
    solver: Solver,
    constraints: list,
    vars_by_id: dict[str, _NodeVars],
    view_name: str,
    model: Model | None = None,
) -> None:
    """Apply user position constraints."""
    # Build maps from node pair → min gap, separated by axis.
    h_label_gaps: dict[frozenset, float] = {}
    v_label_gaps: dict[frozenset, float] = {}
    h_kinds = {"left-of", "right-of"}
    v_kinds = {"above", "below"}
    if model is not None:
        # Collect which pairs have which axis constraints.
        h_pairs: set[frozenset] = set()
        v_pairs: set[frozenset] = set()
        for c in constraints:
            if hasattr(c, "object") and c.object:
                pair = frozenset([c.subject, c.object])
                if c.kind in h_kinds:
                    h_pairs.add(pair)
                elif c.kind in v_kinds:
                    v_pairs.add(pair)
        for edge in model.edges:
            if edge.label:
                pair = frozenset([edge.source, edge.target])
                if pair in h_pairs:
                    lg = _label_min_gap_h(edge.label)
                    if lg > h_label_gaps.get(pair, 0):
                        h_label_gaps[pair] = lg
                if pair in v_pairs:
                    lg = _label_min_gap_v(edge.label)
                    if lg > v_label_gaps.get(pair, 0):
                        v_label_gaps[pair] = lg

    for c in constraints:
        try:
            _add_one_constraint(solver, c, vars_by_id, h_label_gaps, v_label_gaps)
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
    h_label_gaps: dict | None = None,
    v_label_gaps: dict | None = None,
) -> None:
    s = vars_by_id[c.subject]
    user_gap = c.gap if c.gap else _GAP_DEFAULT
    pair = frozenset([c.subject, c.object]) if hasattr(c, "object") and c.object else None
    h_min = (h_label_gaps or {}).get(pair, 0) if pair else 0
    v_min = (v_label_gaps or {}).get(pair, 0) if pair else 0

    kind = c.kind

    if kind == "left-of":
        o = vars_by_id[c.object]
        gap = max(user_gap, h_min)
        solver.addConstraint((s.x2 + gap <= o.x) | "required")

    elif kind == "right-of":
        o = vars_by_id[c.object]
        gap = max(user_gap, h_min)
        solver.addConstraint((s.x >= o.x2 + gap) | "required")

    elif kind == "above":
        o = vars_by_id[c.object]
        gap = max(user_gap, v_min)
        solver.addConstraint((s.y2 + gap <= o.y) | "required")

    elif kind == "below":
        o = vars_by_id[c.object]
        gap = max(user_gap, v_min)
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
        o = vars_by_id[c.object]
        solver.addConstraint((s.cy == o.cy) | "required")

    elif kind == "align-centre":
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
        solver.addConstraint((s.w >= c.gap) | "required")

    elif kind == "min-height":
        solver.addConstraint((s.h >= c.gap) | "required")

    elif kind in ("direction", "grid"):
        pass

    else:
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
    model: "Model | None" = None,
) -> None:
    """Add sequential placement constraints for container children.

    For consecutive child pairs with a labelled edge between them, the gap
    is expanded to fit the label.  Uses REQUIRED priority so label gaps are
    always respected, not just preferred.
    """
    children = node.children
    if len(children) < 2:
        return

    # Build lookup: pair of child ids -> max label min-gap from model edges.
    label_gaps: dict[frozenset, float] = {}
    if model is not None:
        for edge in model.edges:
            if not edge.label:
                continue
            pair = frozenset([edge.source, edge.target])
            child_ids = {c.id for c in children}
            if pair <= child_ids:  # both endpoints are children of this node
                if direction == "right":
                    lg = _label_min_gap_h(edge.label)
                else:
                    lg = _label_min_gap_v(edge.label)
                if lg > label_gaps.get(pair, 0):
                    label_gaps[pair] = lg

    for i in range(1, len(children)):
        prev = vars_by_id[children[i - 1].id]
        curr = vars_by_id[children[i].id]
        pair = frozenset([children[i - 1].id, children[i].id])
        gap = max(_GAP_DEFAULT, label_gaps.get(pair, 0))
        if direction == "right":
            solver.addConstraint((curr.x >= prev.x2 + gap) | "required")
            solver.addConstraint((curr.y == prev.y) | "medium")
        else:  # down
            solver.addConstraint((curr.y >= prev.y2 + gap) | "required")
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
    solved_nodes = [
        _build_solved_node(node, vars_by_id, model, select)
        for node in nodes
    ]

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
        properties=node.properties,
        records=node.records,
    )

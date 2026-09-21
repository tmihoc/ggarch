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

import math
from collections import defaultdict, deque
from dataclasses import replace as _dc_replace

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
from ggarch.geometry import annotation_label_rect
from ggarch.model import (
    AnnotationBox,
    Constraint,
    FanConstraint,
    DiagramView,
    GgarchFile,
    Lifecycle,
    Model,
    Node,
    SelectClause,
)
from ggarch.router import _route_edge

# Annotation labels render at 11px (the annotation font); the
# strike target is the centred text rect at ~0.64em per char.
_ANN_CHAR_W = 7.2


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

    When GGARCH_LAYOUT=elk and the ELK runtime is available, views
    without declared positions lay out with ELK Layered (ADR-006) —
    positions and edge routes from the backend; the built-in floor
    below is the fallback (and serves every authored view).

    Raises ValidationError if user constraints are unsatisfiable.

    ELK is NOT auto-selected (2026-09-21, ADR-006 amendment): the floor
    serves every view — the typed hub planes are synthesis machinery an
    ELK build cannot express. The backend remains the on-demand oracle:
    ggarch.elk.layout_view() and scripts/elk-compare.py run it
    explicitly, side by side with the floor.
    """
    # View-level curation: except pairs drop declared edges before
    # expansion (source, target, type "" = any type) — the same filter
    # route() applies before its own materialization. Without it the
    # synthesized layout layers the graph around edges the view curated
    # out (measured: the "Juju enters" bootstrap arrows formed a
    # controller<->cloud cycle that stalled the sink-anchored Kahn and
    # dragged the clouds into the app column, even though route() later
    # dropped them — the ELK path already curated for the same reason).
    except_pairs = {(s, t, ty) for s, t, ty in
                    getattr(diagram.select, "except_pairs", []) or []}
    if except_pairs:
        model = _dc_replace(model, edges=[
            e for e in model.edges
            if not any((e.source == es and e.target == et
                        and (ty == "" or ty == e.type))
                       for es, et, ty in except_pairs)])

    # Materialize instances (stamped subtrees) before selection; the
    # router performs the same expansion via ggarch.instances.
    mat_nodes, mat_edges = materialize_instances(diagram.select, model)
    selected = _selected_nodes(diagram.select, model, mat_nodes)

    # Solve, with the typed hub planes tried first and abandoned on a
    # contradiction: dense typed webs (a record feeding and fed by the
    # same hubs) can make the plane floors contradictory — the plain
    # depth layout is the honest fallback, not a crash. The planes
    # must also never be WORSE than plain depth: an arrangement whose
    # cells collide (two nodes solved into one rect) falls back too —
    # a fan claiming an occupied column can under-constrain exactly
    # that cell, and an overlapped render is never the honest floor.
    try:
        layout = _solve_constraints(
            diagram, model, selected, mat_edges, planes=True)
    except ValidationError:
        if diagram.constraints:
            raise
        auto_cons, weak_align, auto_fans = _synthesize_auto_layout(
            diagram, selected, mat_edges, refine=False, planes=False)
        return _solve_constraints(
            diagram, model, selected, mat_edges,
            auto_cons=auto_cons, weak_align=weak_align,
            auto_fans=auto_fans)
    if diagram.constraints or not _layout_has_overlaps(layout):
        return layout
    auto_cons, weak_align, auto_fans = _synthesize_auto_layout(
        diagram, selected, mat_edges, refine=False, planes=False)
    return _solve_constraints(
        diagram, model, selected, mat_edges,
        auto_cons=auto_cons, weak_align=weak_align,
        auto_fans=auto_fans)


def _layout_has_overlaps(layout: SolvedLayout) -> bool:
    """True when two top-level nodes solved into the same cell."""
    rects = [n.rect for n in layout.nodes]
    for i in range(len(rects)):
        for j in range(i + 1, len(rects)):
            a, b = rects[i], rects[j]
            if not (a.x + a.w <= b.x + 0.5 or b.x + b.w <= a.x + 0.5
                    or a.y + a.h <= b.y + 0.5 or b.y + b.h <= a.y + 0.5):
                return True
    return False


def _solve_constraints(
    diagram: DiagramView,
    model: Model,
    selected: list,
    mat_edges: list,
    refine: bool = False,
    auto_cons: list | None = None,
    weak_align: list | None = None,
    auto_fans: list | None = None,
    planes: bool = True,
):
    """One constraint solve: synthesis -> fan expansion -> user
    constraints -> label contract. Called once for synthesized views
    (with the hub planes) and once, on ValidationError, without them."""
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

    if auto_cons is None:
        auto_cons, weak_align, auto_fans = _synthesize_auto_layout(
            diagram, selected, mat_edges, refine=bool(diagram.constraints),
            planes=planes)
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
    _add_origin_anchor(solver, selected, vars_by_id,
                       anchor_y=bool(diagram.constraints))

    # View auto-layout: when the diagram declares no positions at all,
    # synthesize a layered layout (SPEC, "Position is content" -- the
    # floor, not the ceiling). Merged into the constraint set so the
    # label-gap pass sees the declared pairs.
    expanded_constraints = _expand_fan_constraints(
        list(diagram.constraints) + auto_cons + auto_fans,
        solver, vars_by_id)

    # Auto-layout container children using direction constraints.
    # This runs before user constraints so user constraints can override.
    direction_map = _collect_directions(expanded_constraints)
    _add_auto_layout_pass(solver, selected, vars_by_id, diagram.select, direction_map, model)
    # Add user-declared constraints, with label-aware gap expansion.
    _add_user_constraints(solver, expanded_constraints, vars_by_id,
                          diagram.name, model,
                          refine=bool(diagram.constraints))
    _add_uniform_sizing(solver, expanded_constraints, vars_by_id)
    if diagram.select.sizing == "uniform" or not diagram.constraints:
        # Synthesized views get uniform leaf sizing by default — the
        # user's standing rule (same-rank nodes render the same size;
        # emphasis by label length is never a reason) and the floor's
        # tidiness precondition: uniform boxes give every column
        # aligned faces and uniform corridors.
        _add_uniform_leaf_sizing(solver, selected, vars_by_id)

    # Edge-aware floor: weak cross-column alignments for the primary
    # edges (a matching — at most one per node). Weak, added after the
    # structural constraints, so they pull the connected ranks
    # horizontal without ever fighting the stacking (a required
    # align-middle here would make stacked multi-fan layouts
    # unsatisfiable).
    for a_id, b_id in weak_align:
        if a_id in vars_by_id and b_id in vars_by_id:
            va, vb = vars_by_id[a_id], vars_by_id[b_id]
            solver.addConstraint((va.cy == vb.cy) | "weak")
    try:
        solver.updateVariables()
    except UnsatisfiableConstraint as exc:
        raise ValidationError(
            f"diagram {diagram.name!r}: unsatisfiable layout constraints — {exc}",
            hint="check for contradictory position constraints",
        ) from exc

    # Label contract (two-phase): measure the along-path geometry each
    # labelled edge would render at and reserve, at strong priority,
    # clearance wherever its label would strike content — a word that
    # cannot fit the leg, a strip striking a node or wall. Weak stays
    # pin this solution, so only measured shortfalls move.
    _apply_label_contract(solver, diagram, selected, mat_edges, vars_by_id)

    # Read results back.
    return _build_layout(selected, vars_by_id, model, diagram.select,
                         list(diagram.constraints) + auto_fans)

# ---------------------------------------------------------------------------
# View auto-layout
# ---------------------------------------------------------------------------

def _synthesize_auto_layout(
    diagram: DiagramView,
    selected: list,
    mat_edges: list,
    refine: bool = False,
    planes: bool = True,
) -> list[Constraint]:
    """Constraints for a view that declares no positions block.

    Position is content: where the arrangement is load-bearing the author
    declares it and this returns nothing. Where the arrangement is not
    load-bearing the author omits positions entirely and gets a
    coherent, flow-based layout:

    - Columns follow topological depth along the visible edges (the main
      flow runs left-to-right, honouring edge direction). Edge endpoints
      resolve to their top-level ancestors among the selected nodes, so
      edges between containers' children drive the containers' placement
      (a Raft mesh between Dqlite nodes lays out the controller nodes;
      a charm-to-pebble link lays out the unit containers).
    - Nodes that share a column stack vertically in declaration order.
    - Every visible edge gets a directly declared relationship at its
      effective endpoints (the deepest distinct ancestors, matching the
      label-gap pass's pair-local resolution), so its label gap resolves
      directionally.

    Refinement mode (ADR-007): when the view declares constraints, the
    synthesized base is emitted at "medium" strength instead of being
    skipped. The priority ladder is doctrine: declared arrangement is
    required (the author's word), the label contract's reservations are
    strong (ADR-002: labels are content), and the synthesized base is
    medium — synthesis fills the geometry the author left undeclared,
    yields to the label contract, and never outranks a declaration.
    Pure synthesis (no declared constraints) is unchanged: terms at
    required strength, byte-identical layouts.

    Cycles are handled by processing nodes in declaration order and
    ignoring not-yet-seen sources, which turns back edges into floors.
    Container children are otherwise unaffected -- the existing
    container auto-layout pass lays them out inside their parents.
    """
    strength = "medium" if refine else ""

    # Refinement: synthesis must not re-declare what the author
    # declared. A synthesized term on a pair the author already
    # constrained on the same axis would fight the declaration at
    # medium-vs-required (harmless) — or, worse, its corridor-budget
    # gap would silently WIDEN a declared adjacency: the budget
    # inequality is satisfied by any gap >= budget, so it drags the
    # declared pair's weak adjacency equality to the budget width and
    # the declared gap is lost (measured: the strike-avoidance contract
    # then mis-predicts and a labelled edge strikes). Declared pairs
    # are the author's; synthesis fills only the undeclared ones.
    declared_x: set[frozenset] = set()
    declared_y: set[frozenset] = set()
    declared_xalign: set[frozenset] = set()
    if refine:
        x_kinds = {"left-of", "right-of", "align-centre", "align-left",
                   "align-right"}
        y_kinds = {"above", "below", "align-middle", "align-top",
                   "align-bottom"}
        for c in diagram.constraints:
            if isinstance(c, Constraint) and c.object:
                pair = frozenset((c.subject, c.object))
                if c.kind in x_kinds:
                    declared_x.add(pair)
                    if c.kind in ("align-centre", "align-left",
                                  "align-right"):
                        declared_xalign.add(pair)
                elif c.kind in y_kinds:
                    declared_y.add(pair)
            elif isinstance(c, FanConstraint):
                anchor_pair = {frozenset((m, c.anchor)) for m in c.members}
                member_pairs = {frozenset((c.members[i], c.members[i + 1]))
                                for i in range(len(c.members) - 1)}
                if c.direction in ("above", "below"):
                    declared_y |= anchor_pair | member_pairs
                else:
                    declared_x |= anchor_pair | member_pairs
                    declared_xalign |= member_pairs

    top_ids = [n.id for n in selected]
    top_set = set(top_ids)

    # Parent map over the selected subtree (materialized ids), and
    # top-ancestor resolution for edge endpoints.
    parent: dict[str, str] = {}
    def _walk(node) -> None:
        for child in node.children:
            parent[child.id] = node.id
            _walk(child)
    for node in selected:
        _walk(node)

    def _chain(nid: str) -> list[str]:
        out = [nid]
        while nid in parent:
            nid = parent[nid]
            out.append(nid)
        return out

    def _top(nid: str) -> str | None:
        c = _chain(nid)
        return c[-1] if c[-1] in top_set else None

    # Visible edges: both endpoints resolve into the selected subtree,
    # honouring the view's edge-type filter.
    vis_edges = []
    for e in mat_edges:
        if e.source == e.target:
            continue
        if diagram.select.edge_types and e.type not in diagram.select.edge_types:
            continue
        ts, tt = _top(e.source), _top(e.target)
        if ts is None or tt is None or ts == tt:
            continue
        vis_edges.append((e, ts, tt))

    # Effective endpoints for the label-gap pair check: the deepest
    # node on each side that is not on the other's ancestry -- matching
    # _add_label_gap_constraints._effective_id.
    def _effective(src: str, tgt: str) -> tuple[str, str]:
        sc, tc = _chain(src), _chain(tgt)
        ts, tt = set(tc), set(sc)
        es = next((n for n in sc if n not in tt), sc[-1])
        et = next((n for n in tc if n not in ts), tc[-1])
        return es, et

    # Forward Kahn (source depth, 0.26.1): the common scale and the
    # cycle fallback — declaration-order one-pass for stalled members
    # (meshes keep their declared left-to-right order).
    indeg: dict[str, int] = {nid: 0 for nid in top_ids}
    succ: dict[str, list[str]] = {nid: [] for nid in top_ids}
    preds: dict[str, list[str]] = {nid: [] for nid in top_ids}
    for _e, s, t in vis_edges:
        if s == t:
            continue
        succ[s].append(t)
        preds[t].append(s)
        indeg[t] += 1
    fdepth: dict[str, int] = {}
    queue = deque(nid for nid in top_ids if indeg[nid] == 0)
    while queue:
        nid = queue.popleft()
        fdepth[nid] = max((fdepth[p] for p in preds[nid] if p in fdepth),
                          default=-1) + 1
        for t in succ[nid]:
            indeg[t] -= 1
            if indeg[t] == 0:
                queue.append(t)
    for nid in top_ids:  # cycle members (stalled queue): back-edge floors
        if nid not in fdepth:
            fdepth[nid] = max((fdepth[p] for p in preds[nid] if p in fdepth),
                              default=-1) + 1
    max_fdepth = max(fdepth.values(), default=0)

    # Sugiyama layering, SINK-ANCHORED (edge-aware floor v2): rdepth is
    # the longest path from the node to a sink (Kahn over the reversed
    # edges); col = max_fdepth - rdepth packs dependents AGAINST their
    # dependencies instead of scattering them into source-depth ranks —
    # undertaker (whose only edge sweeps two columns to domain
    # services) lands in the adjacent column, its arrow a clean
    # horizontal. For DAG nodes this is exact; cycle members (stalled
    # in the reversed queue — a Raft mesh) keep their declared order on
    # the forward scale.
    rindeg: dict[str, int] = {nid: 0 for nid in top_ids}
    rsucc: dict[str, list[str]] = {nid: [] for nid in top_ids}
    rpreds: dict[str, list[str]] = {nid: [] for nid in top_ids}
    for _e, s, t in vis_edges:
        if s == t:
            continue
        rsucc[t].append(s)      # reversed: dependency -> dependent
        rpreds[s].append(t)
        rindeg[s] += 1
    rdepth: dict[str, int] = {}
    queue = deque(nid for nid in top_ids if rindeg[nid] == 0)
    while queue:
        nid = queue.popleft()
        rdepth[nid] = max((rdepth[p] for p in rpreds[nid] if p in rdepth),
                          default=-1) + 1
        for s in rsucc[nid]:
            rindeg[s] -= 1
            if rindeg[s] == 0:
                queue.append(s)
    col: dict[str, int] = {}
    for nid in top_ids:
        if nid in rdepth:
            col[nid] = max_fdepth - rdepth[nid]
    for _ in top_ids:       # stalled (cycle) members: pull to targets
        moved = False
        for nid in top_ids:
            if nid in col:
                continue
            tcols = [col[t] - 1 for t in rpreds[nid] if t in col]
            if tcols:
                col[nid] = min(tcols)
                moved = True
        if not moved:
            break
    for nid in top_ids:     # still unplaced: forward scale
        col.setdefault(nid, fdepth[nid])

    def _label_w(label: str) -> float:
        if not label:
            return 0.0
        return max(len(ln) for ln in label.split("\\n")) * LABEL_CHAR_W

    # Typed hub planes (2026-09-21 reviewer direction: "giving each
    # type of meaning its own plane" — the declared "Juju enters" as
    # the model: spine LR, sink spokes fanned side by side in the
    # orthogonal band, feeder spokes east of the hub with RL arrows).
    # Pure synthesis only: in refinement mode the author's declaration
    # is the arrangement and synthesis fills the undeclared geometry.
    fan_cons: list[FanConstraint] = []
    fanned: set[str] = set()
    sink_fans: dict[str, list[str]] = {}
    spine_aligns: list[tuple[str, str]] = []
    spine_child_aligns: list[tuple[str, str]] = []
    feeder_fans: dict[str, list[str]] = {}
    peer_cons: list[Constraint] = []
    if not refine and planes:
        outs: dict[str, list[str]] = {}
        ins: dict[str, list[str]] = {}
        for _e, s, t in vis_edges:
            outs.setdefault(s, []).append(t)
            ins.setdefault(t, []).append(s)
        # Cycle members (stalled in the reversed Kahn — Raft meshes,
        # mutual pairs) keep the plain depth behaviour: a mesh has no
        # hub, and plane claims on mutually-feeding nodes contradict
        # their own layering.
        cycle = {nid for nid in top_ids if nid not in rdepth}

        # Pass A — sink spokes: a hub's sink successors fan side by
        # side in the orthogonal band (above, straddling its column;
        # with n >= 3 the last spoke hangs below — the declared
        # reference: clouds above, charmhub below for n=3). A lone
        # sink spoke hangs in the hub's column (charm under its
        # application); the column stack owns the rest. Depth column:
        # the fan centres the group on the hub's axis, so the
        # between-column emitter must not drag them a column east.
        sink_spokes: set[str] = set()
        for h in top_ids:
            if h in cycle:
                continue
            if len(outs.get(h, [])) < 2:
                continue
            sinks = [t for t in outs.get(h, []) if not outs.get(t)
                     and t not in fanned]
            if not sinks:
                continue
            for t in sinks:
                col[t] = col[h]
            sink_spokes.update(sinks)
            if len(sinks) == 1:
                continue
            # A SOURCE hub (no feeders — the actor of the view) reads
            # best with its satellites fanned EAST: the arrows run
            # left-to-right, the preattentive direction (2026-09-21
            # reviewer, tested with readers: the directed LR fan beats
            # radial and band placements at a glance). A hub with a
            # west-side spine feed stacks its spokes N/S around the
            # axis instead (the declared enters/overview/K8s
            # references) — the planes below.
            if not ins.get(h):
                label_w = max((_label_w(e.label) for e, s, t in vis_edges
                               if s == h and t in sinks), default=0.0)
                ordered = list(reversed(sinks))
                fan_cons.append(FanConstraint(
                    members=ordered, anchor=h, direction="right-of",
                    gap=max(40, int(label_w) + 35), spacing=20))
                for t in ordered:
                    col[t] = col[h] + 1
                fanned.update(ordered)
                sink_fans[h] = sinks
                continue
            # Stack split (2026-09-21 reviewer direction, the declared
            # overview and K8s references): mixed-type sink spokes
            # split across the hub's faces — api-type spokes (pull-from
            # stores: charmhub) hang BELOW on the hub's axis, the rest
            # (substrate/authority: clouds, k8s) fan above. Each face
            # group with one member stacks ON the axis (the fan's odd-n
            # align-centre), so its arrow joins the N/S face midpoints.
            # A single-type fan keeps the band rule: side by side
            # above, with n >= 3 the last spoke below.
            ety = {(s, t): e.type for e, s, t in vis_edges}
            mixed = len({ety.get((h, t), "") for t in sinks}) > 1
            if mixed:
                below = [t for t in reversed(sinks)
                         if ety.get((h, t)) == "api"]
                above = [t for t in reversed(sinks)
                         if ety.get((h, t)) != "api"]
            else:
                below_count = 1 if len(sinks) >= 3 else 0
                ordered = list(reversed(sinks))
                below = ordered[-below_count:] if below_count else []
                above = ordered[:len(sinks) - below_count]
            # Member spacing carries the riding labels: the widest
            # label plus clearance, floor 40 — the declared view's
            # measured 120 for 85px labels.
            label_w = max((_label_w(e.label) for e, s, t in vis_edges
                           if s == h and t in sinks), default=0.0)
            spacing = max(40, int(label_w) + 35)
            if above:
                fan_cons.append(FanConstraint(
                    members=above, anchor=h, direction="above",
                    gap=40, spacing=spacing))
                fanned.update(above)
            if below:
                fan_cons.append(FanConstraint(
                    members=below, anchor=h, direction="below",
                    gap=40, spacing=spacing))
                fanned.update(below)
            sink_fans[h] = sinks

        # Pass B — feeder spokes: the spine feed (the predecessor
        # deepest on the forward scale, excluding fanned spokes — a
        # spoke cannot define the plane it hangs off) stays west;
        # every other feeder fans EAST of the hub with RL arrows, the
        # feeder plane.
        for h in top_ids:
            if h in cycle:
                continue
            feeders = [p for p in ins.get(h, [])
                       if p not in fanned and p not in cycle]
            if not feeders:
                continue
            if h in fanned or h in sink_spokes:
                # A spoke's row is owned by its own plane: a fan owns
                # its members' rows, and a lone sink spoke stacks in
                # its hub's column (the child-stacking rule). A spine
                # align here would pin the spoke onto its feeder's row
                # and contradict the plane (measured: unit_a above the
                # controller vs the spine align dragging it onto the
                # controller's row; charm's align vs its stack under
                # the application — the honest fallback hid the whole
                # planes path in four views).
                continue
            # A lone feeder IS the spine (2026-09-21: the declared K8s
            # reference — unit_pod feeds controller_pod alone, and the
            # spine's required align-middle still holds; the old
            # >=2-feeder gate left the K8s spine rows unpinned).
            spine = max(feeders, key=lambda p: fdepth.get(p, -1))
            if col.get(spine) == col.get(h):
                # The pair shares a column — the within-column stack
                # owns their rows (the child-stacking reading: charm
                # below its application, api_server above object_
                # store). A spine align would pin the pair onto one
                # row and contradict the stack; skip it (measured: the
                # honest fallback hid the whole planes path in the
                # dense record views).
                continue
            spine_aligns.append((spine, h))
            spoke_feeders = [p for p in feeders if p != spine]
            # The feeder fan claims the column east of the hub; when
            # that column already holds depth-assigned NON-members,
            # the claim collides with them (measured: the worker
            # tree's provider_tracker fanned onto change_stream's
            # cell — same column, both rows pinned to the hub's row).
            # The fan then stays home: the members keep their depth
            # columns and the spine aligns flatten the chain instead —
            # the straight LR reading (the declared arrangement's own
            # answer for a chain with a side feed).
            target_col = col.get(h, 0) + 1
            occupied = any(col.get(nid) == target_col for nid in top_ids
                           if nid not in spoke_feeders and nid not in fanned)
            if spoke_feeders and not occupied:
                feeder_fans[h] = spoke_feeders
                for p in spoke_feeders:
                    col[p] = target_col
                # The feeder column centres on the hub's row (the
                # declared apps fan); a LONE spoke feeder hangs in the
                # hub's row (align-middle via the fan's odd-n rule —
                # symmetric with the lone sink's column stack), and the
                # member gap carries the riding labels.
                label_w = max((_label_w(e.label)
                               for e, s, t in vis_edges
                               if s in spoke_feeders and t == h),
                              default=0.0)
                fan_cons.append(FanConstraint(
                    members=spoke_feeders, anchor=h,
                    direction="right-of",
                    gap=max(40, int(label_w) + 35), spacing=20))
                fanned.update(spoke_feeders)

        # Peer rows (2026-09-21 reviewer, the HA replicaset: "the
        # replicas parallel on the same row... the placement algorithm
        # would be missing an important grouping generalization").
        # Instances of one type are PEERS by construction — the same
        # archetype stamped N times — so an instance group the planes
        # did not claim (no fan owns it, no relationships pulled it
        # apart) reads as a horizontal row, not a column stack. Groups
        # a fan claimed keep the fan's plane (the enters apps fan east,
        # the declared clouds band above).
        peer_groups: dict[str, list[str]] = {}
        for spec in diagram.select.instances:
            peer_groups.setdefault(spec.type_id, []).append(spec.instance_id)
        for members in peer_groups.values():
            if len(members) < 2:
                continue
            if any(m in fanned or m in sink_spokes or m in cycle
                   for m in members):
                continue
            cols = {col.get(m) for m in members}
            if len(cols) != 1 or None in cols:
                continue
            for i in range(len(members) - 1):
                peer_cons.append(Constraint(kind="left-of",
                                            subject=members[i],
                                            object=members[i + 1],
                                            gap=100, strength=strength))
                peer_cons.append(Constraint(kind="align-middle",
                                            subject=members[i],
                                            object=members[i + 1],
                                            strength=strength))

        # Spine free-side flip (2026-09-21 reviewer direction: straight
        # arrows where straight arrows are possible, minimal
        # arrow/node overlap — the declared K8s reference:
        # controller_pod LEFT of unit_pod). A container feed whose
        # spine edge originates at a nested child exits through the
        # child's free side — no row siblings beyond it at ANY level of
        # its ancestry. When that free side faces AWAY from the hub,
        # the straight spine is structurally impossible on the depth
        # order (measured: unit_agent's east corridor is walled by its
        # own row siblings, so the L detoured 718px through the pod's
        # top corridor); the spine pair swaps columns — the hub takes
        # the free side — instead of routing the spine around the
        # feed's own row. Both spine endpoints must be free toward
        # each other after the flip, else the honest L stays.
        node_by_id: dict = {}

        def _reg_nodes(n) -> None:
            node_by_id[n.id] = n
            for c in n.children:
                _reg_nodes(c)
        for n in selected:
            _reg_nodes(n)
        direction_map = _collect_directions(list(diagram.constraints))

        def _free_sides(nid: str, stop: str) -> set:
            sides = {"west", "east"}
            cur = nid
            while cur != stop and sides:
                p = parent.get(cur)
                if p is None:
                    return set()
                sibs = node_by_id[p].children
                if len(sibs) > 1 and direction_map.get(p, "right") == "right":
                    idx = next((i for i, s in enumerate(sibs)
                                if s.id == cur), None)
                    if idx is None:
                        return set()
                    if idx != 0:
                        sides.discard("west")
                    if idx != len(sibs) - 1:
                        sides.discard("east")
                cur = p
            return sides

        spine_child_aligns = []
        for feed, hub in list(spine_aligns):
            fn, hn = node_by_id.get(feed), node_by_id.get(hub)
            if fn is None or hn is None or not fn.children:
                continue
            spine_edges = [(e, s, t) for e, s, t in vis_edges
                           if s == feed and t == hub]
            if not spine_edges:
                continue
            for e, _s, _t in spine_edges:
                if e.source != feed and e.target != hub:
                    # Both endpoints nested: the spine arrow runs
                    # child-to-child — align the children's rows too
                    # (the declared K8s pins jujud align-middle
                    # unit_agent; the pods' align alone leaves the
                    # pads' offset in). Raw endpoints: the edge's own
                    # ids are the deepest distinct ends (the shared
                    # _effective resolves to the TOP ancestors — its
                    # chain-exclusion is self-referential — so it can
                    # never produce a child pair).
                    spine_child_aligns.append((e.source, e.target))
            src_free = _free_sides(spine_edges[0][0].source, feed)
            tgt_free = _free_sides(spine_edges[0][0].target, hub)
            if not src_free or not tgt_free:
                continue
            if any(e.source == feed or e.target == hub
                   for e, _s, _t in spine_edges):
                continue    # a container-level endpoint exits its own face
            hub_east = col.get(hub, 0) > col.get(feed, 0)
            flip = (("west" in src_free and "east" in tgt_free)
                    if hub_east else
                    ("east" in src_free and "west" in tgt_free))
            if flip:
                # The swap carries the hub's PLANES with it: its sink
                # spokes share its column (col[t] = col[h]) and its
                # feeder spokes hang a column east — stranding them in
                # the old column makes the between-column left-of fight
                # the fans' align-centre (measured: k8s/charmhub stuck
                # in unit_pod's column vs their above/below fans, the
                # whole planes path unsatisfiable, the honest fallback).
                col[feed], col[hub] = col[hub], col[feed]
                for t in sink_fans.get(hub, []):
                    col[t] = col[hub]
                for p in feeder_fans.get(hub, []):
                    col[p] = col[hub] + 1

    # Compact to consecutive columns; then BARYCENTER row ordering
    # (Sugiyama step 4): rows ordered by the mean position of their
    # neighbours in the adjacent columns, alternating sweeps — the
    # standard crossing-minimisation, so arrows stop meeting faces at
    # arbitrary heights. Nodes without neighbours on a side keep their
    # current slot (stable).
    used = sorted(set(col.values()))
    col = {nid: used.index(d) for nid, d in col.items()}
    columns: dict[int, list[str]] = {}
    for nid in top_ids:
        columns.setdefault(col[nid], []).append(nid)
    nbrs: dict[str, list[str]] = {nid: [] for nid in top_ids}
    for _e, s, t in vis_edges:
        if col.get(s) != col.get(t):
            nbrs[s].append(t)
            nbrs[t].append(s)
    # Boundary edges for the crossing count (adjacent columns only;
    # multi-column spans contribute the same whatever the rows do).
    span: dict[int, list[tuple[str, str]]] = {}
    for _e, s, t in vis_edges:
        if 0 <= col[s] and col[s] + 1 == col[t]:
            span.setdefault(col[s], []).append((s, t))

    def _crossings() -> int:
        total = 0
        for c, es in span.items():
            left = columns.get(c, [])
            right = columns.get(c + 1, [])
            li = {nid: i for i, nid in enumerate(left)}
            ri = {nid: i for i, nid in enumerate(right)}
            pairs = [(li[s], ri[t]) for s, t in es if s in li and t in ri]
            for i in range(len(pairs)):
                for j in range(i + 1, len(pairs)):
                    (a1, b1), (a2, b2) = pairs[i], pairs[j]
                    if (a1 - a2) * (b1 - b2) < 0:
                        total += 1
        return total

    # Alternating sweeps, keeping the FEWEST-CROSSINGS arrangement —
    # the last sweep would otherwise oscillate (the up-sweep orders by
    # left neighbours and undoes the down-sweep's right-neighbour
    # ordering).
    best_arr: dict[int, list[str]] | None = None
    best_cross = None
    for sweep in range(4):
        order = range(len(used)) if sweep % 2 == 0 \
            else range(len(used) - 1, -1, -1)
        for c in order:
            members = columns.get(c)
            if not members or len(members) < 2:
                continue
            other = c - 1 if sweep % 2 else c + 1
            pos = {nid: i for i, nid in enumerate(columns.get(other, []))}

            def key(nid: str) -> tuple[float, int]:
                ns = [pos[t] for t in nbrs[nid]
                      if col.get(t) == other and t in pos]
                if ns:
                    mean: float = sum(ns) / len(ns)
                else:
                    mean = float(members.index(nid))
                return (mean, members.index(nid))
            columns[c] = sorted(members, key=key)
        cr = _crossings()
        if best_cross is None or cr < best_cross:
            best_cross = cr
            best_arr = {c: list(v) for c, v in columns.items()}
    if best_arr is not None:
        for c in list(columns):
            columns[c] = best_arr.get(c, columns[c])

    # Fanned members leave their column's stacking — SINK spokes and
    # FEEDER spokes alike (the FanConstraint owns their plane; the
    # hub stays, so its row follows the spine). The old loop iterated
    # sink_fans, so a view with only feeder fans (the full spine's
    # credential fan) never stripped its fan members: their fan
    # align-middles then contradicted the column stack and the whole
    # planes path fell back — the honest fallback hid the planes.
    # Peer-row members leave too (the peer row owns their plane).
    for c in columns:
        columns[c] = [nid for nid in columns[c] if nid not in fanned]
    if peer_cons:
        peers = {m for c in peer_cons for m in (c.subject, c.object)}
        for c in columns:
            columns[c] = [nid for nid in columns[c] if nid not in peers]

    GAP = 60
    cons: list[Constraint] = []
    cons.extend(peer_cons)
    # Within a column: stack vertically, centred.
    for members in columns.values():
        for i in range(len(members) - 1):
            u, v = members[i], members[i + 1]
            pair = frozenset((u, v))
            if pair not in declared_y:
                cons.append(Constraint(kind="above", subject=u, object=v,
                                       gap=GAP, strength=strength))
            if pair not in declared_x:
                cons.append(Constraint(kind="align-centre", subject=u,
                                       object=v, strength=strength))

    # The spine is a plane statement, not a coordinate nudge: the
    # hub's row holds with the spine feed at the floor's own strength
    # (required, like every other pure-synthesis term — the generic
    # weak pulls stay the barycenter coordinates). A synthesized spine
    # that folded to a strong label reservation would trade the plane
    # for a corridor the declared view itself keeps audited (measured:
    # the enters hub dropped 37px and bent the spine for a stub-label
    # corridor its target-exempt label rides anyway).
    for a_id, b_id in spine_aligns:
        cons.append(Constraint(kind="align-middle", subject=a_id,
                               object=b_id, strength="required"))
    for a_id, b_id in spine_child_aligns:
        cons.append(Constraint(kind="align-middle", subject=a_id,
                               object=b_id, strength="required"))

    # Corridor budget (the edge-aware floor): a column boundary must be
    # wide enough for every edge whose label rides through it — the
    # label's longest line plus side pads and arrowhead clearance. A
    # fixed 60px gap starves any corridor carrying a labelled edge
    # (the juju4 forced strike: a 57px label in a 60px gap).
    boundary_budget: dict[int, float] = {}
    for e, ts, tt in vis_edges:
        cs, ct = col[ts], col[tt]
        if cs == ct:
            continue
        # Refinement: a corridor whose labelled edge the author
        # declared a gap for is budgeted the author's way (they chose
        # the wrap); re-budgeting it at the un-wrapped label width
        # would drag neighbouring undeclared pairs out to that width.
        if refine and frozenset((ts, tt)) in declared_x:
            continue
        need = _label_w(e.label) + 2 * LABEL_SIDE_PAD + 24
        lo, hi = min(cs, ct), max(cs, ct)
        for b in range(lo, hi):
            boundary_budget[b] = max(boundary_budget.get(b, GAP), need)

    # Between adjacent columns: every left-column member is left of
    # every right-column member, at the boundary's budgeted corridor.
    for c in range(len(used) - 1):
        gap = int(boundary_budget.get(c, GAP))
        for u in columns.get(c, []):
            for v in columns.get(c + 1, []):
                if frozenset((u, v)) in declared_x:
                    continue
                cons.append(Constraint(kind="left-of", subject=u,
                                       object=v, gap=gap,
                                       strength=strength))
    # Every visible edge gets a directly declared pair, at its effective
    # endpoints (child-to-child edges declare their children, which the
    # containment constraints then translate into container separation).
    weak_align: list[tuple[str, str]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for e, ts, tt in vis_edges:
        cs, ct = col[ts], col[tt]
        es, et = _effective(e.source, e.target)
        if cs < ct:
            gap = int(boundary_budget.get(cs, GAP))
            if frozenset((es, et)) not in declared_x:
                cons.append(Constraint(kind="left-of", subject=es,
                                       object=et, gap=gap,
                                       strength=strength))
            if ct == cs + 1 and (es, et) not in seen_pairs:
                # Sugiyama coordinate assignment: EVERY adjacent-column
                # edge weakly pulls its two endpoints to the same
                # height. Weak constraints cannot conflict-raise, so a
                # node with several feeders settles at their mean — the
                # solver computes the barycenter coordinates (the phase
                # we skipped: db_accessor floated to the top row while
                # its feeders sat in rows 2-3; http_server->api_server
                # bent around a one-row offset with nothing blocking).
                weak_align.append((es, et))
                seen_pairs.add((es, et))
        elif cs > ct:
            gap = int(boundary_budget.get(ct, GAP))
            if frozenset((es, et)) not in declared_x:
                cons.append(Constraint(kind="left-of", subject=et, object=es,
                                       gap=gap, strength=strength))
        else:
            members = columns[cs]
            if ts not in members or tt not in members:
                continue    # fanned: the FanConstraint owns the plane
            i, j = members.index(ts), members.index(tt)
            u, v = members[min(i, j)], members[max(i, j)]
            if frozenset((u, v)) not in declared_y:
                cons.append(Constraint(kind="above", subject=u, object=v,
                                       gap=GAP, strength=strength))
    return cons, weak_align, fan_cons


def _add_uniform_sizing(
    solver: Solver,
    constraints: list,
    vars_by_id: dict[str, _NodeVars],
) -> None:
    """Rank uniformity (Mermaid/Structurizr grade, review round 1):
    fan members share one size (the units of a fanout are the same
    thing — same box); align-middle rows share one width (a rank reads
    as a unit). Required equalities at the max of the members' needs;
    labels always fit (the widest member sets the size)."""
    parent: dict[str, str] = {}

    def find(x):
        while parent.get(x, x) != x:
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    fan_roots: set[str] = set()
    for c in constraints:
        if isinstance(c, FanConstraint):
            ms = [m for m in c.members if m in vars_by_id]
            for i in range(len(ms) - 1):
                union(ms[i], ms[i + 1])
            if ms:
                fan_roots.add(find(ms[0]))
        elif isinstance(c, Constraint) and c.kind == "align-middle":
            if c.subject in vars_by_id and c.object in vars_by_id:
                union(c.subject, c.object)

    groups: dict[str, list[str]] = defaultdict(list)
    for nid in list(parent):
        groups[find(nid)].append(nid)
    for root, members in groups.items():
        vs = [vars_by_id[n] for n in members]
        if len(vs) < 2:
            continue
        for i in range(len(vs)):
            for j in range(len(vs)):
                if i != j:
                    solver.addConstraint((vs[i].w >= vs[j].w) | "strong")
        if root in fan_roots:
            for i in range(len(vs)):
                for j in range(len(vs)):
                    if i != j:
                        solver.addConstraint(
                            (vs[i].h >= vs[j].h) | "strong")


def _add_uniform_leaf_sizing(
    solver: Solver,
    selected: list[Node],
    vars_by_id: dict[str, _NodeVars],
) -> None:
    """`sizing: uniform` (review round 2): every selected top-level
    leaf node renders the same size — no node gets visual emphasis
    merely because its label is longer. Containers keep their
    content-driven size."""
    leaves = [n for n in selected
              if not n.children and n.id in vars_by_id]
    for i in range(len(leaves)):
        for j in range(len(leaves)):
            if i == j:
                continue
            vi = vars_by_id[leaves[i].id]
            vj = vars_by_id[leaves[j].id]
            solver.addConstraint((vi.w >= vj.w) | "strong")
            solver.addConstraint((vi.h >= vj.h) | "strong")


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

    # ADR-005: `records: shown` — a view drawing the persistence bridge
    # needs the record node laid out too. Auto-include from the
    # selected subtrees (the record is the bridge's far endpoint, not
    # an editorial choice).
    if getattr(select, "show_records", False):
        present = {n.id for n in result}
        for n in result:
            stack = [n]
            while stack:
                cur = stack.pop()
                stack.extend(cur.children)
                rec = cur.records
                if rec and rec not in present:
                    rec_node = _find_in_tree(mat_nodes, rec)
                    if rec_node is not None:
                        result.append(rec_node)
                        present.add(rec)
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
        # Symmetric vertical padding (2026-09-21 reviewer: a fan arrow
        # leaving a nested child must be align-middle'ed with the child
        # AND the hub — possible only when the child row sits on the
        # container's midline; the label band's top pad alone put rows
        # ~12px low). The bottom pad equals the top pad, so the content
        # centres on the box and every level of nesting stays on the
        # midline.
        solver.addConstraint(
            (cv.y2 <= parent.y2 - CONTAINER_PAD_TOP) | "required"
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
    anchor_y: bool = True,
) -> None:
    """Anchor the first top-level node at (0, 0) with WEAK priority.

    This prevents the layout from floating to arbitrary coordinates while
    still allowing user constraints to override the position.

    anchor_y=False for synthesized views: the required non-negativity
    chain from the anchor node otherwise pins the spine row at y=0 and
    forbids the typed hub planes from fanning a band ABOVE the spine
    (the solver then breaks the spine's weak alignment instead — the
    whole arrangement pays for one weak pin). _build_layout translates
    the solved boxes back to the origin.
    """
    if not nodes:
        return
    first = vars_by_id[nodes[0].id]
    solver.addConstraint((first.x == 0) | "weak")
    if anchor_y:
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
            # -- 3. All members on the same vertical column, aligned
            # toward the anchor: a right-of fanout hangs its members'
            # LEFT edges off the anchor's right; a left-of fan mirrors.
            # (Centre-aligning unequal-width members forced symmetric
            # container inflation — the empty-container defect.)
            column_align = ("align-left" if c.direction == "right-of"
                            else "align-right")
            for m in members:
                result.append(Constraint(kind=column_align,
                                         subject=m, object=members[0]))
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
# Label contract — along-path reservations (ADR-002)
# ---------------------------------------------------------------------------
# Labels ride the arrow's longest leg (renderer.label_geometry is the
# single source of measurement; the constants below are that module's).
# The contract reserves clearance only when the label would strike
# content: a word that cannot fit on the leg, a strip that would
# strike a node or cross its own container's wall.

from ggarch.renderer import (  # noqa: E402 — shared measurement source
    LABEL_CHAR_W,
    LABEL_CLEARANCE,
    LABEL_LINE_H,
    LABEL_SIDE_PAD,
    label_geometry,
)

_GAP_DEFAULT = 20  # px — default gap when not specified
_RESERVE_SLACK = 6        # px headroom over the renderer's need
_STRIKE_EPS = 1.0         # px — overlap tolerance for strike tests
_LEG_DOMINANCE = 0.75     # |ux| or |uy| threshold for strike checks


def _label_min_gap(label: str) -> float:
    """Authored-gap floor for a labelled pair: the widest word plus
    side padding — the shortest leg that hosts every word on a line
    (labels wrap to the leg; the stroke is never cut)."""
    words = [w for raw in label.split("\\n") for w in raw.split()]
    widest = max((len(w) for w in words), default=0) * LABEL_CHAR_W
    return widest + LABEL_SIDE_PAD * 2


def _pts_cross_rect(pts, x: float, y: float, x2: float, y2: float) -> bool:
    """Does the polyline enter the rect's interior (already inset)?"""
    for (px1, py1), (px2, py2) in zip(pts, pts[1:]):
        length = math.hypot(px2 - px1, py2 - py1)
        steps = max(2, int(length * 2))
        for i in range(steps + 1):
            t = i / steps
            x_, y_ = px1 + (px2 - px1) * t, py1 + (py2 - py1) * t
            if x < x_ < x2 and y < y_ < y2:
                return True
    return False


def _measure_label_reservations(
    diagram: DiagramView,
    selected: list[Node],
    mat_edges: list,
    vars_by_id: dict[str, _NodeVars],
) -> list[tuple[str, str, str, float]]:
    """Measured reservations for along-path label placement (ADR-002).

    For every labelled visible edge: resolve the effective endpoints
    (the deepest solver-tracked distinct ancestors — the pair the
    solver can actually push apart), draw the route the renderer would
    draw between them, and measure the label it would draw on the
    longest leg (renderer.label_geometry). Reservations, each applied
    STRONG in _apply_label_contract:

      ("h", left, right, gap)    word fit — left.x2 + gap <= right.x
      ("v", above, below, gap)   word fit — above.y2 + gap <= below.y
      ("v", node, end, gap)      node strike, horizontal leg (node above)
      ("h", end, node, gap)      node strike, vertical leg (node right)
      ("wall-top", cont, child, need)   strip past the container's top pad
      ("wall-right", cont, child, need) strip past the container's right pad

    Word-fit shortfalls reserve the widest word plus side padding.
    Node strikes reserve the strip's perpendicular clearance from the
    struck node to each endpoint — only when the stroke itself clears
    the node (a stroke crossing a node is a router defect, never a
    label reservation). Wall strikes grow the container. Strikes are
    only measured on axis-dominant legs; diagonal labels are router
    work (the geometry audit tracks them).
    """
    parent: dict[str, str] = {}
    def _walk(node: Node, pid: str | None) -> None:
        if pid is not None:
            parent[node.id] = pid
        for child in node.children:
            _walk(child, node.id)
    for node in selected:
        _walk(node, None)

    def _chain(nid: str) -> list[str]:
        out = []
        while nid in vars_by_id:
            out.append(nid)
            nid = parent.get(nid, "")
        return out

    out: list[tuple[str, str, str, float]] = []
    for edge in mat_edges:
        if not edge.label or edge.source == edge.target:
            continue
        if (diagram.select.edge_types
                and edge.type not in diagram.select.edge_types):
            continue
        src_chain, tgt_chain = _chain(edge.source), _chain(edge.target)
        src_set, tgt_set = set(src_chain), set(tgt_chain)
        exempt_ids = src_set | tgt_set
        es = next((n for n in src_chain if n not in tgt_set), None)
        et = next((n for n in tgt_chain if n not in src_set), None)
        if es is None or et is None or es == et:
            continue
        vs, vt = vars_by_id.get(es), vars_by_id.get(et)
        if vs is None or vt is None:
            continue
        rs = Rect(vs.x.value(), vs.y.value(), vs.w.value(), vs.h.value())
        rt = Rect(vt.x.value(), vt.y.value(), vt.w.value(), vt.h.value())

        # The route the renderer would draw.
        if edge.source_field or edge.target_field:
            # Field-qualified edges route flat at the fields' mid-y;
            # the segment spans the facing faces.
            left, right = (rs, rt) if rs.cx <= rt.cx else (rt, rs)
            my = (rs.cy + rt.cy) / 2
            pts = [(left.x2, my), (right.x, my)]
        else:
            # The route the router would draw, obstacles included
            # (ancestor-or-self of either endpoint exempt) — the
            # contract measures the detour the label actually rides.
            obstacles = [
                ((v.x.value(), v.y.value(),
                  v.x.value() + v.w.value(), v.y.value() + v.h.value()), nid)
                for nid, v in vars_by_id.items()
                if nid not in exempt_ids]
            pts = [(p.x, p.y) for p in _route_edge(rs, rt, obstacles)]
        if not pts:
            continue

        lg = label_geometry(pts, edge.label, 0.5)

        # Word fit: a word wider than the leg minus side padding
        # reserves the word's width on the leg's dominant axis. The
        # strike geometry changes once the leg widens, so strikes are
        # re-measured next round rather than reserved against a leg
        # that is about to move.
        if lg.widest_word_w > lg.leg_len - LABEL_SIDE_PAD * 2:
            need = lg.widest_word_w + LABEL_SIDE_PAD * 2 + _RESERVE_SLACK
            if lg.rotated:
                above, below = (es, et) if rs.cy <= rt.cy else (et, es)
                out.append(("v", above, below, need))
            else:
                left_id, right_id = (es, et) if rs.cx <= rt.cx else (et, es)
                out.append(("h", left_id, right_id, need))
            continue

        # Strikes need an axis-dominant leg to have a clear axis.
        if max(lg.ux, lg.uy) < _LEG_DOMINANCE:
            continue
        depth = LABEL_CLEARANCE + LABEL_LINE_H * len(lg.lines) + _RESERVE_SLACK
        strip = lg.strip
        sx, sy = lg.anchor

        # Node strikes: the one-sided strip vs every node that is not
        # an ancestor-or-self of an endpoint and that the stroke
        # itself clears.
        exempt = src_set | tgt_set
        seen: set[int] = set()
        for nid, nv in vars_by_id.items():
            if id(nv) in seen:
                continue
            seen.add(id(nv))
            if nid in exempt:
                continue
            nx, ny = nv.x.value(), nv.y.value()
            nw, nh = nv.w.value(), nv.h.value()
            if (strip[2] <= nx + _STRIKE_EPS
                    or strip[0] >= nx + nw - _STRIKE_EPS
                    or strip[3] <= ny + _STRIKE_EPS
                    or strip[1] >= ny + nh - _STRIKE_EPS):
                continue  # no overlap
            if _pts_cross_rect(pts, nx + _STRIKE_EPS, ny + _STRIKE_EPS,
                               nx + nw - _STRIKE_EPS, ny + nh - _STRIKE_EPS):
                continue  # the stroke already crosses it: router work
            if lg.rotated:
                # Vertical leg: the strip extends right of the stroke.
                if nv.cx.value() <= sx:
                    continue
                for eid, ev in ((es, vs), (et, vt)):
                    # Separability guard: an "h" reservation between
                    # vertically-stacked nodes (a fan column) is
                    # unresolvable — kiwi's error minimisation would
                    # drag the struck container's content sideways and
                    # inflate it (the u_app2 stretch). The strike is
                    # audited; the route owns it.
                    if not (nv.x.value() >= ev.x.value() + ev.w.value()
                            - _STRIKE_EPS
                            or nv.x.value() + nv.w.value()
                            <= ev.x.value() + _STRIKE_EPS):
                        continue
                    gap = depth - (sx - (ev.x.value() + ev.w.value()))
                    if gap > 0:
                        out.append(("h", eid, nid, gap))
            else:
                # Horizontal leg: the strip extends above the stroke.
                if nv.cy.value() >= sy:
                    continue
                for eid, ev in ((es, vs), (et, vt)):
                    # Separability guard (mirror of the rotated case):
                    # only vertically-separable pairs.
                    if not (nv.y.value() >= ev.y.value() + ev.h.value()
                            - _STRIKE_EPS
                            or nv.y.value() + nv.h.value()
                            <= ev.y.value() + _STRIKE_EPS):
                        continue
                    gap = depth - (sy - ev.y.value())
                    if gap > 0:
                        out.append(("v", nid, eid, gap))

        # Annotation label strikes (2026-09-21 reviewer: labels NEVER
        # overlap - an annotation's label is content too, and the
        # measured defect was a riding edge label through an
        # annotation's label band). The label TEXT is centred in its
        # band (the band itself spans the members' union, which for a
        # wide box would strike everything); the strike target is the
        # text's own rect. The box follows its members, so reserving
        # the edge's endpoint away from the member that defines the
        # struck side holds the clearance as they move.
        for ann in diagram.annotations:
            if not isinstance(ann, AnnotationBox):
                continue
            member_ids = [m for m in ann.nodes if m in vars_by_id]
            if not member_ids:
                continue
            member_boxes = [(v.x.value(), v.y.value(),
                             v.x.value() + v.w.value(),
                             v.y.value() + v.h.value())
                            for v in (vars_by_id[m] for m in member_ids)]
            lrect = annotation_label_rect(ann, member_boxes)
            if lrect is None:
                continue
            text_w = len(ann.label) * _ANN_CHAR_W + 2 * LABEL_SIDE_PAD
            if ann.label_position in ('left', 'right'):
                cy = (lrect[1] + lrect[3]) / 2
                trect = (lrect[0], cy - text_w / 2, lrect[2],
                         cy + text_w / 2)
            else:
                cx = (lrect[0] + lrect[2]) / 2
                trect = (cx - text_w / 2, lrect[1], cx + text_w / 2,
                         lrect[3])
            if (strip[2] <= trect[0] + _STRIKE_EPS
                    or strip[0] >= trect[2] - _STRIKE_EPS
                    or strip[3] <= trect[1] + _STRIKE_EPS
                    or strip[1] >= trect[3] - _STRIKE_EPS):
                continue  # no overlap
            if _pts_cross_rect(pts, *trect):
                continue  # the stroke runs through the band: router work
            # The reservation primitive anchors at a member node, so
            # the shortfall is measured to that same member: required
            # slack = (member-to-band offset) + label depth.
            if lg.rotated:
                # Vertical leg: the strip extends right of the stroke;
                # the edge node must clear the band horizontally.
                right = max(member_boxes, key=lambda b: b[2])
                left = min(member_boxes, key=lambda b: b[0])
                for eid, ev in ((es, vs), (et, vt)):
                    if ev.x.value() >= trect[2] - _STRIKE_EPS:
                        m_id = member_ids[member_boxes.index(right)]
                        gap = (right[2] - trect[2]) + depth \
                            - (ev.x.value() - right[2])
                        if gap > 0:
                            out.append(('h', m_id, eid, gap))
                    elif (ev.x.value() + ev.w.value()
                          <= trect[0] + _STRIKE_EPS):
                        m_id = member_ids[member_boxes.index(left)]
                        gap = (trect[0] - left[0]) + depth \
                            - (left[0] - ev.x2.value())
                        if gap > 0:
                            out.append(('h', eid, m_id, gap))
            else:
                # Horizontal leg: the strip extends above the stroke.
                # The edge node sits above or below the band; reserve
                # in the direction that opens the gap.
                low = max(member_boxes, key=lambda b: b[3])
                high = min(member_boxes, key=lambda b: b[1])
                for eid, ev in ((es, vs), (et, vt)):
                    if ev.y2.value() <= trect[1] + _STRIKE_EPS:
                        m_id = member_ids[member_boxes.index(high)]
                        gap = (high[1] - trect[1]) + depth \
                            - (high[1] - ev.y2.value())
                        if gap > 0:
                            out.append(('v', eid, m_id, gap))
                    elif ev.y.value() >= trect[3] - _STRIKE_EPS:
                        m_id = member_ids[member_boxes.index(low)]
                        gap = (trect[3] - low[3]) + depth \
                            - (ev.y.value() - low[3])
                        if gap > 0:
                            out.append(('v', m_id, eid, gap))

        # Wall strikes: the strip crossing the padded boundary of the
        # container shared by both endpoints (internal edges only --
        # exit-edge wall crossings are router work).
        c_id = next((a for a, b in zip(src_chain[1:], tgt_chain[1:])
                     if a == b), None)
        if c_id is not None and c_id in vars_by_id:
            cv = vars_by_id[c_id]
            cx2 = cv.x.value() + cv.w.value()
            if not lg.rotated and strip[1] < cv.y.value() + CONTAINER_PAD_TOP:
                need = CONTAINER_PAD_TOP + (vs.y.value() - strip[1])
                out.append(("wall-top", c_id, es, need))
            elif lg.rotated and strip[2] > cx2 - CONTAINER_PAD:
                need = CONTAINER_PAD + (strip[2] - (vs.x.value() + vs.w.value()))
                out.append(("wall-right", c_id, es, need))
    return out


def _apply_label_contract(
    solver: Solver,
    diagram: DiagramView,
    selected: list[Node],
    mat_edges: list,
    vars_by_id: dict[str, _NodeVars],
) -> None:
    """Two-phase label contract: strike avoidance (ADR-002).

    Phase one (the declared constraints) has already been solved. This
    phase measures the along-path geometry of every labelled edge and,
    for each reservation _measure_label_reservations reports (word
    fit, node strike, wall strike), adds a strong-priority constraint,
    then re-solves. Weak stays pin the phase-one solution as the
    reference point, so only measured shortfalls move anything — views
    without shortfalls are untouched.

    Required constraints always outrank the reservations: an authored
    arrangement that cannot spare the clearance keeps the struck label
    rather than erroring. The bounded iteration lets a reservation
    that squeezes a neighbour trigger that neighbour's own
    reservation.
    """
    seen: set[int] = set()
    for v in vars_by_id.values():
        if id(v) in seen:
            continue
        seen.add(id(v))
        solver.addConstraint((v.x == v.x.value()) | "weak")
        solver.addConstraint((v.y == v.y.value()) | "weak")
        solver.addConstraint((v.w == v.w.value()) | "weak")
        solver.addConstraint((v.h == v.h.value()) | "weak")

    reserved: dict[tuple[str, str, str], float] = {}
    for _ in range(3):
        shortfalls = _measure_label_reservations(
            diagram, selected, mat_edges, vars_by_id)
        added = False
        for axis, a_id, b_id, gap in shortfalls:
            key = (axis, a_id, b_id)
            if gap <= reserved.get(key, 0.0):
                continue
            reserved[key] = gap
            added = True
            va, vb = vars_by_id[a_id], vars_by_id[b_id]
            if axis == "h":
                solver.addConstraint((va.x2 + gap <= vb.x) | "strong")
            elif axis == "v":
                solver.addConstraint((va.y2 + gap <= vb.y) | "strong")
            elif axis == "wall-top":
                # The strip reaches above the container's top pad:
                # grow the container (or push the child down).
                solver.addConstraint((va.y + gap <= vb.y) | "strong")
            elif axis == "wall-right":
                # The strip reaches past the container's right pad:
                # grow the container around the child.
                solver.addConstraint((vb.x2 + gap <= va.x2) | "strong")
        if not added:
            return
        solver.updateVariables()


# ---------------------------------------------------------------------------
# User-declared constraints
# ---------------------------------------------------------------------------

def _add_user_constraints(
    solver: Solver,
    constraints: list,
    vars_by_id: dict[str, _NodeVars],
    view_name: str,
    model: Model | None = None,
    refine: bool = False,
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
                    lg = _label_min_gap(edge.label)
                    if lg > h_label_gaps.get(pair, 0):
                        h_label_gaps[pair] = lg
                if pair in v_pairs:
                    lg = _label_min_gap(edge.label)
                    if lg > v_label_gaps.get(pair, 0):
                        v_label_gaps[pair] = lg

    for c in constraints:
        try:
            _add_one_constraint(solver, c, vars_by_id, h_label_gaps,
                                v_label_gaps, refine=refine)
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
    refine: bool = False,
) -> None:
    s = vars_by_id[c.subject]
    # Refinement mode (ADR-007): synthesized terms arrive at "medium";
    # declared arrangement is required. kiwi yields the medium term
    # where a required declaration disagrees with the synthesized base.
    st = c.strength or "required"
    # The declared adjacency pull (the pair's gap equality) is part of
    # the author's word: at weak it loses to synthesized medium terms
    # coupled through align-* chains, and a declared 98px gap silently
    # inflates to the synthesized corridor budget (measured: the
    # strike-avoidance contract then predicts on the wrong geometry).
    # In refinement mode it holds at strong — still below the required
    # declarations and the label contract's reservations.
    pull = "strong" if (refine and not c.strength) else "weak"
    user_gap = c.gap if c.gap else _GAP_DEFAULT
    pair = frozenset([c.subject, c.object]) if hasattr(c, "object") and c.object else None
    h_min = (h_label_gaps or {}).get(pair, 0) if pair else 0
    v_min = (v_label_gaps or {}).get(pair, 0) if pair else 0

    kind = c.kind

    # Cardinal constraints: required inequality (ordering) PLUS a weak
    # equality pulling the pair to the declared gap — adjacency by
    # default (the Scrabble grid rule, review round 4). A pure
    # inequality lets a free node drift arbitrarily far from its
    # anchor (relation_rec sat 475px from endpoint_rec); a required
    # equality over-determines fan members that also carry their own
    # cardinals (kiwi raises). The weak pull holds the authored gap
    # unless a stronger constraint (label reservations, fan planes)
    # needs the room.
    if kind == "left-of":
        o = vars_by_id[c.object]
        gap = max(user_gap, h_min)
        solver.addConstraint((s.x2 + gap <= o.x) | st)
        solver.addConstraint(((o.x - s.x2) == gap) | pull)

    elif kind == "right-of":
        o = vars_by_id[c.object]
        gap = max(user_gap, h_min)
        solver.addConstraint((s.x >= o.x2 + gap) | st)
        solver.addConstraint(((s.x - o.x2) == gap) | pull)

    elif kind == "above":
        o = vars_by_id[c.object]
        gap = max(user_gap, v_min)
        solver.addConstraint((s.y2 + gap <= o.y) | st)
        solver.addConstraint(((o.y - s.y2) == gap) | pull)

    elif kind == "below":
        o = vars_by_id[c.object]
        gap = max(user_gap, v_min)
        solver.addConstraint((s.y >= o.y2 + gap) | st)
        solver.addConstraint(((s.y - o.y2) == gap) | pull)

    elif kind == "align-left":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x == o.x) | st)

    elif kind == "align-right":
        o = vars_by_id[c.object]
        solver.addConstraint((s.x2 == o.x2) | st)

    elif kind == "align-top":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y == o.y) | st)

    elif kind == "align-bottom":
        o = vars_by_id[c.object]
        solver.addConstraint((s.y2 == o.y2) | st)

    elif kind == "align-middle":
        o = vars_by_id[c.object]
        solver.addConstraint((s.cy == o.cy) | st)

    elif kind == "align-centre":
        o = vars_by_id[c.object]
        solver.addConstraint((s.cx == o.cx) | st)

    elif kind == "same-width":
        o = vars_by_id[c.object]
        solver.addConstraint((s.w == o.w) | st)

    elif kind == "same-height":
        o = vars_by_id[c.object]
        solver.addConstraint((s.h == o.h) | st)

    elif kind == "same-size":
        o = vars_by_id[c.object]
        solver.addConstraint((s.w == o.w) | st)
        solver.addConstraint((s.h == o.h) | st)

    elif kind == "min-width":
        solver.addConstraint((s.w >= c.gap) | st)

    elif kind == "min-height":
        solver.addConstraint((s.h >= c.gap) | st)

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
                lg = _label_min_gap(edge.label)
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
    constraints: list | None = None,
) -> SolvedLayout:
    solved_nodes = [
        _build_solved_node(node, vars_by_id, model, select)
        for node in nodes
    ]

    # Compute overall bounding box; translate to the origin — the
    # typed hub planes fan spokes into negative y (bands above the
    # origin-anchored spine row), and the canvas is not a place for
    # negative coordinates.
    if solved_nodes:
        min_x = min(n.rect.x for n in solved_nodes)
        min_y = min(n.rect.y for n in solved_nodes)
        if min_x > 0 or min_y > 0:
            dx, dy = -min_x, -min_y
            solved_nodes = [
                _dc_replace(n, rect=Rect(n.rect.x + dx, n.rect.y + dy,
                                         n.rect.w, n.rect.h))
                for n in solved_nodes
            ]
            min_x = min(n.rect.x for n in solved_nodes)
            min_y = min(n.rect.y for n in solved_nodes)
        max_x = max(n.rect.x2 for n in solved_nodes)
        max_y = max(n.rect.y2 for n in solved_nodes)
        bounds = Rect(min_x, min_y, max_x - min_x, max_y - min_y)
    else:
        bounds = Rect(0, 0, 0, 0)

    # Declared fan faces: for each materialized edge under a
    # FanConstraint, the (source_face, target_face) the fan's direction
    # declares — "above" means the anchor's arrows leave north and
    # arrive on the members' south faces, whatever the fan's spread
    # does to the centre-to-centre geometry. The router honours these
    # over its geometric class (measured: a wide uniform fan above
    # misread as inter-column flow and the arrows left west/east).
    fan_faces: dict[tuple[str, str], tuple[str, str]] = {}
    _FACE_OF = {"above": ("top", "bottom"), "below": ("bottom", "top"),
                "left-of": ("left", "right"), "right-of": ("right", "left")}
    for c in constraints or []:
        if not isinstance(c, FanConstraint):
            continue
        anchor_face, member_face = _FACE_OF[c.direction]
        for m in c.members:
            fan_faces[(c.anchor, m)] = (anchor_face, member_face)
            fan_faces[(m, c.anchor)] = (member_face, anchor_face)

    return SolvedLayout(nodes=solved_nodes, bounds=bounds,
                        fan_faces=fan_faces)


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

"""ggarch semantic validator.

Validates a parsed GgarchFile against the model-completeness rules:
- Every edge endpoint must be a declared node.
- Every behaviour participant must be a declared node.
- Every behaviour step must reference a declared edge (source → target pair).
- Every view must reference a declared model.
- Every node in a view's select must be a declared node in its model.
- Every behaviour in a sequence view's select must be declared in its model.

Constraint targets in positions blocks are also checked.
"""
from __future__ import annotations

from ggarch.errors import ValidationError
from ggarch.model import (
    Block,
    ARROWHEAD_VALUES,
    BUILTIN_EDGE_TYPES,
    Constraint,
    FanConstraint,
    DiagramView,
    GgarchFile,
    Model,
    SelectClause,
    SequenceView,
    StateView,
    Step,
)


def validate(f: GgarchFile, *, check_orphans: bool = False,
             check_labels: bool = False) -> None:
    """Validate f in place. Raises ValidationError on the first problem
    found.

    check_orphans: the everything-connects law (reviewer round 24, V4)
    binds product views — it is enforced by `ggarch check` (the docs
    gate) and by audit-geometry.py --gate. Default off: the engine
    test suite builds geometry probes whose edge-less nodes are the
    point of the fixture, and adding edges to them would break the
    measurements they assert.

    check_labels: the arrow-label intelligibility law (reviewer round
    24, V2 — 'every arrow should have a label unless deliberately
    removed to avoid overwhelm'): a drawn edge without a label is an
    error; a view that declares `labels: hidden` is the sanctioned
    exception (the model keeps the labels, the view mutes them).
    Sequence steps: the same rule over the behaviour's arrows. Same
    enforcement points as check_orphans; same default-off rationale."""
    for model in f.models:
        _validate_model(model)
    for diagram in f.diagrams:
        _validate_diagram_view(diagram, f,
                               check_orphans=check_orphans,
                               check_labels=check_labels)
    for seq in f.sequences:
        _validate_sequence_view(seq, f, check_labels=check_labels)
    for state in f.states:
        _validate_state_view(state, f)


# ---------------------------------------------------------------------------
# Model validation
# ---------------------------------------------------------------------------


def _validate_node_fields(node, model_name: str) -> None:
    """Check field ids are unique within the node; recurse into children."""
    seen: set[str] = set()
    for f in node.fields:
        if f.id in seen:
            raise ValidationError(
                f"model {model_name!r}, node {node.id!r}: "
                f"duplicate field id {f.id!r}",
            )
        seen.add(f.id)
    for child in node.children:
        _validate_node_fields(child, model_name)


def _collect_field_ids(node, out: dict[str, set[str]]) -> None:
    """Populate out[node_id] = {field_id, ...} for node and all descendants."""
    out[node.id] = {f.id for f in node.fields}
    for child in node.children:
        _collect_field_ids(child, out)

def _fk_complete_nodes(model: Model) -> list:
    """Nodes whose fields carry real FK semantics: record-type nodes with
    declared fields. On class nodes `fk:` renders as the UML '#'
    (protected) marker — not a foreign key — so class fields stay out of
    scope."""
    out = []
    for node in model.nodes:
        _fk_complete_walk(node, out)
    return out


def _fk_complete_walk(node, out: list) -> None:
    if node.type == "record" and node.fields:
        out.append(node)
    for child in node.children:
        _fk_complete_walk(child, out)


def _validate_fk_edges(model: Model) -> None:
    """FK-completeness (record nodes): the FK field is the storage-level
    truth of a data association — where the pointer lives — so the
    declared data edges must mirror it exactly:

    1. a field-qualified edge endpoint on an fk: field must have type
       data (a non-data edge is not a pointer);
    2. every fk: field originates exactly one data edge (the pointer is
       drawn; a half-drawn junction hides truth);
    3. every data edge originating at a record's field starts from an
       fk: field (no phantom pointers).
    """
    nodes = _fk_complete_nodes(model)
    if not nodes:
        return

    fk_fields: dict[str, set[str]] = {}
    field_owner: dict[str, str] = {}
    for node in nodes:
        fk_fields[node.id] = {f.id for f in node.fields if f.fk}
        for f in node.fields:
            field_owner[(node.id, f.id)] = node.id

    def _edge_src(e) -> tuple[str, str] | None:
        """The (node, field) a data edge would start at, or None. The
        parser stores field-qualified endpoints split (source +
        source_field); a dotted node id is tolerated for robustness."""
        if e.source_field:
            return e.source, e.source_field
        node_id, _, field = e.source.partition(".")
        return (node_id, field) if field else None

    edges = model.edges
    for e in edges:
        src = _edge_src(e)
        if src and src in field_owner and e.type != "data":
            raise ValidationError(
                f"model {model.name!r}: edge {e.source}->{e.target} "
                f"starts at field {e.source!r} but has type {e.type!r}; "
                f"an edge from a foreign key column is a pointer "
                f"(type: data)",
            )

    origin_count: dict[tuple[str, str], int] = {}
    for e in edges:
        src = _edge_src(e)
        if not src or src not in field_owner:
            continue
        node_id, field = src
        origin_count[(node_id, field)] = origin_count.get((node_id, field), 0) + 1
        if field not in fk_fields.get(node_id, set()):
            raise ValidationError(
                f"model {model.name!r}: data edge {e.source}->{e.target} "
                f"starts at field {e.source!r} which is not marked fk: "
                f"— a data edge from a record field must start at the "
                f"foreign key column that stores the pointer",
                hint="mark the column fk: true, or re-anchor the edge at "
                     "the node (unqualified) if no column stores it",
            )

    for node in nodes:
        for f in node.fields:
            if f.id not in fk_fields[node.id]:
                continue
            targets = [e.target for e in edges
                       if _edge_src(e) == (node.id, f.id)]
            n = len(targets)
            if n == 0:
                raise ValidationError(
                    f"model {model.name!r}: fk field "
                    f"{node.id}.{f.id!r} originates 0 data edges; "
                    f"exactly 1 expected — the FK column is the storage "
                    f"truth of the association and must be drawn exactly "
                    f"once (a missing edge hides the pointer)",
                )
            # One pointer per target: a DDL may legitimately declare one
            # column referencing TWO tables (measured:
            # application_remote_consumer.offer_connection_uuid, dual
            # reference sanctioned in the DDL comment) — each pointer
            # drawn once. A repeated target is a double-drawn arrow.
            dupes = {t for t in targets if targets.count(t) > 1}
            if dupes:
                raise ValidationError(
                    f"model {model.name!r}: fk field "
                    f"{node.id}.{f.id!r} draws {n} data edges to the "
                    f"same target {sorted(dupes)[0]!r}; each pointer is "
                    f"drawn exactly once (distinct targets may each "
                    f"carry an edge — a DDL-declared dual reference)",
                )


def _validate_records(node, model: Model) -> None:
    """A records: target must be a declared record-type node."""
    if node.records:
        target = model.find_node(node.records)
        if target is None:
            raise ValidationError(
                f"model {model.name!r}: records target {node.records!r} "
                f"of node {node.id!r} is not declared",
            )
        if target.type != "record":
            raise ValidationError(
                f"model {model.name!r}: records target {node.records!r} "
                f"of node {node.id!r} is not a record-type node "
                f"(type {target.type!r})",
            )
    for child in node.children:
        _validate_records(child, model)

def _validate_model(model: Model) -> None:
    node_ids  = model.all_node_ids()
    valid_ids = model.all_valid_ids()
    abs_map   = model.abstractions_map()

    # Check field id uniqueness within each node.
    for node in model.nodes:
        _validate_node_fields(node, model.name)

    # Check environments reference declared nodes.
    for env in model.environments:
        for nid in env.present:
            if nid not in node_ids:
                raise ValidationError(
                    f"model {model.name!r}, environment {env.name!r}: "
                    f"present node {nid!r} is not declared",
                )
        for abstract_id, concrete_id in env.abstracts.items():
            if concrete_id not in node_ids:
                raise ValidationError(
                    f"model {model.name!r}, environment {env.name!r}: "
                    f"concrete node {concrete_id!r} for abstract {abstract_id!r} is not declared",
                )

    # Check records: targets — must be declared record-type nodes.
    for node in model.nodes:
        _validate_records(node, model)

    # Check collective: targets — the base kind must exist in the model
    # (SPEC "collective nodes": the abstraction references the kind it
    # abstracts over; a typo would silently draw a meaningless stack).
    def _validate_collective(node, model):
        base = str(node.properties.get("collective", "") or "")
        if base and model.find_node(base) is None:
            raise ValidationError(
                f"model {model.name!r}: node {node.id} declares "
                f"collective: {base!r} but no node with that id exists",
                hint="the collective's value is the base kind's node id "
                     "(e.g. clouds [collective: cloud])")
        for child in node.children:
            _validate_collective(child, model)

    for node in model.nodes:
        _validate_collective(node, model)

    # Build field index: node_id -> set of field ids (for qualified endpoint checks).
    field_ids: dict[str, set[str]] = {}
    for node in model.nodes:
        _collect_field_ids(node, field_ids)

    # Non-built-in edge types are custom types: they must be styled in the
    # model's style block (edge <name> { ... }) or they would silently
    # fall back to default styling -- and a typo would go unnoticed.
    styled_edge_types = set(model.style.edge_rules) | set(model.style.dark_edge_rules)
    for edge in model.edges:
        if (edge.type not in BUILTIN_EDGE_TYPES
                and edge.type not in styled_edge_types):
            raise ValidationError(
                f"model {model.name!r}: edge {edge.source}->{edge.target} "
                f"has unknown type {edge.type!r}",
                hint="use a built-in type (api, stream, event, data, control, "
                     "ipc) or declare edge " + edge.type + " { ... } in the "
                     "style block",
            )

    # ADR-004: the arrowhead channel is a closed enum (filled | open |
    # none) — the preattentive limit is enforced by construction.
    for rules in (model.style.edge_rules, model.style.dark_edge_rules):
        for type_name, rule in rules.items():
            if rule.arrowhead and rule.arrowhead not in ARROWHEAD_VALUES:
                raise ValidationError(
                    f"model {model.name!r}: edge {type_name!r} has unknown "
                    f"arrowhead {rule.arrowhead!r}",
                    hint="arrowhead is one of: filled, open, none "
                         "(ADR-004 — the commitment channel)",
                )

    # Check pairing values -- the only supported expansion semantic
    for edge in model.edges:
        pairing = edge.properties.get("pairing", "")
        if pairing not in ("", "mesh"):
            raise ValidationError(
                f"model {model.name!r}: edge {edge.source}->{edge.target}: "
                f"unknown pairing {pairing!r}; expected mesh",
            )
        for ep_node, ep_field, role in (
            (edge.source, edge.source_field, "source"),
            (edge.target, edge.target_field, "target"),
        ):
            if ep_node not in valid_ids:
                raise ValidationError(
                    f"model {model.name!r}: edge {role} {ep_node!r} is not a declared node",
                    hint=f"declared nodes: {sorted(node_ids)}",
                )
            if ep_field:
                node_fields = field_ids.get(ep_node, set())
                if ep_field not in node_fields:
                    raise ValidationError(
                        f"model {model.name!r}: edge {role} {ep_node!r}.{ep_field!r} "
                        f"references undeclared field",
                        hint=f"declared fields on {ep_node!r}: {sorted(node_fields)}",
                    )

    # FK completeness on record nodes: declared data edges must mirror
    # where the pointers live (every fk: column drawn exactly once; no
    # data edges from non-fk fields). Runs after endpoint validation so
    # undeclared fields get the precise error first.
    _validate_fk_edges(model)

    # Build resolved edge pairs: also expand abstract ids to their concrete ids.
    edge_pairs: set[tuple[str, str]] = set()
    for e in model.edges:
        src = abs_map.get(e.source, e.source)
        tgt = abs_map.get(e.target, e.target)
        edge_pairs.add((src, tgt))
        edge_pairs.add((tgt, src))
        # Also keep the abstract form so steps using abstract ids match.
        edge_pairs.add((e.source, e.target))
        edge_pairs.add((e.target, e.source))

    # Check behaviour participants (may use abstract ids if abstracted by a concrete node).
    for behaviour in model.behaviours:
        participants = behaviour.all_participants()
        for pid in participants:
            if pid not in valid_ids:
                raise ValidationError(
                    f"model {model.name!r}, behaviour {behaviour.name!r}: "
                    f"participant {pid!r} is not a declared node "
                    f"(and not covered by any abstracts: relationship)",
                    hint=f"declared nodes: {sorted(node_ids)}",
                )
        _validate_steps(behaviour.steps, edge_pairs, model.name, behaviour.name)


def _validate_steps(steps, edge_pairs, model_name, behaviour_name):
    for item in steps:
        if isinstance(item, Step):
            if item.source != item.target:
                if (item.source, item.target) not in edge_pairs:
                    raise ValidationError(
                        f"model {model_name!r}, behaviour {behaviour_name!r}: "
                        f"step {item.source!r} -> {item.target!r} does not "
                        f"correspond to any declared edge (checked both directions)",
                        hint="add the edge to the model's edges block, or check for typos",
                    )
            _validate_steps(item.body, edge_pairs, model_name, behaviour_name)
        elif isinstance(item, Block):
            _validate_steps(item.body, edge_pairs, model_name, behaviour_name)
            for _, branch in item.else_branches:
                _validate_steps(branch, edge_pairs, model_name, behaviour_name)


# ---------------------------------------------------------------------------
# View validation
# ---------------------------------------------------------------------------

def _resolve_model(view_name: str, model_name: str, f: GgarchFile) -> Model:
    model = f.get_model(model_name)
    if model is None:
        declared = [m.name for m in f.models]
        raise ValidationError(
            f"view {view_name!r} references model {model_name!r} which is not declared",
            hint=f"declared models: {declared}",
        )
    return model


def _validate_select(select: SelectClause, model: Model, view_name: str) -> None:
    # Include abstract ids valid for the specified environment (if any).
    if select.environment:
        valid_ids = model.all_valid_ids_for_env(select.environment)
    else:
        valid_ids = model.all_valid_ids()
    node_ids = model.all_node_ids()

    for nid in select.node_ids:
        if nid not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: selected node {nid!r} is not declared in model {model.name!r}",
                hint=f"declared nodes: {sorted(node_ids)}",
            )

    for nid in select.collapse:
        if nid not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: collapse target {nid!r} is not declared in model {model.name!r}",
            )

    for nid in select.expand:
        if nid not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: expand target {nid!r} is not declared in model {model.name!r}",
            )

    for spec in select.instances:
        if spec.type_id and spec.type_id not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: instance type {spec.type_id!r} is not declared in model {model.name!r}",
            )

    if select.routing and select.routing != "orthogonal":
        raise ValidationError(
            f"view {view_name!r}: unknown routing mode {select.routing!r}",
            hint="the only declared routing mode is 'orthogonal' "
                 "(axis-aligned legs; snap-to-grid)",
        )
    if select.sizing and select.sizing not in ("uniform", "natural"):
        raise ValidationError(
            f"view {view_name!r}: unknown sizing mode {select.sizing!r}",
            hint="uniform is the default; the opt-out is 'natural'",
        )
    for es, et, _ty in select.except_pairs:
        for nid in (es, et):
            if nid not in valid_ids:
                raise ValidationError(
                    f"view {view_name!r}: except edge references unknown "
                    f"node {nid!r}",
                )

    if select.behaviour:
        b = model.find_behaviour(select.behaviour)
        if b is None:
            declared = [b.name for b in model.behaviours]
            raise ValidationError(
                f"view {view_name!r}: behaviour {select.behaviour!r} is not declared in model {model.name!r}",
                hint=f"declared behaviours: {declared}",
            )
        for pid in select.participants:
            if pid not in valid_ids:
                raise ValidationError(
                    f"view {view_name!r}: participant filter {pid!r} is not declared in model {model.name!r}",
                )


def _validate_constraints(
    constraints: list[Constraint | FanConstraint],
    model: Model,
    view_name: str,
    extra_ids: set[str] | None = None,
) -> None:
    valid_ids = model.all_node_ids() | (extra_ids or set())
    for c in constraints:
        if isinstance(c, FanConstraint):
            for m in c.members:
                if m not in valid_ids:
                    raise ValidationError(
                        f"view {view_name!r}: fan member {m!r} is not declared in model {model.name!r}",
                    )
            if c.anchor not in valid_ids:
                raise ValidationError(
                    f"view {view_name!r}: fan anchor {c.anchor!r} is not declared in model {model.name!r}",
                )
        else:
            if c.subject not in valid_ids:
                raise ValidationError(
                    f"view {view_name!r}: constraint subject {c.subject!r} is not declared in model {model.name!r}",
                )
            if c.object and c.object not in valid_ids:
                raise ValidationError(
                    f"view {view_name!r}: constraint object {c.object!r} is not declared in model {model.name!r}",
                )


def _validate_diagram_view(diagram: DiagramView, f: GgarchFile,
                           *, check_orphans: bool = False,
                           check_labels: bool = False) -> None:
    model = _resolve_model(diagram.name, diagram.model_name, f)
    _validate_select(diagram.select, model, diagram.name)
    if check_orphans:
        _validate_orphans(diagram, model)
    if check_labels:
        _validate_labels(diagram, model)
    instance_ids = {spec.instance_id for spec in diagram.select.instances}
    # Include abstract ids resolvable in the environment as valid constraint targets.
    env_ids: set[str] = set()
    if diagram.select.environment:
        env_ids = set(model.environment_abstractions_map(diagram.select.environment).keys())
    _validate_constraints(diagram.constraints, model, diagram.name,
                          extra_ids=instance_ids | env_ids)
    _validate_emphasize(diagram, model)


def _validate_emphasize(diagram: DiagramView, model: Model) -> None:
    """The salience channel's truth rule (SPEC 'Design item: the
    salience channel'): a declared path is a route CLAIM — consecutive
    members must be connected by an edge the view actually draws
    (materialized through instances, curated by except, type-filtered).
    A path through non-adjacent nodes is a lie, like every other lie
    the validator catches. Direction-agnostic: emphasis highlights the
    connection, not an arrow direction."""
    from ggarch.instances import materialize_instances

    if not diagram.emphasize_path and not diagram.emphasize_nodes:
        return
    view_name = diagram.name
    nodes, edges = materialize_instances(diagram.select, model)
    sel_ids = {n.id for n in nodes}
    except_pairs = {(s, t, ty) for s, t, ty in diagram.select.except_pairs}
    types = set(diagram.select.edge_types) if diagram.select.edge_types else None

    def drawn(a: str, b: str) -> bool:
        return any(
            {e.source, e.target} == {a, b}
            and e.source != e.target
            and (types is None or e.type in types)
            and not any(es == e.source and et == e.target
                        and (ty == "" or ty == e.type)
                        for es, et, ty in except_pairs)
            for e in edges)

    for nid in diagram.emphasize_nodes + diagram.emphasize_path:
        if nid not in sel_ids:
            raise ValidationError(
                f"view {view_name!r}: emphasized node {nid!r} is not "
                f"selected by the view (unknown, unexpanded, or "
                f"unselected id)",
            )
    for a, b in zip(diagram.emphasize_path, diagram.emphasize_path[1:]):
        if a == b:
            raise ValidationError(
                f"view {view_name!r}: emphasize path repeats {a!r}",
            )
        if not drawn(a, b):
            raise ValidationError(
                f"view {view_name!r}: emphasize path claims "
                f"{a!r} -> {b!r}, but the view draws no edge between "
                f"them (check the select, except, and edge-type "
                f"filters; instance ids, not type ids)",
                hint="a path is a route claim: consecutive members "
                     "must be connected by a drawn edge",
            )
    if len(set(diagram.emphasize_path)) != len(diagram.emphasize_path):
        raise ValidationError(
            f"view {view_name!r}: emphasize path visits a node twice",
        )


def _resolve_drawn(diagram: DiagramView, model: Model):
    """The view's drawn node/edge set, resolved the way the solver
    draws it: except pairs and the edge-type filter apply to MODEL
    edges BEFORE instance stamping (a type-id except — client -> cloud
    — must also suppress its stamped copies), then instances stamp,
    then the selection resolves. An edge draws only when BOTH
    endpoints resolve into the selected set (the deepest top ancestor
    on each side) and the two tops differ — self-edges and same-top
    internal edges are never drawn.

    Returns (nodes, [(edge, top_source, top_target), ...])."""
    from dataclasses import replace as _dc_replace

    from ggarch.instances import materialize_instances
    from ggarch.solver import _selected_nodes

    except_pairs = {(s, t, ty) for s, t, ty in diagram.select.except_pairs}
    if except_pairs:
        model = _dc_replace(model, edges=[
            e for e in model.edges
            if not any(e.source == es and e.target == et
                       and (ty == "" or ty == e.type)
                       for es, et, ty in except_pairs)])
    mat_nodes, edges = materialize_instances(diagram.select, model)
    nodes = _selected_nodes(diagram.select, model, mat_nodes)
    types = (set(diagram.select.edge_types)
             if diagram.select.edge_types else None)

    top_set = {n.id for n in nodes}
    parent: dict[str, str] = {}

    def _walk(n) -> None:
        for c in n.children:
            parent[c.id] = n.id
            _walk(c)

    for n in nodes:
        _walk(n)

    def _top(nid: str) -> str | None:
        chain = [nid]
        while nid in parent:
            nid = parent[nid]
            chain.append(nid)
        return chain[-1] if chain[-1] in top_set else None

    drawn = []
    for e in edges:
        if e.source == e.target:
            continue
        if types is not None and e.type not in types:
            continue
        ts, tt = _top(e.source), _top(e.target)
        if ts is None or tt is None or ts == tt:
            continue
        drawn.append((e, ts, tt))
    return nodes, drawn


def _validate_orphans(diagram: DiagramView, model: Model) -> None:
    """Everything connects (reviewer round 24, V4): a selected node
    whose whole subtree no drawn edge touches is an error — 'a diagram
    means everything is connected'. Tree-resolved, like the measured
    orphan scan: containers count as connected through their children
    (an edge touching any subtree member touches the subtree's top).
    The view's own curation applies: the edge-type filter and except
    pairs decide which edges count, and edges the solver does not draw
    (self-edges, same-top internal edges) do not count. The ADR-005
    records bridge (records: shown) is a synthetic drawn edge and
    connects both of its endpoints. Diagram views only: sequence
    lifelines and state-machine states are edge-connected by
    construction (every step is a declared edge)."""
    nodes, drawn = _resolve_drawn(diagram, model)

    top_set = {n.id for n in nodes}
    parent: dict[str, str] = {}

    def _walk(n) -> None:
        for c in n.children:
            parent[c.id] = n.id
            _walk(c)

    for n in nodes:
        _walk(n)

    def _top(nid: str) -> str | None:
        chain = [nid]
        while nid in parent:
            nid = parent[nid]
            chain.append(nid)
        return chain[-1] if chain[-1] in top_set else None

    touched: set[str] = set()
    for _e, ts, tt in drawn:
        touched.add(ts)
        touched.add(tt)

    if getattr(diagram.select, "show_records", False):
        # ADR-005: one synthetic bridge per recorded node whose record
        # node is present — the bridge connects both endpoints.
        all_ids: set[str] = set()
        for n in nodes:
            all_ids.update(_walk_ids(n))
        for n in nodes:
            stack = [n]
            while stack:
                cur = stack.pop()
                stack.extend(cur.children)
                rec = cur.records
                if not rec or rec == cur.id or rec not in all_ids:
                    continue
                touched.add(cur.id)
                rec_top = _top(rec)
                if rec_top:
                    touched.add(rec_top)

    for n in nodes:
        if n.id not in touched:
            raise ValidationError(
                f"view {diagram.name!r}: node {n.id!r} (with its whole "
                f"subtree) has no edges in this view — a diagram means "
                f"everything is connected",
                hint="declare the edge that involves the node, remove "
                     "it from the select, or drop the view if the node "
                     "belongs to another story",
            )


def _walk_ids(node) -> list[str]:
    out = [node.id]
    for c in node.children:
        out.extend(_walk_ids(c))
    return out


def _validate_labels(diagram: DiagramView, model: Model) -> None:
    """Arrow-label intelligibility (reviewer round 24, V2): every
    drawn edge carries a label — 'every arrow should have a label
    unless deliberately removed to avoid overwhelm'. The sanctioned
    exception is `labels: hidden` (the model keeps the labels; the
    view mutes them before routing), plus the tutorial reveal views
    that use it. Runs on the same drawn-edge resolution as the orphan
    check."""
    if getattr(diagram.select, "hide_labels", False):
        return
    _nodes, drawn = _resolve_drawn(diagram, model)
    for e, _ts, _tt in drawn:
        if not e.label:
            raise ValidationError(
                f"view {diagram.name!r}: edge {e.source}->{e.target} "
                f"({e.type!r}) draws with no label — every arrow "
                f"carries a label unless the view deliberately mutes "
                f"them",
                hint="label the edge in the model (one verb, the "
                     "coherent-sentence rule), or declare "
                     "`labels: hidden` on the view if it is a "
                     "deliberately muted view",
            )


def _validate_sequence_view(seq: SequenceView, f: GgarchFile,
                            *, check_labels: bool = False) -> None:
    model = _resolve_model(seq.name, seq.model_name, f)
    _validate_select(seq.select, model, seq.name)
    if check_labels:
        behaviour = model.find_behaviour(seq.select.behaviour)
        if behaviour is not None and not seq.select.participants:
            _validate_step_labels(behaviour.steps, seq.name)


def _validate_step_labels(steps: list, view_name: str) -> None:
    """V2 over sequences: every message arrow prints a label (the
    renderer draws bare arrows for label-less steps). Block branches
    are walked so alt/loop bodies are covered."""
    for item in steps:
        if isinstance(item, Step):
            if not item.label:
                raise ValidationError(
                    f"view {view_name!r}: behaviour step "
                    f"{item.source} -> {item.target} "
                    f"({item.kind.value}) has no label — every "
                    f"sequence arrow carries one",
                    hint="label the step with what crosses the arrow "
                         "(the call's subject, the returned thing)",
                )
        elif isinstance(item, Block):
            _validate_step_labels(item.body, view_name)
            for _, branch in item.else_branches:
                _validate_step_labels(branch, view_name)


def _validate_state_view(state: StateView, f: GgarchFile) -> None:
    model = _resolve_model(state.name, state.model_name, f)
    _validate_select(state.select, model, state.name)

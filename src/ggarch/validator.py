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
    Constraint,
    DiagramView,
    GgarchFile,
    Model,
    SelectClause,
    SequenceView,
    Step,
)


def validate(f: GgarchFile) -> None:
    """Validate f in place. Raises ValidationError on the first problem found."""
    for model in f.models:
        _validate_model(model)
    for diagram in f.diagrams:
        _validate_diagram_view(diagram, f)
    for seq in f.sequences:
        _validate_sequence_view(seq, f)


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

def _validate_model(model: Model) -> None:
    node_ids  = model.all_node_ids()
    valid_ids = model.all_valid_ids()
    abs_map   = model.abstractions_map()

    # Check field id uniqueness within each node.
    for node in model.nodes:
        _validate_node_fields(node, model.name)

    # Build field index: node_id -> set of field ids (for qualified endpoint checks).
    field_ids: dict[str, set[str]] = {}
    for node in model.nodes:
        _collect_field_ids(node, field_ids)

    # Check edge endpoints.
    for edge in model.edges:
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
    valid_ids = model.all_valid_ids()   # includes abstract ids covered by abstracts:
    node_ids  = model.all_node_ids()    # concrete only (for error messages)

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
    constraints: list[Constraint],
    model: Model,
    view_name: str,
    extra_ids: set[str] | None = None,
) -> None:
    valid_ids = model.all_node_ids() | (extra_ids or set())
    for c in constraints:
        if c.subject not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: constraint subject {c.subject!r} is not declared in model {model.name!r}",
            )
        if c.object and c.object not in valid_ids:
            raise ValidationError(
                f"view {view_name!r}: constraint object {c.object!r} is not declared in model {model.name!r}",
            )


def _validate_diagram_view(diagram: DiagramView, f: GgarchFile) -> None:
    model = _resolve_model(diagram.name, diagram.model_name, f)
    _validate_select(diagram.select, model, diagram.name)
    instance_ids = {spec.instance_id for spec in diagram.select.instances}
    _validate_constraints(diagram.constraints, model, diagram.name,
                          extra_ids=instance_ids)


def _validate_sequence_view(seq: SequenceView, f: GgarchFile) -> None:
    model = _resolve_model(seq.name, seq.model_name, f)
    _validate_select(seq.select, model, seq.name)

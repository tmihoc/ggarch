"""ggarch parser.

Transforms a Lark parse tree into a GgarchFile data model.
"""
from __future__ import annotations

import importlib.resources
from pathlib import Path

from lark import Lark, Token, Transformer, v_args

from ggarch.errors import ParseError
from ggarch.model import (
    Annotation,
    AnnotationBadge,
    AnnotationBox,
    AnnotationCallout,
    AnnotationSeparator,
    Behaviour,
    Block,
    Cardinality,
    Constraint,
    DiagramView,
    Edge,
    EdgeType,
    GgarchFile,
    InstanceSpec,
    Lifecycle,
    Model,
    Node,
    NodeField,
    SelectClause,
    SequenceView,
    Step,
    StepKind,
    Style,
    StyleRule,
)


def _load_grammar() -> str:
    try:
        ref = importlib.resources.files("ggarch").joinpath("grammar.lark")
        return ref.read_text(encoding="utf-8")
    except Exception:
        here = Path(__file__).parent
        return (here / "grammar.lark").read_text(encoding="utf-8")


_GRAMMAR = _load_grammar()
_PARSER = Lark(_GRAMMAR, parser="lalr")


def _str(token) -> str:
    s = str(token)
    if s.startswith('"') and s.endswith('"'):
        return s[1:-1]
    return s


def _int(token) -> int:
    return int(token)


def _edge_type(s: str) -> EdgeType:
    try:
        return EdgeType(s)
    except ValueError:
        return EdgeType.CUSTOM


def _lifecycle(s: str) -> Lifecycle:
    try:
        return Lifecycle(s)
    except ValueError:
        raise ParseError(
            f"unknown lifecycle value: {s!r}; expected persistent | init | ephemeral"
        )


def _cardinality(s: str) -> Cardinality | int:
    try:
        return Cardinality(s)
    except ValueError:
        try:
            return int(s)
        except ValueError:
            raise ParseError(f"unknown cardinality value: {s!r}")


def _make_node(
    node_id: str,
    attrs: dict,
    children: list,
    fields: list | None = None,
) -> Node:
    attrs = dict(attrs)  # copy — we pop from it
    label      = attrs.pop("label", node_id)
    node_type  = attrs.pop("type", "default")
    lifecycle  = _lifecycle(attrs.pop("lifecycle", "persistent"))
    raw_card   = attrs.pop("cardinality", None)
    cardinality = _cardinality(raw_card) if raw_card is not None else None
    raw_abs    = attrs.pop("abstracts", "")
    abstracts  = [a.strip() for a in raw_abs.split() if a.strip()] if raw_abs else []
    return Node(
        id=node_id,
        label=label,
        type=node_type,
        lifecycle=lifecycle,
        cardinality=cardinality,
        abstracts=abstracts,
        children=children,
        fields=fields or [],
        attrs=attrs,
    )


@v_args(inline=True)
class _GgarchTransformer(Transformer):

    # ------------------------------------------------------------------
    # Top level
    # ------------------------------------------------------------------

    def start(self, *items) -> GgarchFile:
        f = GgarchFile()
        for item in items:
            if isinstance(item, Model):
                f.models.append(item)
            elif isinstance(item, DiagramView):
                f.diagrams.append(item)
            elif isinstance(item, SequenceView):
                f.sequences.append(item)
        return f

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------

    def model(self, name_token, body) -> Model:
        nodes, edges, behaviours, style = body
        m = Model(name=_str(name_token))
        m.nodes = nodes
        m.edges = edges
        m.behaviours = behaviours
        m.style = style
        return m

    def model_body(self, *items):
        nodes: list[Node] = []
        edges: list[Edge] = []
        behaviours: list[Behaviour] = []
        style = Style()
        for item in items:
            if isinstance(item, list):
                if item and isinstance(item[0], Node):
                    nodes = item
                elif item and isinstance(item[0], Edge):
                    edges = item
                elif item and isinstance(item[0], Behaviour):
                    behaviours = item
            elif isinstance(item, Style):
                style = item
        return nodes, edges, behaviours, style

    def nodes_block(self, *nodes) -> list[Node]:
        return list(nodes)

    def node_with_children(self, id_token, *rest) -> Node:
        # rest is: optional attrs dict, then node_body (tuple of children+fields)
        attrs: dict = {}
        children: list[Node] = []
        fields: list[NodeField] = []
        for item in rest:
            if isinstance(item, dict):
                attrs = item
            elif isinstance(item, tuple) and item and item[0] == "__node_body__":
                children = item[1]
                fields   = item[2]
        return _make_node(_str(id_token), attrs, children, fields)

    def node_body(self, *items):
        children: list[Node] = []
        fields: list[NodeField] = []
        for item in items:
            if isinstance(item, Node):
                children.append(item)
            elif isinstance(item, list) and item and isinstance(item[0], NodeField):
                fields = item
        return ("__node_body__", children, fields)

    def fields_block(self, *items) -> list[NodeField]:
        # items[0] is the FIELDS_KW token — discard it; rest are NodeField
        return [f for f in items if isinstance(f, NodeField)]

    def field_decl(self, id_token, *rest) -> NodeField:
        attrs = rest[0] if rest and isinstance(rest[0], dict) else {}
        attrs = dict(attrs)
        return NodeField(
            id=_str(id_token),
            label=attrs.pop("label", _str(id_token)),
            type=attrs.pop("type", ""),
            pk=attrs.pop("pk", False) in (True, "true", "yes", 1),
            fk=attrs.pop("fk", False) in (True, "true", "yes", 1),
            uk=attrs.pop("uk", False) in (True, "true", "yes", 1),
            nullable=attrs.pop("null", False) in (True, "true", "yes", 1),
        )

    def node_leaf(self, id_token, *rest) -> Node:
        attrs = rest[0] if rest and isinstance(rest[0], dict) else {}
        return _make_node(_str(id_token), attrs, [])

    def attrs_inline(self, *attrs) -> dict:
        result = {}
        for k, v in attrs:
            result[k] = v
        return result

    def attr(self, key, value) -> tuple:
        return _str(key), value

    def attr_string(self, token) -> str:
        return _str(token)

    def attr_id(self, token) -> str:
        return _str(token)

    def attr_int(self, token) -> int:
        return _int(token)

    # ------------------------------------------------------------------
    # Edges
    # ------------------------------------------------------------------

    def edges_block(self, *edges) -> list[Edge]:
        return list(edges)

    def edge(self, src, tgt, *rest) -> Edge:
        attrs = rest[0] if rest and isinstance(rest[0], dict) else {}
        attrs = dict(attrs)
        # src and tgt are tuples from endpoint rules: (node_id, field_id | "")
        src_node, src_field = src
        tgt_node, tgt_field = tgt
        return Edge(
            source=src_node,
            target=tgt_node,
            type=_edge_type(attrs.pop("type", "api")),
            label=attrs.pop("label", ""),
            protocol=attrs.pop("protocol", ""),
            style=attrs.pop("style", ""),
            arrow=attrs.pop("arrow", "forward"),
            source_field=src_field,
            target_field=tgt_field,
        )

    def endpoint_node(self, id_token) -> tuple:
        return (_str(id_token), "")

    def endpoint_field(self, node_token, field_token) -> tuple:
        return (_str(node_token), _str(field_token))

    # ------------------------------------------------------------------
    # Behaviours
    # ------------------------------------------------------------------

    def behaviours_block(self, *behaviours) -> list[Behaviour]:
        return list(behaviours)

    def behaviour(self, name_token, *steps) -> Behaviour:
        return Behaviour(name=_str(name_token), steps=list(steps))

    def bstep(self, item) -> Step | Block:
        # Pass-through alias for all behaviour_step alternatives.
        return item

    def step_line(self, src, tgt, kind_token, *rest) -> Step:
        kind = StepKind(str(kind_token))
        label = _str(rest[0]) if rest and not isinstance(rest[0], dict) else ""
        return Step(kind=kind, source=_str(src), target=_str(tgt), label=label)

    def loop_block(self, label, *steps) -> Block:
        return Block(kind="loop", label=_str(label), body=list(steps))

    def alt_block(self, label, *rest) -> Block:
        steps: list = []
        else_branches: list = []
        for item in rest:
            if isinstance(item, (Step, Block)):
                steps.append(item)
            elif isinstance(item, tuple):
                else_branches.append(item)
        return Block(kind="alt", label=_str(label), body=steps,
                     else_branches=else_branches)

    def else_clause(self, label, *steps) -> tuple:
        return (_str(label), list(steps))

    def par_block(self, *steps) -> Block:
        return Block(kind="par", label="", body=list(steps))

    def opt_block(self, label, *steps) -> Block:
        return Block(kind="opt", label=_str(label), body=list(steps))

    # ------------------------------------------------------------------
    # Style
    # ------------------------------------------------------------------

    def style_block(self, *items) -> Style:
        s = Style()
        for item in items:
            if not isinstance(item, tuple):
                continue
            key, value = item
            if key == "extends":
                s.extends = value
            elif key == "dark":
                s.dark_node_rules.update(value)
            else:
                s.node_rules[key] = value
        return s

    def style_extends(self, id_token) -> tuple:
        return ("extends", _str(id_token))

    def style_type_rule(self, id_token, *rules) -> tuple:
        rule = StyleRule()
        for k, v in rules:
            setattr(rule, k.replace("-", "_"), v)
        return (_str(id_token), rule)

    def style_rule(self, key, value) -> tuple:
        return (_str(key), value)

    def style_dark(self, *items) -> tuple:
        rules = {}
        for k, v in items:
            rules[k] = v
        return ("dark", rules)

    def style_dark_item(self, id_token, *rules) -> tuple:
        rule = StyleRule()
        for k, v in rules:
            setattr(rule, k.replace("-", "_"), v)
        return (_str(id_token), rule)

    # ------------------------------------------------------------------
    # Diagram view
    # ------------------------------------------------------------------

    def diagram(self, name, model_name, body) -> DiagramView:
        select, constraints, annotations = body
        return DiagramView(
            name=_str(name),
            model_name=_str(model_name),
            select=select,
            constraints=constraints,
            annotations=annotations,
        )

    def diagram_body(self, *items):
        select = SelectClause()
        constraints: list[Constraint] = []
        annotations: list[Annotation] = []
        for item in items:
            if isinstance(item, SelectClause):
                select = item
            elif isinstance(item, list):
                if item and isinstance(item[0], Constraint):
                    constraints = item
                elif item and isinstance(item[0], (
                        AnnotationBox, AnnotationCallout,
                        AnnotationSeparator, AnnotationBadge)):
                    annotations = item
        return select, constraints, annotations

    def select_block(self, *items) -> SelectClause:
        s = SelectClause()
        for item in items:
            if not isinstance(item, tuple):
                continue
            key, value = item
            if key == "nodes":        s.node_ids = value
            elif key == "edges":      s.edge_types = value
            elif key == "environment":s.environment = value
            elif key == "collapse":   s.collapse = value
            elif key == "expand":     s.expand = value
            elif key == "instances":  s.instances = value
            elif key == "behaviour":  s.behaviour = value
            elif key == "participants":s.participants = value
        return s

    def select_nodes(self, id_list)        -> tuple: return ("nodes", id_list)
    def select_edges(self, ef_list)        -> tuple: return ("edges", ef_list)
    def select_environment(self, id_token) -> tuple: return ("environment", _str(id_token))
    def select_collapse(self, id_list)     -> tuple: return ("collapse", id_list)
    def select_expand(self, id_list)       -> tuple: return ("expand", id_list)
    def select_behaviour(self, s_token)    -> tuple: return ("behaviour", _str(s_token))
    def select_participants(self, id_list) -> tuple: return ("participants", id_list)

    def select_instances(self, type_id, *specs) -> tuple:
        return ("instances", list(specs))

    def instance_spec(self, id_token, label_token) -> InstanceSpec:
        return InstanceSpec(type_id="", instance_id=_str(id_token),
                            label=_str(label_token))

    def edge_filter_list(self, *filters) -> list:
        return list(filters)

    def edge_filter(self, id_token) -> EdgeType:
        return _edge_type(_str(id_token))

    def id_list(self, *ids) -> list[str]:
        return [_str(i) for i in ids]

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def positions_block(self, *constraints) -> list[Constraint]:
        return list(constraints)

    def constraint_cardinal(self, subject, kw, obj, *rest) -> Constraint:
        gap = _int(rest[0]) if rest else 0
        return Constraint(kind=_str(kw), subject=_str(subject),
                          object=_str(obj), gap=gap)

    def constraint_align(self, subject, kw, obj) -> Constraint:
        return Constraint(kind=_str(kw), subject=_str(subject), object=_str(obj))

    def constraint_same(self, subject, kw, obj) -> Constraint:
        return Constraint(kind=_str(kw), subject=_str(subject), object=_str(obj))

    def constraint_direction(self, subject, value) -> Constraint:
        return Constraint(kind="direction", subject=_str(subject), value=_str(value))

    def constraint_grid(self, subject, rows, cols) -> Constraint:
        return Constraint(kind="grid", subject=_str(subject),
                          value=f"{_int(rows)}x{_int(cols)}")

    def constraint_min_width(self, subject, value) -> Constraint:
        return Constraint(kind="min-width", subject=_str(subject), gap=_int(value))

    def constraint_min_height(self, subject, value) -> Constraint:
        return Constraint(kind="min-height", subject=_str(subject), gap=_int(value))

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def annotations_block(self, *annotations) -> list[Annotation]:
        return list(annotations)

    def ann_box(self, attrs) -> AnnotationBox:
        attrs = dict(attrs)
        nodes_raw = attrs.pop("nodes", "")
        nodes = nodes_raw.split() if isinstance(nodes_raw, str) else []
        return AnnotationBox(
            nodes=nodes,
            label=attrs.pop("label", ""),
            style=attrs.pop("style", "dashed"),
            color=attrs.pop("color", ""),
        )

    def ann_callout(self, attrs) -> AnnotationCallout:
        attrs = dict(attrs)
        return AnnotationCallout(
            anchor=attrs.pop("anchor", ""),
            text=attrs.pop("text", ""),
            position=attrs.pop("position", "above"),
        )

    def ann_separator(self, attrs) -> AnnotationSeparator:
        attrs = dict(attrs)
        between_raw = attrs.pop("between", "")
        between = between_raw.split() if isinstance(between_raw, str) else []
        return AnnotationSeparator(
            between=between,
            label=attrs.pop("label", ""),
            style=attrs.pop("style", "dashed"),
        )

    def ann_badge(self, attrs) -> AnnotationBadge:
        attrs = dict(attrs)
        return AnnotationBadge(
            anchor=attrs.pop("anchor", ""),
            text=attrs.pop("text", ""),
        )

    # ------------------------------------------------------------------
    # Sequence view
    # ------------------------------------------------------------------

    def sequence(self, name, model_name, body) -> SequenceView:
        select, annotations = body
        return SequenceView(
            name=_str(name),
            model_name=_str(model_name),
            select=select,
            annotations=annotations,
        )

    def sequence_body(self, *items):
        select = SelectClause()
        annotations: list[Annotation] = []
        for item in items:
            if isinstance(item, SelectClause):
                select = item
            elif isinstance(item, list):
                annotations = item
        return select, annotations


def parse(source: str) -> GgarchFile:
    """Parse ggarch source text into a GgarchFile.

    Raises ParseError on syntax errors.
    """
    try:
        tree = _PARSER.parse(source)
    except Exception as exc:
        raise ParseError(str(exc)) from exc
    return _GgarchTransformer().transform(tree)

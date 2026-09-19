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
    AnnotationLegend,
    AnnotationSeparator,
    Behaviour,
    Block,
    Cardinality,
    Constraint,
    FanConstraint,
    DiagramView,
    Edge,

    Environment,
    GgarchFile,
    InstanceSpec,
    Lifecycle,
    Model,
    Node,
    NodeField,
    SelectClause,
    SequenceView,
    StateView,
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

def _style_rule(rules) -> StyleRule:
    rule = StyleRule()
    for k, v in rules:
        setattr(rule, k.replace("-", "_"), v)
    return rule


def _int(token) -> int:
    return int(token)


def _edge_type(s: str) -> str:
    """Edge type names pass through; built-ins and custom names alike.

    Validation that a non-built-in name is styled happens in the
    validator (which can see the style block), not here.
    """
    return s


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
    url        = attrs.pop("url", "")
    records    = str(attrs.pop("records", "") or "")
    # Remaining attrs are user-defined properties.
    properties = {k: str(v) for k, v in attrs.items()}
    return Node(
        id=node_id,
        label=label,
        type=node_type,
        lifecycle=lifecycle,
        cardinality=cardinality,
        abstracts=abstracts,
        children=children,
        fields=fields or [],
        properties=properties,
        url=url,
        records=records,
        attrs={},
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
            elif isinstance(item, StateView):
                f.states.append(item)
        return f

    # ------------------------------------------------------------------
    # Model
    # ------------------------------------------------------------------

    def model(self, name_token, body) -> Model:
        nodes, edges, behaviours, style, environments = body
        m = Model(name=_str(name_token))
        m.nodes = nodes
        m.edges = edges
        m.behaviours = behaviours
        m.style = style
        m.environments = environments
        return m

    def model_body(self, *items):
        nodes: list[Node] = []
        edges: list[Edge] = []
        behaviours: list[Behaviour] = []
        style = Style()
        environments: list[Environment] = []
        for item in items:
            if isinstance(item, list):
                if item and isinstance(item[0], Node):
                    nodes = item
                elif item and isinstance(item[0], Edge):
                    edges = item
                elif item and isinstance(item[0], Behaviour):
                    behaviours = item
                elif item and isinstance(item[0], Environment):
                    environments.extend(item)
            elif isinstance(item, Style):
                style = item
        return nodes, edges, behaviours, style, environments

    def environment_block(self, _kw, name_token, *items) -> list[Environment]:
        present: list[str] = []
        abstracts: dict[str, str] = {}
        for item in items:
            if isinstance(item, tuple):
                k, v = item
                if k == "present":
                    present = v
                elif k == "abstracts":
                    abstracts = v
        return [Environment(name=_str(name_token), present=present, abstracts=abstracts)]

    def env_present(self, id_list) -> tuple:
        return ("present", id_list)

    def env_abstracts_block(self, *pairs) -> tuple:
        return ("abstracts", dict(pairs))

    def env_abstract(self, abstract_token, concrete_token) -> tuple:
        return (_str(abstract_token), _str(concrete_token))

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
        src_node, src_field = src
        tgt_node, tgt_field = tgt
        url = attrs.pop("url", "")
        properties = {k: str(v) for k, v in attrs.items()
                      if k not in ("type", "label", "protocol", "style", "arrow")}
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
            url=url,
            properties=properties,
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
        attrs = rest[-1] if rest and isinstance(rest[-1], dict) else {}
        attrs = dict(attrs)
        guard   = attrs.pop("guard",   "")
        trigger = attrs.pop("on",      "")
        props   = {k: str(v) for k, v in attrs.items()}
        return Step(kind=kind, source=_str(src), target=_str(tgt),
                    label=label, guard=guard, trigger=trigger, properties=props)

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
                s.dark_node_rules.update(value[0])
                s.dark_edge_rules.update(value[1])
            elif key == "edge":
                name, rule = value
                s.edge_rules[name] = rule
            else:
                s.node_rules[key] = value
        return s

    def style_extends(self, id_token) -> tuple:
        return ("extends", _str(id_token))

    def style_type_rule(self, id_token, *rules) -> tuple:
        return (_str(id_token), _style_rule(rules))

    def style_edge_rule(self, _kw, id_token, *rules) -> tuple:
        return ("edge", (_str(id_token), _style_rule(rules)))

    def style_rule(self, key, value) -> tuple:
        return (_str(key), value)

    def style_dark(self, *items) -> tuple:
        nodes: dict = {}
        edges: dict = {}
        for payload in items:
            if isinstance(payload, tuple) and payload[0] == "edge":
                _, (name, rule) = payload
                edges[name] = rule
            else:
                name, rule = payload
                nodes[name] = rule
        return ("dark", (nodes, edges))

    def style_dark_node_item(self, id_token, *rules) -> tuple:
        return (_str(id_token), _style_rule(rules))

    def style_dark_edge_item(self, _kw, id_token, *rules) -> tuple:
        return ("edge", (_str(id_token), _style_rule(rules)))

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
                if item and isinstance(item[0], (Constraint, FanConstraint)):
                    constraints = item
                elif item and isinstance(item[0], (
                        AnnotationBox, AnnotationCallout,
                        AnnotationSeparator, AnnotationBadge,
                        AnnotationLegend)):
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
            elif key == "instances":  s.instances.extend(value)
            elif key == "behaviour":  s.behaviour = value
            elif key == "participants":s.participants = value
            elif key == "routing":    s.routing = value
            elif key == "except":     s.except_pairs.extend(value)
            elif key == "sizing":     s.sizing = value
            elif key == "records":    s.show_records = value == "shown"
        return s

    def select_nodes(self, id_list)        -> tuple: return ("nodes", id_list)
    def select_edges(self, ef_list)        -> tuple: return ("edges", ef_list)
    def select_environment(self, id_token) -> tuple: return ("environment", _str(id_token))
    def select_collapse(self, id_list)     -> tuple: return ("collapse", id_list)
    def select_expand(self, id_list)       -> tuple: return ("expand", id_list)
    def select_behaviour(self, s_token)    -> tuple: return ("behaviour", _str(s_token))
    def select_participants(self, id_list) -> tuple: return ("participants", id_list)

    def select_routing(self, mode_token) -> tuple: return ("routing", _str(mode_token))

    def edge_ref(self, src_token, tgt_token, *typ) -> tuple:
        t = _str(typ[0]) if typ else ""
        return (_str(src_token), _str(tgt_token), t)

    def edge_ref_list(self, *refs) -> list: return list(refs)

    def select_except(self, refs) -> tuple: return ("except", refs)

    def select_sizing(self, mode_token) -> tuple: return ("sizing", _str(mode_token))

    def select_records(self, mode_token) -> tuple: return ("records", _str(mode_token))

    def select_instances(self, type_id, *specs) -> tuple:
        tid = _str(type_id)
        # Backfill type_id into each spec (instance_spec can't see it directly).
        filled = [InstanceSpec(type_id=tid, instance_id=s.instance_id, label=s.label)
                  for s in specs]
        return ("instances", filled)

    def instance_spec(self, id_token, label_token) -> InstanceSpec:
        return InstanceSpec(type_id="", instance_id=_str(id_token),
                            label=_str(label_token))

    def edge_filter_list(self, *filters) -> list:
        return list(filters)

    def edge_filter(self, id_token) -> str:
        return _edge_type(_str(id_token))

    def id_list(self, *ids) -> list[str]:
        return [_str(i) for i in ids]

    # ------------------------------------------------------------------
    # Positions
    # ------------------------------------------------------------------

    def positions_block(self, *constraints) -> list[Constraint | FanConstraint]:
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

    def constraint_fan(self, *args) -> FanConstraint:
        # Grammar: FAN_KW "[" ID+ "]" CARDINAL_KW ID ("gap" ":" INT)? ("spacing" ":" INT)?
        # Lark passes all matched tokens; skip the FAN_KW, collect member IDs until
        # a cardinal keyword, then anchor, then optional gap/spacing ints.
        cardinals = {"above", "below", "left-of", "right-of"}
        members: list[str] = []
        i = 0
        # Skip FAN_KW token ("fan").
        if i < len(args) and _str(args[i]) == "fan":
            i += 1
        while i < len(args) and _str(args[i]) not in cardinals:
            members.append(_str(args[i]))
            i += 1
        direction = _str(args[i]); i += 1
        anchor    = _str(args[i]); i += 1
        gap     = _int(args[i]) if i < len(args) else 20; i += 1
        spacing = _int(args[i]) if i < len(args) else 20
        return FanConstraint(members=members, direction=direction,
                             anchor=anchor, gap=gap, spacing=spacing)

    # ------------------------------------------------------------------
    # Annotations
    # ------------------------------------------------------------------

    def annotations_block(self, *annotations) -> list[Annotation]:
        return list(annotations)

    def ann_box(self, attrs) -> AnnotationBox:
        attrs = dict(attrs)
        nodes_raw = attrs.pop("nodes", "")
        nodes = nodes_raw.split() if isinstance(nodes_raw, str) else []
        pad = int(attrs.pop("padding", 10))
        return AnnotationBox(
            nodes=nodes,
            label=attrs.pop("label", ""),
            style=attrs.pop("style", "dashed"),
            color=attrs.pop("color", ""),
            label_position=attrs.pop("label-position", "top"),
            padding=pad,
            padding_top=int(attrs.pop("padding-top", pad)),
            padding_right=int(attrs.pop("padding-right", pad)),
            padding_bottom=int(attrs.pop("padding-bottom", pad)),
            padding_left=int(attrs.pop("padding-left", pad)),
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

    def ann_legend(self, attrs) -> AnnotationLegend:
        attrs = dict(attrs)
        position = attrs.pop("position", "bottom-right")
        labels = {k: v for k, v in attrs.items()}
        return AnnotationLegend(position=position, labels=labels)

    def ann_legend_bare(self) -> AnnotationLegend:
        return AnnotationLegend()

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

    # ------------------------------------------------------------------
    # State view
    # ------------------------------------------------------------------

    def state_view(self, name, model_name, body) -> StateView:
        select, annotations = body
        return StateView(
            name=_str(name),
            model_name=_str(model_name),
            select=select,
            annotations=annotations,
        )

    def state_view_body(self, *items):
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

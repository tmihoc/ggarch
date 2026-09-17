"""ggarch data model.

The model is the single source of truth for everything the system is and does.
Views are projections — they select, position, and annotate; they add no new
system facts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class Lifecycle(Enum):
    PERSISTENT = "persistent"  # runs continuously (default)
    INIT       = "init"        # runs once at startup, then exits
    EPHEMERAL  = "ephemeral"   # runs on demand, exits


class Cardinality(Enum):
    ONE_PER_DEPLOYMENT   = "one-per-deployment"
    ONE_PER_MODEL        = "one-per-model"
    ONE_PER_APPLICATION  = "one-per-application"
    ONE_PER_UNIT         = "one-per-unit"
    ONE_PER_HOST         = "one-per-host"


class EdgeType(Enum):
    API      = "api"      # RPC or REST over a network protocol
    STREAM   = "stream"   # long-lived connection (websocket, gRPC stream)
    EVENT    = "event"    # one-way notification
    DATA     = "data"     # data read/write (database, object store)
    CONTROL  = "control"  # process control (exec, signal, lifecycle)
    IPC      = "ipc"      # local inter-process (unix socket, pipe)
    CUSTOM   = "custom"   # declared in the style block


class StepKind(Enum):
    CALL   = "call"    # synchronous invocation
    RETURN = "return"  # response to a prior call
    ASYNC  = "async"   # fire-and-forget
    SELF   = "self"    # self-call (node acting on itself)


# ---------------------------------------------------------------------------
# Node fields
# ---------------------------------------------------------------------------

@dataclass
class NodeField:
    """A named field inside a structured node (record table or class box)."""
    id: str
    label: str
    type: str = ""         # display type string, e.g. "int", "text", "uuid"
    pk: bool = False       # primary key marker
    fk: bool = False       # foreign key marker
    uk: bool = False       # unique key marker
    nullable: bool = False # nullable marker (shown as "?")


# ---------------------------------------------------------------------------
# Nodes
# ---------------------------------------------------------------------------

@dataclass
class Node:
    """A node type in the model.

    Nodes are types, not unique instances. A node with cardinality
    one-per-unit exists N times in a live deployment; a view decides
    whether to render it as an abstract archetype box or as N labelled
    instances.
    """
    id: str
    label: str
    type: str                                 # maps to style grammar
    lifecycle: Lifecycle = Lifecycle.PERSISTENT
    cardinality: Cardinality | int | None = None
    abstracts: list[str] = field(default_factory=list)
    children: list[Node] = field(default_factory=list)
    fields: list[NodeField] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)  # arbitrary key-value metadata
    url: str = ""                             # if set, node is clickable in SVG
    attrs: dict[str, Any] = field(default_factory=dict)

    def all_ids(self) -> set[str]:
        """Return this node's id and all descendant ids."""
        ids = {self.id}
        for child in self.children:
            ids |= child.all_ids()
        return ids

    def find(self, node_id: str) -> Node | None:
        """Return node by id (depth-first), or None."""
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find(node_id)
            if found:
                return found
        return None


# ---------------------------------------------------------------------------
# Edges
# ---------------------------------------------------------------------------

@dataclass
class Edge:
    """A directed relationship between two model nodes."""
    source: str          # node id (or "node.field_id" for field-qualified)
    target: str          # node id (or "node.field_id" for field-qualified)
    type: EdgeType = EdgeType.API
    label: str = ""
    protocol: str = ""
    style: str = ""
    arrow: str = "forward"
    source_field: str = ""
    target_field: str = ""
    properties: dict[str, str] = field(default_factory=dict)  # arbitrary key-value metadata
    url: str = ""                             # if set, edge label is clickable in SVG


# ---------------------------------------------------------------------------
# Behaviours
# ---------------------------------------------------------------------------
@dataclass
class Step:
    """A single interaction step in a behaviour."""
    kind: StepKind
    source: str
    target: str
    label: str = ""
    body: list[Step | Block] = field(default_factory=list)
    properties: dict[str, str] = field(default_factory=dict)
    guard: str = ""    # [condition] — for state view rendering
    trigger: str = ""  # on: "event" — for state view rendering
@dataclass
class Block:
    """A structured block within a behaviour: loop, alt, par."""
    kind: str            # "loop" | "alt" | "par"
    label: str           # condition or description
    body: list[Step | Block] = field(default_factory=list)
    # For alt: the else branches.
    else_branches: list[tuple[str, list[Step | Block]]] = field(default_factory=list)


@dataclass
class Behaviour:
    """A named interaction sequence between model entities."""
    name: str
    steps: list[Step | Block] = field(default_factory=list)

    def all_participants(self) -> set[str]:
        """Return all node ids referenced in this behaviour."""
        ids: set[str] = set()
        self._collect_participants(self.steps, ids)
        return ids

    def _collect_participants(
        self,
        steps: list[Step | Block],
        ids: set[str],
    ) -> None:
        for item in steps:
            if isinstance(item, Step):
                ids.add(item.source)
                ids.add(item.target)
                self._collect_participants(item.body, ids)
            elif isinstance(item, Block):
                self._collect_participants(item.body, ids)
                for _, branch in item.else_branches:
                    self._collect_participants(branch, ids)


# ---------------------------------------------------------------------------
# Style
# ---------------------------------------------------------------------------

@dataclass
class StyleRule:
    """Visual properties for a node or edge type."""
    fill: str = ""
    stroke: str = ""
    font_color: str = ""
    font_size: int = 0
    shape: str = ""        # rectangle (default) | person | cylinder | diamond
    style: str = ""        # dashed | dotted | solid


@dataclass
class Style:
    """Visual grammar for the model."""
    extends: str = ""      # built-in preset name (e.g. "juju")
    node_rules: dict[str, StyleRule] = field(default_factory=dict)
    edge_rules: dict[str, StyleRule] = field(default_factory=dict)
    dark_node_rules: dict[str, StyleRule] = field(default_factory=dict)
    dark_edge_rules: dict[str, StyleRule] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Deployment environments
# ---------------------------------------------------------------------------

@dataclass
class Environment:
    """A named deployment context.

    Declares which nodes are present in this environment and which abstract
    node ids they realise (extending the node-level abstracts: relationship
    to a model-level grouping).
    """
    name: str
    present: list[str] = field(default_factory=list)   # node ids active in this env
    abstracts: dict[str, str] = field(default_factory=dict)  # {abstract_id: concrete_id}


# ---------------------------------------------------------------------------
# Model
# ---------------------------------------------------------------------------

@dataclass
class Model:
    """The complete system model."""
    name: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
    behaviours: list[Behaviour] = field(default_factory=list)
    style: Style = field(default_factory=Style)
    environments: list[Environment] = field(default_factory=list)

    # ------------------------------------------------------------------
    # Lookup helpers
    # ------------------------------------------------------------------

    def all_node_ids(self) -> set[str]:
        """Return every declared node id (including nested)."""
        ids: set[str] = set()
        for node in self.nodes:
            ids |= node.all_ids()
        return ids

    def find_node(self, node_id: str) -> Node | None:
        for node in self.nodes:
            found = node.find(node_id)
            if found:
                return found
        return None

    def find_behaviour(self, name: str) -> Behaviour | None:
        for b in self.behaviours:
            if b.name == name:
                return b
        return None

    def abstractions_map(self) -> dict[str, str]:
        """Return {abstract_id: concrete_id} for every abstracts relationship.

        If multiple concrete nodes abstract the same abstract id, the last
        one declared wins (ambiguous; the validator will warn).
        """
        result: dict[str, str] = {}
        for node in self.nodes:
            self._collect_abstractions(node, result)
        return result

    def _collect_abstractions(
        self, node: Node, result: dict[str, str]
    ) -> None:
        for abstract_id in node.abstracts:
            result[abstract_id] = node.id
        for child in node.children:
            self._collect_abstractions(child, result)

    def resolve_id(self, node_id: str) -> str:
        """Resolve an abstract node id to its concrete id, if one exists.

        Returns the original id if no abstraction is declared.
        """
        return self.abstractions_map().get(node_id, node_id)

    def all_valid_ids(self) -> set[str]:
        """Declared node ids PLUS abstract ids covered by abstracts relationships."""
        ids = self.all_node_ids()
        ids |= set(self.abstractions_map().keys())
        return ids

    def find_environment(self, name: str) -> Environment | None:
        for env in self.environments:
            if env.name == name:
                return env
        return None

    def environment_abstractions_map(self, env_name: str) -> dict[str, str]:
        """Return {abstract_id: concrete_id} for a specific environment.

        Merges the model-level node abstracts with the environment's own
        abstracts block. Environment-specific overrides win.
        """
        result = dict(self.abstractions_map())  # start from node-level abstracts
        env = self.find_environment(env_name)
        if env:
            result.update(env.abstracts)        # environment-level overrides
        return result

    def all_valid_ids_for_env(self, env_name: str) -> set[str]:
        """Declared node ids PLUS abstract ids resolvable in env_name."""
        ids = self.all_node_ids()
        ids |= set(self.environment_abstractions_map(env_name).keys())
        return ids


# ---------------------------------------------------------------------------
# Views
# ---------------------------------------------------------------------------

@dataclass
class InstanceSpec:
    """Specifies how a type node should be rendered as a named instance."""
    type_id: str
    instance_id: str
    label: str


@dataclass
class SelectClause:
    """Which model entities to include in a view, and how."""
    node_ids: list[str] = field(default_factory=list)
    edge_types: list[EdgeType] = field(default_factory=list)  # empty = all
    environment: str = ""
    collapse: list[str] = field(default_factory=list)   # node ids to close
    expand: list[str] = field(default_factory=list)     # node ids to open
    instances: list[InstanceSpec] = field(default_factory=list)
    behaviour: str = ""    # for sequence views: which behaviour to render
    participants: list[str] = field(default_factory=list)  # optional filter


@dataclass
class Constraint:
    """A spatial constraint between two nodes."""
    kind: str            # left-of | right-of | above | below |
                         # align-top | align-bottom | align-left |
                         # align-right | align-middle | align-centre |
                         # same-width | same-height | same-size |
                         # direction | grid
    subject: str         # node id
    object: str = ""     # node id (not needed for direction/grid)
    gap: int = 0
    value: str = ""      # for direction (left|right|up|down) and grid


@dataclass
class FanConstraint:
    """Fan a group of nodes in one direction relative to an anchor node.

    Places all members on the same plane (above/below/left-of/right-of the
    anchor), spaced evenly, and centred on the anchor's perpendicular axis.
    Expanded into ordinary Constraints before the solver runs.
    """
    members: list[str]      # node ids, left-to-right or top-to-bottom
    direction: str          # above | below | left-of | right-of
    anchor: str             # anchor node id
    gap: int = 20           # px between fan plane and anchor
    spacing: int = 20       # px between members

@dataclass
class AnnotationBox:
    """A dashed/solid rectangle enclosing a set of nodes."""
    nodes: list[str]
    label: str = ""
    style: str = "dashed"
    color: str = ""
    label_position: str = "top"  # top | bottom | left | right


@dataclass
class AnnotationCallout:
    """A text label anchored to a node."""
    anchor: str
    text: str
    position: str = "above"   # above | below | left | right


@dataclass
class AnnotationSeparator:
    """A line between two groups of nodes."""
    between: list[str]
    label: str = ""
    style: str = "dashed"


@dataclass
class AnnotationBadge:
    """A small label on a specific node."""
    anchor: str
    text: str


@dataclass
class AnnotationLegend:
    """A visual key rendered from the model's style block.

    Renders only node types and edge types actually used in the current view.
    position: one of 'top-left' | 'top-right' | 'bottom-left' | 'bottom-right'
    labels: optional dict mapping internal type names to human-readable display names.
    """
    position: str = "bottom-right"
    labels: dict = field(default_factory=dict)

Annotation = AnnotationBox | AnnotationCallout | AnnotationSeparator | AnnotationBadge | AnnotationLegend


@dataclass
class DiagramView:
    """A topology/deployment view: selects nodes, declares positions and annotations."""
    name: str
    model_name: str
    select: SelectClause = field(default_factory=SelectClause)
    constraints: list[Constraint | FanConstraint] = field(default_factory=list)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class SequenceView:
    """A sequence diagram view: selects a behaviour, optionally filters participants."""
    name: str
    model_name: str
    select: SelectClause = field(default_factory=SelectClause)
    annotations: list[Annotation] = field(default_factory=list)


@dataclass
class StateView:
    """A state machine view: renders a behaviour as a state transition diagram."""
    name: str
    model_name: str
    select: SelectClause = field(default_factory=SelectClause)
    annotations: list[Annotation] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Top-level file
# ---------------------------------------------------------------------------

@dataclass
class GgarchFile:
    """The parsed contents of a .ggarch file."""
    models: list[Model] = field(default_factory=list)
    diagrams: list[DiagramView] = field(default_factory=list)
    sequences: list[SequenceView] = field(default_factory=list)
    states: list[StateView] = field(default_factory=list)

    def get_model(self, name: str) -> Model | None:
        for m in self.models:
            if m.name == name:
                return m
        return None

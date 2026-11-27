"""ggarch layout types.

Geometry produced by the constraint solver. These are the solved coordinates
that the renderer consumes. All values are in SVG user units (pixels).
"""
from __future__ import annotations

from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Geometry primitives
# ---------------------------------------------------------------------------

@dataclass
class Rect:
    """Axis-aligned bounding rectangle."""
    x: float
    y: float
    w: float
    h: float

    @property
    def cx(self) -> float:
        return self.x + self.w / 2

    @property
    def cy(self) -> float:
        return self.y + self.h / 2

    @property
    def x2(self) -> float:
        return self.x + self.w

    @property
    def y2(self) -> float:
        return self.y + self.h


@dataclass
class SolvedNode:
    """A node with fully solved geometry."""
    id: str
    rect: Rect
    # Children solved recursively; empty for leaf nodes.
    children: list[SolvedNode] = field(default_factory=list)
    # Carry through model node properties for the renderer.
    label: str = ""
    type: str = ""
    lifecycle: str = "persistent"
    cardinality: str = ""
    fields: list = field(default_factory=list)  # list[NodeField]
    url: str = ""
    properties: dict = field(default_factory=dict)
    records: str = ""   # backing record id, for the renderer's records chip

    def find(self, node_id: str) -> SolvedNode | None:
        if self.id == node_id:
            return self
        for child in self.children:
            found = child.find(node_id)
            if found:
                return found
        return None


@dataclass
class SolvedLayout:
    """The fully solved layout for one diagram view.

    edge_routes: when laid out by the ELK backend (ADR-006), the
    backend's edge geometry as (source, target, [Point, ...]) tuples;
    route() wraps these instead of running the built-in router. None
    for the built-in synthesizer."""
    edge_routes: list | None = None
    # Top-level solved nodes (in declaration order).
    nodes: list[SolvedNode] = field(default_factory=list)
    # Total bounding box of the diagram (for SVG viewBox).
    bounds: Rect = field(default_factory=lambda: Rect(0, 0, 0, 0))
    # Declared fan faces (ADR-007 salience of arrangement): for each
    # materialized edge under a FanConstraint, (source_face,
    # target_face) from the fan's declared direction — "fan above"
    # means the anchor's arrows leave NORTH and arrive on the members'
    # south faces, however wide the fan spreads. The router honours
    # this over its centre-delta geometry class, which misreads a wide
    # fan as inter-column flow (measured on the Juju enters fan).
    fan_faces: dict[tuple[str, str], tuple[str, str]] = field(
        default_factory=dict)

    def find(self, node_id: str) -> SolvedNode | None:
        for n in self.nodes:
            found = n.find(node_id)
            if found:
                return found
        return None


# ---------------------------------------------------------------------------
# Node sizing
# ---------------------------------------------------------------------------

# Layout constants (all in SVG user units / px).
FONT_SIZE         = 13      # px — matches the style grammar default
CHAR_WIDTH        = 7.2     # px — approximate for a 13px sans-serif font
LINE_HEIGHT       = 18      # px
PADDING_X         = 16      # px horizontal padding inside a node box
PADDING_Y         = 12      # px vertical padding inside a node box
CONTAINER_PAD_TOP = 28      # px — extra top padding for container label (also the bottom pad: the content centres on the box)
CONTAINER_COMPACT_TOP = 36  # px — compact mode: the label band, with room around the label
CONTAINER_PAD     = 16      # px — padding around children inside a container
CONTAINER_BOTTOM_PAD = 16   # px — compact mode: bottom padding (no label there)
MIN_NODE_WIDTH    = 80      # px
MIN_NODE_HEIGHT   = 36      # px


def _text_size(label: str) -> tuple[float, float]:
    """Estimate (width, height) of a text label in px.

    Handles \\n line breaks. Does not account for font metrics precisely —
    good enough for layout; the renderer will use actual text metrics.
    """
    if not label:
        return MIN_NODE_WIDTH, LINE_HEIGHT
    lines = label.split("\\n")
    max_chars = max(len(line) for line in lines)
    w = max_chars * CHAR_WIDTH
    h = len(lines) * LINE_HEIGHT
    return w, h


FIELD_ROW_H   = 20    # px — height of one field row in a record/class node
FIELD_HEADER_H = 28   # px — header compartment height for record/class nodes


def container_pad_top(label: str, compact: bool = False) -> float:
    """Top padding of a container.

    The default keeps the label band (28 px) and pads the bottom to match, so
    the content sits on the container's midline: edges that must stay straight
    between a nested child and a node aligned with the container rely on it.
    A container that opts in with `padding: compact` spends padding where a
    label needs it: the label band with room around the label (36 px) when it
    has a label, the plain padding when it has none; its bottom is the plain
    padding, and its content centres on the box between the two.
    """
    if not compact:
        return CONTAINER_PAD_TOP
    return CONTAINER_COMPACT_TOP if label else CONTAINER_PAD


def min_size(label: str, is_container: bool = False) -> tuple[float, float]:
    """Return the minimum (width, height) for a node with the given label.

    For containers the minimum size is just the label size with padding —
    the solver will expand it to contain its children.
    """
    tw, th = _text_size(label)
    w = max(tw + PADDING_X * 2, MIN_NODE_WIDTH)
    if is_container:
        h = max(th + CONTAINER_PAD_TOP, MIN_NODE_HEIGHT)
    else:
        h = max(th + PADDING_Y * 2, MIN_NODE_HEIGHT)
    return w, h


def field_node_min_size(label: str, n_fields: int) -> tuple[float, float]:
    """Min size for a record/class node: header + field rows."""
    tw, _ = _text_size(label)
    w = max(tw + PADDING_X * 2, 160)  # wider default for table nodes
    h = FIELD_HEADER_H + max(n_fields, 1) * FIELD_ROW_H + 4  # 4px bottom pad
    return w, h


# ---------------------------------------------------------------------------
# Ports
# ---------------------------------------------------------------------------

PORT_SIZE        = 12   # px — side of a port's square, centred on the border
PORT_ROW_H       = 30   # px — one row per left/right port; one band per top/bottom side
PORT_LABEL_BAND  = 32   # px — the node's own label band above the port rows
PORT_BOTTOM_PAD  = 8    # px
PORT_LABEL_GAP   = 8    # px — between a port's square and its label
PORT_LABEL_FONT  = 12   # px


def _side_ports(ports, side):
    return [p for p in ports if p.side == side]


def port_top_extra(ports) -> float:
    """Height of the band that top ports' labels take above the node label."""
    return PORT_ROW_H if _side_ports(ports, "top") else 0


def port_label_y(rect: Rect, ports) -> float:
    """Centre y of the node's own label in a node with ports."""
    return rect.y + port_top_extra(ports) + PORT_LABEL_BAND / 2


def port_node_min_size(label: str, ports) -> tuple[float, float]:
    """Min size for a node with ports: its label band, one row per
    left/right port (the two sides share rows), and a band for each of the
    top and bottom sides that has ports; wide enough for the labels."""
    tw, _ = _text_size(label)
    left, right = _side_ports(ports, "left"), _side_ports(ports, "right")
    top, bottom = _side_ports(ports, "top"), _side_ports(ports, "bottom")
    label_w = lambda ps: max((len(p.label) * CHAR_WIDTH for p in ps), default=0)
    inset = PORT_SIZE / 2 + PORT_LABEL_GAP
    side_w = (inset + label_w(left) if left else 0) + (inset + label_w(right) if right else 0)
    if left and right:
        side_w += PADDING_X
    across = max(len(top), len(bottom))
    across_w = (across + 1) * max(label_w(top + bottom) + PADDING_X, 0) if across else 0
    w = max(tw + PADDING_X * 2, side_w + PADDING_X, across_w, MIN_NODE_WIDTH)
    rows = max(len(left), len(right))
    h = (port_top_extra(ports) + PORT_LABEL_BAND
         + rows * PORT_ROW_H + PORT_BOTTOM_PAD
         + (PORT_ROW_H if bottom else 0))
    return w, max(h, MIN_NODE_HEIGHT)


def port_center(rect: Rect, ports, port_id: str) -> tuple[float, float, str]:
    """Centre (x, y) of a port's square on the node's border, and its side.
    Left and right ports sit in rows below the node label, in declaration
    order per side; top and bottom ports spread evenly along their face."""
    port = next(p for p in ports if p.id == port_id)
    same = _side_ports(ports, port.side)
    i = same.index(port)
    if port.side in ("left", "right"):
        cy = (rect.y + port_top_extra(ports) + PORT_LABEL_BAND
              + i * PORT_ROW_H + PORT_ROW_H / 2)
        return (rect.x if port.side == "left" else rect.x2), cy, port.side
    cx = rect.x + rect.w * (i + 1) / (len(same) + 1)
    return cx, (rect.y if port.side == "top" else rect.y2), port.side


def port_anchor(rect: Rect, ports, port_id: str) -> tuple[float, float, str]:
    """Where an edge ends on a port: the midpoint of the square's outer face."""
    cx, cy, side = port_center(rect, ports, port_id)
    half = PORT_SIZE / 2
    dx, dy = {"left": (-half, 0), "right": (half, 0),
              "top": (0, -half), "bottom": (0, half)}[side]
    return cx + dx, cy + dy, side

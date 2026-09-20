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
CONTAINER_PAD_TOP = 28      # px — extra top padding for container label
CONTAINER_PAD     = 16      # px — padding around children inside a container
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

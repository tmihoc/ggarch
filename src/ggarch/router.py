"""ggarch edge router.

Given a solved layout and a model, computes the start and end anchor points
for each edge, then routes a path between them.

Routing strategy (Phase 3): straight lines with elbow fallback.
- If source and target are on different horizontal levels: straight line.
- If they share roughly the same y-centre (within threshold): two-segment
  elbow routed above or below to avoid overlapping the nodes.

Each routed edge is a list of (x, y) waypoints. The renderer draws these
as a polyline with an arrowhead at the last point.

Anchor point selection:
- For each edge, we pick the face of the source/target rect that minimises
  the Euclidean distance between the centres.
- Faces: top-centre, bottom-centre, left-centre, right-centre.
- The anchor is the midpoint of that face.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from ggarch.layout import Rect, SolvedLayout, SolvedNode
from ggarch.model import Edge, GgarchFile, Model


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------

@dataclass
class Point:
    x: float
    y: float

    def __iter__(self):
        yield self.x
        yield self.y

    def distance_to(self, other: Point) -> float:
        return math.hypot(self.x - other.x, self.y - other.y)


@dataclass
class RoutedEdge:
    """A routed edge ready for the renderer."""
    source_id: str
    target_id: str
    label: str
    edge_type: str     # from EdgeType.value
    style: str         # solid | dashed | dotted
    arrow: str         # forward | back | both | none
    # Waypoints: first = start anchor, last = end anchor.
    points: list[Point] = field(default_factory=list)

    @property
    def start(self) -> Point:
        return self.points[0]

    @property
    def end(self) -> Point:
        return self.points[-1]

    @property
    def mid(self) -> Point:
        """Midpoint of the path — used for label placement."""
        if len(self.points) == 2:
            return Point(
                (self.points[0].x + self.points[1].x) / 2,
                (self.points[0].y + self.points[1].y) / 2,
            )
        # For elbows, use the middle waypoint.
        return self.points[len(self.points) // 2]


@dataclass
class RoutedLayout:
    """Solved layout plus routed edges for one diagram view."""
    layout: SolvedLayout
    edges: list[RoutedEdge] = field(default_factory=list)


# ---------------------------------------------------------------------------
# Anchor point calculation
# ---------------------------------------------------------------------------

_FACE_OFFSETS = {
    "top":    (0.5,  0.0),
    "bottom": (0.5,  1.0),
    "left":   (0.0,  0.5),
    "right":  (1.0,  0.5),
}


def _face_point(rect: Rect, face: str) -> Point:
    fx, fy = _FACE_OFFSETS[face]
    return Point(rect.x + rect.w * fx, rect.y + rect.h * fy)


def _best_anchors(src_rect: Rect, tgt_rect: Rect) -> tuple[Point, Point]:
    """Return (source_anchor, target_anchor) using the closest opposing faces."""
    src_cx, src_cy = src_rect.cx, src_rect.cy
    tgt_cx, tgt_cy = tgt_rect.cx, tgt_rect.cy

    dx = tgt_cx - src_cx
    dy = tgt_cy - src_cy

    # Primary axis: whichever delta is larger.
    if abs(dx) >= abs(dy):
        # Horizontal dominant.
        if dx >= 0:
            return _face_point(src_rect, "right"), _face_point(tgt_rect, "left")
        else:
            return _face_point(src_rect, "left"), _face_point(tgt_rect, "right")
    else:
        # Vertical dominant.
        if dy >= 0:
            return _face_point(src_rect, "bottom"), _face_point(tgt_rect, "top")
        else:
            return _face_point(src_rect, "top"), _face_point(tgt_rect, "bottom")


# ---------------------------------------------------------------------------
# Path routing
# ---------------------------------------------------------------------------

def _route_straight_horizontal(
    src_rect: Rect,
    tgt_rect: Rect,
) -> list[Point]:
    """Straight horizontal line. Exits right/left face, enters opposite face."""
    if tgt_rect.cx > src_rect.cx:
        return [_face_point(src_rect, "right"), _face_point(tgt_rect, "left")]
    else:
        return [_face_point(src_rect, "left"), _face_point(tgt_rect, "right")]


def _route_orthogonal(
    src_rect: Rect,
    tgt_rect: Rect,
) -> list[Point]:
    """L-shaped orthogonal route for primarily-vertical travel.

    Exits bottom/top face, horizontal jog at midpoint, enters top/bottom face.
    """
    src_cx, src_cy = src_rect.cx, src_rect.cy
    tgt_cx, tgt_cy = tgt_rect.cx, tgt_rect.cy

    # Same column — straight vertical.
    if abs(src_cx - tgt_cx) < 4:
        if tgt_cy > src_cy:
            return [_face_point(src_rect, "bottom"), _face_point(tgt_rect, "top")]
        else:
            return [_face_point(src_rect, "top"), _face_point(tgt_rect, "bottom")]

    if tgt_cy >= src_cy:
        src_pt = _face_point(src_rect, "bottom")
        tgt_pt = _face_point(tgt_rect, "top")
        mid_y  = src_rect.y2 + (tgt_rect.y - src_rect.y2) / 2
        mid_y  = max(mid_y, src_rect.y2 + 6)
        mid_y  = min(mid_y, tgt_rect.y  - 6)
    else:
        src_pt = _face_point(src_rect, "top")
        tgt_pt = _face_point(tgt_rect, "bottom")
        mid_y  = tgt_rect.y2 + (src_rect.y - tgt_rect.y2) / 2
        mid_y  = max(mid_y, tgt_rect.y2 + 6)
        mid_y  = min(mid_y, src_rect.y  - 6)

    return [
        src_pt,
        Point(src_pt.x, mid_y),
        Point(tgt_pt.x, mid_y),
        tgt_pt,
    ]


def _route_edge(
    src_rect: Rect,
    tgt_rect: Rect,
) -> list[Point]:
    """Choose routing strategy based on relative position and face alignment.

    - Truly horizontal (face points at same y within 4px) → straight 2-point.
    - Primarily horizontal (dx >= dy) but different y → ⌐-shape 3-point:
        exit source right/left face horizontally, then drop/rise vertically
        at the target's near edge to enter the target face.
    - Primarily vertical (dy > dx) → L-shaped 4-point orthogonal.
    """
    dx = abs(tgt_rect.cx - src_rect.cx)
    dy = abs(tgt_rect.cy - src_rect.cy)

    going_right = tgt_rect.cx >= src_rect.cx

    if dx >= dy:
        src_face = "right" if going_right else "left"
        tgt_face = "left"  if going_right else "right"
        src_pt = _face_point(src_rect, src_face)
        tgt_pt = _face_point(tgt_rect, tgt_face)

        if abs(src_pt.y - tgt_pt.y) < 10:
            # Face points genuinely at the same height — pure horizontal.
            return [src_pt, tgt_pt]

        # Different y: go horizontal at source height, then vertical to target.
        return [
            src_pt,
            Point(tgt_pt.x, src_pt.y),
            tgt_pt,
        ]

    return _route_orthogonal(src_rect, tgt_rect)

# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def _effective_rect(node: SolvedNode) -> Rect:
    """Return the rect used for anchor-point calculation."""
    return node.rect


def _field_anchor(
    node: SolvedNode,
    field_id: str,
    face: str,
) -> Point:
    """Return the anchor point for a field-qualified edge endpoint.

    face: "right" | "left" | "top" | "bottom"
    The y (for left/right) or x (for top/bottom) is centred on the field row.
    """
    from ggarch.layout import FIELD_HEADER_H, FIELD_ROW_H
    field_index = next(
        (i for i, f in enumerate(node.fields) if f.id == field_id), 0
    )
    field_y = node.rect.y + FIELD_HEADER_H + field_index * FIELD_ROW_H + FIELD_ROW_H / 2
    if face == "right":
        return Point(node.rect.x2, field_y)
    elif face == "left":
        return Point(node.rect.x, field_y)
    elif face == "top":
        return Point(node.rect.cx, node.rect.y)
    else:  # bottom
        return Point(node.rect.cx, node.rect.y2)


def route(layout: SolvedLayout, model: Model, select) -> RoutedLayout:
    """Compute routed edges for all model edges whose endpoints are in layout."""
    routed_edges: list[RoutedEdge] = []

    for edge in model.edges:
        src_node = layout.find(edge.source)
        tgt_node = layout.find(edge.target)
        if src_node is None or tgt_node is None:
            continue

        if select.edge_types and edge.type not in select.edge_types:
            continue

        # Field-qualified endpoints: choose face based on dominant axis,
        # same as _route_edge, so arrows don't cross the node boxes.
        if edge.source_field or edge.target_field:
            src_rect = _effective_rect(src_node)
            tgt_rect = _effective_rect(tgt_node)
            dx = abs(tgt_rect.cx - src_rect.cx)
            dy = abs(tgt_rect.cy - src_rect.cy)
            if dx >= dy:
                # Horizontal dominant: left/right faces.
                going_right = tgt_rect.cx >= src_rect.cx
                src_face = "right" if going_right else "left"
                tgt_face = "left"  if going_right else "right"
            else:
                # Vertical dominant: top/bottom faces.
                going_down = tgt_rect.cy >= src_rect.cy
                src_face = "bottom" if going_down else "top"
                tgt_face = "top"    if going_down else "bottom"

            src_pt = (_field_anchor(src_node, edge.source_field, src_face)
                      if edge.source_field
                      else _face_point(src_rect, src_face))
            tgt_pt = (_field_anchor(tgt_node, edge.target_field, tgt_face)
                      if edge.target_field
                      else _face_point(tgt_rect, tgt_face))
            points = [src_pt, tgt_pt]
        else:
            points = _route_edge(_effective_rect(src_node), _effective_rect(tgt_node))

        style = _default_style(edge.type.value)

        routed_edges.append(RoutedEdge(
            source_id=edge.source,
            target_id=edge.target,
            label=edge.label,
            edge_type=edge.type.value,
            style=edge.style if edge.style else style,
            arrow=edge.arrow,
            points=points,
        ))

    return RoutedLayout(layout=layout, edges=routed_edges)


def _default_style(edge_type: str) -> str:
    """Default line style for each semantic edge type."""
    return {
        "stream":  "dashed",
        "event":   "dashed",
        "data":    "solid",
        "api":     "solid",
        "control": "solid",
        "ipc":     "dotted",
    }.get(edge_type, "solid")

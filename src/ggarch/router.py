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

_SAME_LEVEL_THRESHOLD = 10   # px — centres closer than this → use elbow
_ELBOW_CLEARANCE      = 20   # px — elbow offset from node face


def _route_straight(src: Point, tgt: Point) -> list[Point]:
    return [src, tgt]


def _route_elbow(
    src: Point,
    tgt: Point,
    src_rect: Rect,
    tgt_rect: Rect,
) -> list[Point]:
    """Two-segment elbow when source and target are at roughly the same height.

    Routes above or below depending on which direction has more clearance.
    """
    # Route above if there is space; otherwise below.
    clearance_above = min(src_rect.y, tgt_rect.y) - _ELBOW_CLEARANCE
    if clearance_above > 0:
        mid_y = clearance_above
    else:
        mid_y = max(src_rect.y2, tgt_rect.y2) + _ELBOW_CLEARANCE

    return [
        src,
        Point(src.x, mid_y),
        Point(tgt.x, mid_y),
        tgt,
    ]


def _route_edge(
    src_rect: Rect,
    tgt_rect: Rect,
) -> list[Point]:
    """Route from src_rect to tgt_rect."""
    src_pt, tgt_pt = _best_anchors(src_rect, tgt_rect)

    # Use elbow if centres are at roughly the same height.
    same_level = abs(src_rect.cy - tgt_rect.cy) < _SAME_LEVEL_THRESHOLD
    if same_level:
        return _route_elbow(src_pt, tgt_pt, src_rect, tgt_rect)

    return _route_straight(src_pt, tgt_pt)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def route(layout: SolvedLayout, model: Model, select) -> RoutedLayout:
    """Compute routed edges for all model edges whose endpoints are in layout.

    select: SelectClause — used to filter edge types if specified.
    """
    routed_edges: list[RoutedEdge] = []

    for edge in model.edges:
        # Skip edges whose endpoints are not in the layout.
        src_node = layout.find(edge.source)
        tgt_node = layout.find(edge.target)
        if src_node is None or tgt_node is None:
            continue

        # Filter by edge type if the view specifies a type filter.
        if select.edge_types and edge.type not in select.edge_types:
            continue

        points = _route_edge(src_node.rect, tgt_node.rect)

        # Default style from edge type.
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

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

from ggarch.instances import materialize_instances

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
    edge_type: str     # edge type name (built-in or custom)
    style: str         # solid | dashed | dotted
    arrow: str         # forward | back | both | none
    url: str = ""      # if set, edge label is clickable
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
    """Primarily-vertical route.

    - Same column (dx < 4px) → straight vertical.
    - Small horizontal deviation (dx < dy * 0.4) → straight diagonal.
      The horizontal offset is too small to warrant a jog; a diagonal
      is cleaner and avoids producing degenerate short segments.
    - Otherwise → L-shaped 4-point orthogonal with midpoint jog.
    """
    src_cx, src_cy = src_rect.cx, src_rect.cy
    tgt_cx, tgt_cy = tgt_rect.cx, tgt_rect.cy
    dx = abs(tgt_cx - src_cx)
    dy = abs(tgt_cy - src_cy)

    # Same column — straight vertical.
    if dx < 4:
        if tgt_cy > src_cy:
            return [_face_point(src_rect, "bottom"), _face_point(tgt_rect, "top")]
        else:
            return [_face_point(src_rect, "top"), _face_point(tgt_rect, "bottom")]

    # Very small horizontal deviation — snap to a clean vertical through the midpoints.
    if dx < dy * 0.2:
        mid_x = (src_rect.cx + tgt_rect.cx) / 2
        if tgt_cy < src_cy:  # target above source
            return [Point(mid_x, src_rect.y), Point(mid_x, tgt_rect.y2)]
        else:
            return [Point(mid_x, src_rect.y2), Point(mid_x, tgt_rect.y)]

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

    - Primarily horizontal (dx >= dy) → straight line from source right/left
        face to target left/right face (diagonal or flat). The former ⌐-shape
        3-point route placed its bend at the target's near face, making the
        final segment traverse the target's own border — always degenerate.
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

        # Straight line: flat when same height, diagonal otherwise.
        # The old ⌐ bend always landed on the target face, so the last segment
        # ran down the target's own border.  Direct is always better here.
        return [src_pt, tgt_pt]

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

    # Materialized edges: instanced types are stamped out (subtrees +
    # per-instance edge expansion) so routing sees the same nodes the
    # solver laid out. Shared with the solver via ggarch.instances.
    _, edges = materialize_instances(select, model)

    for edge in edges:
        if select.edge_types and edge.type not in select.edge_types:
            continue
        sid, tid = edge.source, edge.target
        src_node = layout.find(sid)
        tgt_node = layout.find(tid)
        if src_node is None or tgt_node is None:
            continue

        # Field-qualified endpoints.
        if edge.source_field or edge.target_field:
            src_rect = _effective_rect(src_node)
            tgt_rect = _effective_rect(tgt_node)
            dx = abs(tgt_rect.cx - src_rect.cx)
            dy = abs(tgt_rect.cy - src_rect.cy)
            if dx >= dy:
                going_right = tgt_rect.cx >= src_rect.cx
                src_face = "right" if going_right else "left"
                tgt_face = "left"  if going_right else "right"
            else:
                going_down = tgt_rect.cy >= src_rect.cy
                src_face = "bottom" if going_down else "top"
                tgt_face = "top"    if going_down else "bottom"
            src_pt = (_field_anchor(src_node, edge.source_field, src_face)
                      if edge.source_field
                      else _face_point(src_rect, src_face))
            tgt_pt = (_field_anchor(tgt_node, edge.target_field, tgt_face)
                      if edge.target_field
                      else _face_point(tgt_rect, tgt_face))
            if dx >= dy and (edge.source_field or edge.target_field):
                mid_y = (src_pt.y + tgt_pt.y) / 2
                src_pt = Point(src_pt.x, mid_y)
                tgt_pt = Point(tgt_pt.x, mid_y)
            points = [src_pt, tgt_pt]
        else:
            points = _route_edge(_effective_rect(src_node), _effective_rect(tgt_node))

        style = _default_style(edge.type)
        routed_edges.append(RoutedEdge(
            source_id=sid,
            target_id=tid,
            label=edge.label,
            edge_type=edge.type,
            style=edge.style if edge.style else style,
            arrow=edge.arrow,
            url=edge.url,
            points=points,
        ))
    _spread_shared_face_anchors(routed_edges, layout)
    _simplify_spread_paths(routed_edges)
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


def _simplify_spread_paths(edges: list[RoutedEdge]) -> None:
    """After face-spread, collapse L-shaped paths to diagonals when the
    horizontal deviation is small relative to the vertical travel.

    The face-spread adjusts endpoint positions but doesn't re-route, so an
    L-shape that was valid before spreading may now be nearly vertical and
    better rendered as a diagonal.  Threshold: dx < dy * 0.5.
    """
    for e in edges:
        if len(e.points) != 4:
            continue
        src, tgt = e.points[0], e.points[-1]
        dx = abs(tgt.x - src.x)
        dy = abs(tgt.y - src.y)
        if dy > 0 and dx <= dy * 0.2:
            mid_x = (src.x + tgt.x) / 2
            e.points[:] = [Point(mid_x, src.y), Point(mid_x, tgt.y)]


# ---------------------------------------------------------------------------
# Face anchor spreading
# ---------------------------------------------------------------------------

def _spread_shared_face_anchors(
    edges: list[RoutedEdge],
    layout: SolvedLayout,
) -> None:
    """Redistribute endpoint anchor points when multiple edges share the same
    node face, so arrowheads fan across the face instead of piling up.

    Groups edges by (node_id, which_end, face).  For each group with >1 edge,
    evenly spaces the anchor points along the face, with a 20% inset from each
    corner.  Adjusts the adjacent waypoint to keep the path rectilinear.
    """
    INSET = 0.20  # fraction of face length kept clear at each end

    def _face_of(pt: Point, rect: Rect) -> str | None:
        """Identify which face of rect the point lies on (within 1px)."""
        if abs(pt.y - rect.y)  < 1: return "top"
        if abs(pt.y - rect.y2) < 1: return "bottom"
        if abs(pt.x - rect.x)  < 1: return "left"
        if abs(pt.x - rect.x2) < 1: return "right"
        return None

    # Collect groups: key = (node_id, end, face_name)
    # end: "start" or "end"
    from collections import defaultdict
    groups: dict = defaultdict(list)
    for e in edges:
        for end, pt in (("start", e.points[0]), ("end", e.points[-1])):
            node_id = e.source_id if end == "start" else e.target_id
            node = layout.find(node_id)
            if node is None:
                continue
            face = _face_of(pt, node.rect)
            if face:
                groups[(node_id, end, face)].append(e)

    for (node_id, end, face), group in groups.items():
        if len(group) < 2:
            continue
        node = layout.find(node_id)
        r = node.rect
        horiz_face = face in ("top", "bottom")
        if horiz_face:
            lo = r.x  + r.w * INSET
            hi = r.x2 - r.w * INSET
        else:
            lo = r.y  + r.h * INSET
            hi = r.y2 - r.h * INSET

        n = len(group)
        step = (hi - lo) / (n - 1) if n > 1 else 0
        for i, e in enumerate(group):
            coord = lo + i * step
            pts = list(e.points)
            if end == "start":
                old = pts[0]
                if horiz_face:
                    pts[0] = Point(coord, old.y)
                    if len(pts) > 1 and abs(pts[1].x - old.x) < 1:
                        pts[1] = Point(coord, pts[1].y)
                else:
                    pts[0] = Point(old.x, coord)
                    if len(pts) > 1 and abs(pts[1].y - old.y) < 1:
                        pts[1] = Point(pts[1].x, coord)
            else:
                old = pts[-1]
                if horiz_face:
                    pts[-1] = Point(coord, old.y)
                    if len(pts) > 1 and abs(pts[-2].x - old.x) < 1:
                        pts[-2] = Point(coord, pts[-2].y)
                else:
                    pts[-1] = Point(old.x, coord)
                    if len(pts) > 1 and abs(pts[-2].y - old.y) < 1:
                        pts[-2] = Point(pts[-2].x, coord)
            e.points[:] = pts

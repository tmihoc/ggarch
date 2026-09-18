"""ggarch state diagram renderer.

Renders a StateView into an SVG state machine diagram by projecting a named
Behaviour from the model.

Layout:
- Each unique participant in the behaviour becomes a state node.
- Directed steps (call/return/async) become transition edges labelled
  trigger [guard] / label.
- Self steps become internal action annotations on the state.
- Layered layout: states are assigned columns by topological depth along
  forward edges (the main flow runs left-to-right); states that share a
  column stack vertically below the chain row.

Routing (ADR-003 decision 10): transition curves are routed strips like
any diagram edge — obstacle-aware search over the other states' boxes
(back edges bow outside the machine as the same
corridor-around-obstacle problem), earlier transitions' strips included,
so parallel transitions offset emergently. Labels ride the curve along-
path (ADR-002 textPath, mirrored legs, above the line) — one label
mechanism across all three view kinds; the opaque background masks are
gone. State boxes adopt the shared shape machinery (the style's
border radius), not a bespoke box.
"""
from __future__ import annotations

import math
import drawsvg as dw
from dataclasses import dataclass, field
from ggarch.model import (
    Behaviour,
    Block,
    GgarchFile,
    Model,
    StateView,
    Step,
    StepKind,
)

from ggarch.presets import resolve_style
from ggarch.geometry import label_geometry, strip_for_edge
from ggarch.layout import Rect
from ggarch.renderer import (
    ANNOTATION_FONT,
    ARROWHEAD_SIZE,
    LABEL_FONT,
    _path_d,
    draw_path_label,
)
from ggarch.router import (
    ROUTE_STROKE_W,
    _route_edge,
    _route_order,
)


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

STATE_W       = 120   # px — default state box width
STATE_H       = 40    # px — default state box height
STATE_GAP_X   = 80    # px — horizontal gap between states in same row
STATE_GAP_Y   = 70    # px — vertical gap between rows
MARGIN        = 30    # px
INIT_R        = 10    # px — initial pseudostate radius


# ---------------------------------------------------------------------------
# Participant collection
# ---------------------------------------------------------------------------

def _collect_states(steps: list) -> list[str]:
    """Return unique participant ids in order of first appearance."""
    seen: list[str] = []
    for item in steps:
        if isinstance(item, Step):
            if item.source != item.target:
                for nid in (item.source, item.target):
                    if nid not in seen:
                        seen.append(nid)
            else:
                # Self step — source is a state
                if item.source not in seen:
                    seen.append(item.source)
        elif isinstance(item, Block):
            for sub in _collect_states(item.body):
                if sub not in seen:
                    seen.append(sub)
            for _, branch in item.else_branches:
                for sub in _collect_states(branch):
                    if sub not in seen:
                        seen.append(sub)
    return seen


@dataclass
class _Transition:
    source: str
    target: str
    label: str   # trigger [guard] / action


def _collect_transitions(steps: list, transitions: list[_Transition]) -> None:
    """Recursively collect directed steps as transitions."""
    for item in steps:
        if isinstance(item, Step) and item.source != item.target:
            parts = []
            if item.trigger:
                parts.append(item.trigger)
            if item.guard:
                parts.append(f"[{item.guard}]")
            if item.label:
                parts.append(f"/ {item.label}")
            transitions.append(_Transition(
                source=item.source,
                target=item.target,
                label=" ".join(parts),
            ))
        elif isinstance(item, Block):
            _collect_transitions(item.body, transitions)
            for _, branch in item.else_branches:
                _collect_transitions(branch, transitions)


def _collect_internal_actions(state_id: str, steps: list) -> list[str]:
    """Collect self-step labels for a given state."""
    actions: list[str] = []
    for item in steps:
        if isinstance(item, Step) and item.source == item.target == state_id:
            actions.append(item.label or item.kind.value)
        elif isinstance(item, Block):
            actions.extend(_collect_internal_actions(state_id, item.body))
            for _, branch in item.else_branches:
                actions.extend(_collect_internal_actions(state_id, branch))
    return actions


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_state(
    view: StateView,
    model: Model,
    dark: bool = False,
) -> str:
    """Render a StateView to an SVG state machine string."""
    behaviour = model.find_behaviour(view.select.behaviour)
    if behaviour is None:
        raise ValueError(
            f"behaviour {view.select.behaviour!r} not found in model {model.name!r}"
        )

    state_ids = _collect_states(behaviour.steps)
    if not state_ids:
        raise ValueError(f"behaviour {behaviour.name!r} has no participants")

    # Filter by participants if specified.
    if view.select.participants:
        state_ids = [s for s in state_ids if s in view.select.participants]

    node_styles = resolve_style(model.style, dark=dark)

    # -- Layered layout ---------------------------------------------------
    # Columns follow topological depth along forward edges (main flow
    # left -> right, matching the previous single-row render for plain
    # chains); branch targets that would share a column stack below the
    # chain row in first-appearance order.
    transitions: list[_Transition] = []
    _collect_transitions(behaviour.steps, transitions)

    layer: dict[str, int] = {}
    for sid in state_ids:
        incoming = [t for t in transitions
                   if t.target == sid and t.source in layer and t.source != sid]
        layer[sid] = (max(layer[t.source] for t in incoming) + 1) if incoming else 0

    # Compact the used columns to consecutive indices.
    used_cols = sorted(set(layer.values()))
    col_remap = {c: i for i, c in enumerate(used_cols)}
    col_of = {sid: col_remap[c] for sid, c in layer.items()}

    slots: dict[int, int] = {}
    slot_of: dict[str, int] = {}
    for sid in state_ids:
        slot_of[sid] = slots.get(col_of[sid], 0)
        slots[col_of[sid]] = slot_of[sid] + 1

    chain_cy = MARGIN + INIT_R * 2 + STATE_GAP_Y + STATE_H / 2
    state_pos: dict[str, tuple[float, float]] = {}  # id -> (cx, cy)
    for sid in state_ids:
        cx = MARGIN + INIT_R * 2 + STATE_GAP_X \
            + col_of[sid] * (STATE_W + STATE_GAP_X) + STATE_W / 2
        cy = chain_cy + slot_of[sid] * (STATE_H + STATE_GAP_Y)
        state_pos[sid] = (cx, cy)

    # -- Edge geometry ----------------------------------------------------
    # Transitions are routed strips (ADR-003): obstacle-aware search
    # over the other states' boxes, earlier transitions' strips included
    # (offsets emergent); labels ride the path (ADR-002). Computed
    # before the canvas so paths and label extents size the drawing.
    actions_of = {sid: _collect_internal_actions(sid, behaviour.steps)
                  for sid in state_ids}
    box_h = {sid: STATE_H + len(a) * 14 for sid, a in actions_of.items()}

    def _state_rect(sid: str) -> Rect:
        cx, cy = state_pos[sid]
        return Rect(cx - STATE_W / 2, cy - STATE_H / 2, STATE_W, box_h[sid])

    def _box_tuple(sid: str):
        r = _state_rect(sid)
        return (r.x, r.y, r.x2, r.y2)

    routed: list[tuple[str, str, str, list[tuple[float, float]]]] = []
    strips_done = []
    ordered = _route_order([
        (t, _state_rect(t.source), _state_rect(t.target))
        for t in transitions
        if t.source != t.target
        and t.source in state_pos and t.target in state_pos
    ])
    for t, src_rect, tgt_rect in ordered:
        obstacles = [(_box_tuple(sid), sid) for sid in state_ids
                     if sid not in (t.source, t.target)]
        pts = _route_edge(
            src_rect, tgt_rect, obstacles, strips_done,
            [_state_rect(t.source), _state_rect(t.target)])
        pts_t = [(p.x, p.y) for p in pts]
        strips_done.append(strip_for_edge(
            pts_t, ROUTE_STROKE_W, "forward", t.label, 0.5,
            owner=f"{t.source}->{t.target}"))
        routed.append((t.source, t.target, t.label, pts_t))

    # Canvas: fit states, the init pseudostate, routed paths and their
    # label extents, with margin.
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    def _extend(x0, y0, x1, y1):
        nonlocal min_x, min_y, max_x, max_y
        min_x = min(min_x, x0); max_x = max(max_x, x1)
        min_y = min(min_y, y0); max_y = max(max_y, y1)

    for sid in state_ids:
        cx, cy = state_pos[sid]
        _extend(cx - STATE_W / 2, cy - STATE_H / 2,
                cx + STATE_W / 2 + 8, cy - STATE_H / 2 + box_h[sid])
    for _s, _t, label, pts_t in routed:
        xs = [p[0] for p in pts_t]
        ys = [p[1] for p in pts_t]
        _extend(min(xs), min(ys), max(xs), max(ys))
        if label:
            lg = label_geometry(pts_t, label)
            _extend(lg.strip[0], lg.strip[1], lg.strip[2], lg.strip[3])

    _extend(MARGIN, MARGIN, MARGIN, MARGIN)
    pad_x = max(0.0, MARGIN - min_x)
    pad_y = max(0.0, MARGIN - min_y)
    w = max_x - min_x + pad_x + MARGIN
    h = max_y - min_y + pad_y + MARGIN

    if pad_x or pad_y:
        state_pos = {s: (cx + pad_x, cy + pad_y)
                     for s, (cx, cy) in state_pos.items()}
        routed = [(s, t, lbl, [(x + pad_x, y + pad_y) for x, y in pts_t])
                  for s, t, lbl, pts_t in routed]

    bg = "#1E1E2E" if dark else "#FFFFFF"
    text_color = "#CDD6F4" if dark else "#333333"
    arrow_color = "#AAAAAA" if dark else "#555555"
    state_fill = "#2A2A3E" if dark else "#F5F5F5"
    state_stroke = "#5555AA" if dark else "#8888CC"

    drawing = dw.Drawing(w, h, origin=(0, 0))
    drawing.append(dw.Rectangle(0, 0, w, h, fill=bg))

    # Arrowhead.
    s = ARROWHEAD_SIZE
    marker = dw.Marker(0, 0, s, s, scale=1, orient="auto", id="st-arrow",
                       refX=s, refY=s/2)
    marker.append(dw.Lines(0, 0, s, s/2, 0, s, fill=arrow_color, close=True))
    drawing.append_def(marker)

    content = dw.Group()

    # Initial pseudostate: filled circle at top-left, arrow to first state.
    init_cx = MARGIN + INIT_R
    init_cy = MARGIN + INIT_R
    content.append(dw.Circle(init_cx, init_cy, INIT_R, fill=arrow_color))
    if state_ids:
        first_cx, first_cy = state_pos[state_ids[0]]
        first_left_x = first_cx - STATE_W / 2
        content.append(dw.Line(
            init_cx, init_cy + INIT_R,
            first_left_x, first_cy,
            stroke=arrow_color, stroke_width=1.5,
            marker_end="url(#st-arrow)",
        ))

    # State boxes.
    for sid in state_ids:
        cx, cy = state_pos[sid]
        x = cx - STATE_W / 2
        y = cy - STATE_H / 2
        node = model.find_node(sid)
        label = node.label if node else sid
        ntype = node.type if node else "default"
        style = node_styles.get(ntype, node_styles.get("default"))

        # Internal actions for this state.
        actions = actions_of[sid]
        bh = STATE_H + len(actions) * 14

        sfill  = style.fill if style and style.fill != "none" else state_fill
        sstroke = style.stroke if style else state_stroke
        # Shared shape machinery: the style's border radius, not a
        # bespoke box (one node, one visual identity).
        srx = style.border_radius if style else 4

        content.append(dw.Rectangle(
            x, y, STATE_W, bh,
            fill=sfill, stroke=sstroke, stroke_width=1.5,
            rx=srx, ry=srx,
        ))
        # State name.
        name_color = style.font_color if style else text_color
        content.append(dw.Text(
            label, 12, cx, cy,
            font_family=LABEL_FONT, fill=name_color,
            text_anchor="middle", dominant_baseline="central",
            font_weight="bold",
        ))
        # Internal actions below the name.
        if actions:
            content.append(dw.Line(
                x, y + STATE_H - 4, x + STATE_W, y + STATE_H - 4,
                stroke=sstroke, stroke_width=0.5,
            ))
            for i, act in enumerate(actions):
                content.append(dw.Text(
                    act, 10, x + 6, y + STATE_H + i * 14 + 6,
                    font_family=ANNOTATION_FONT, fill=text_color,
                    dominant_baseline="hanging",
                ))

    # Transitions (replayed from the routed geometry): the stroke is
    # content — paths first, then labels riding their own strokes.
    for _s, _t, label, pts_t in routed:
        content.append(dw.Path(
            d=_path_d(pts_t), fill="none",
            stroke=arrow_color, stroke_width=1.5,
            marker_end="url(#st-arrow)",
            stroke_linejoin="round",
        ))
    for _s, _t, label, pts_t in routed:
        if not label:
            continue
        draw_path_label(content, pts_t, label, text_color)

    drawing.append(content)
    return drawing.as_svg()


def render_state_both(view: StateView, model: Model) -> tuple[str, str]:
    """Return (light_svg, dark_svg)."""
    return render_state(view, model, dark=False), render_state(view, model, dark=True)

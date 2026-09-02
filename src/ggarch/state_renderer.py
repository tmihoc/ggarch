"""ggarch state diagram renderer.

Renders a StateView into an SVG state machine diagram by projecting a named
Behaviour from the model.

Layout:
- Each unique participant in the behaviour becomes a state node.
- Directed steps (call/return/async) become transition edges labelled
  trigger [guard] / label.
- Self steps become internal action annotations on the state.
- States are laid out left-to-right in order of first appearance.

Produces light and dark SVG strings via render_state() / render_state_both().
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import drawsvg as dw

from ggarch.model import (
    Behaviour,
    Block,
    GgarchFile,
    Model,
    StateView,
    Step,
    StepKind,
)
from ggarch.presets import get_preset, resolve_style
from ggarch.renderer import LABEL_FONT, ANNOTATION_FONT, ARROWHEAD_SIZE


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

STATE_W       = 120   # px — default state box width
STATE_H       = 40    # px — default state box height
STATE_GAP_X   = 80    # px — horizontal gap between states in same row
STATE_GAP_Y   = 70    # px — vertical gap between rows
MARGIN        = 30    # px
INIT_R        = 10    # px — initial pseudostate radius
ARROW_CURVE   = 30    # px — control point offset for curved transitions


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
    preset = get_preset(model.style.extends)

    # Layout: place states in a single row (simple default).
    # For more states, wrap into multiple rows of max 4.
    MAX_PER_ROW = 4
    rows = [state_ids[i:i+MAX_PER_ROW] for i in range(0, len(state_ids), MAX_PER_ROW)]

    state_pos: dict[str, tuple[float, float]] = {}  # id -> (cx, cy)
    for row_idx, row in enumerate(rows):
        for col_idx, sid in enumerate(row):
            cx = MARGIN + INIT_R * 2 + STATE_GAP_X + col_idx * (STATE_W + STATE_GAP_X) + STATE_W / 2
            cy = MARGIN + INIT_R * 2 + STATE_GAP_Y + row_idx * (STATE_H + STATE_GAP_Y) + STATE_H / 2
            state_pos[sid] = (cx, cy)

    # Compute drawing dimensions.
    all_cx = [p[0] for p in state_pos.values()]
    all_cy = [p[1] for p in state_pos.values()]
    w = max(all_cx) + STATE_W / 2 + MARGIN
    h = max(all_cy) + STATE_H / 2 + MARGIN + 30  # extra for initial arrow

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
        actions = _collect_internal_actions(sid, behaviour.steps)
        box_h = STATE_H + len(actions) * 14

        sfill  = style.fill if style and style.fill != "none" else state_fill
        sstroke = style.stroke if style else state_stroke

        content.append(dw.Rectangle(
            x, y, STATE_W, box_h,
            fill=sfill, stroke=sstroke, stroke_width=1.5,
            rx=8, ry=8,
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

    # Transitions.
    transitions: list[_Transition] = []
    _collect_transitions(behaviour.steps, transitions)

    # Count edges between the same pair to offset curves.
    pair_count: dict[tuple[str, str], int] = {}

    for t in transitions:
        if t.source not in state_pos or t.target not in state_pos:
            continue
        sx, sy = state_pos[t.source]
        tx, ty = state_pos[t.target]
        key = (min(t.source, t.target), max(t.source, t.target))
        offset_idx = pair_count.get(key, 0)
        pair_count[key] = offset_idx + 1

        # Compute anchor points on state box edges.
        dx, dy = tx - sx, ty - sy
        dist = math.hypot(dx, dy) or 1

        # Self-transition: skip (handled as internal actions above).
        if t.source == t.target:
            continue

        # Exit/entry faces based on direction.
        if abs(dx) >= abs(dy):
            src_pt = (sx + (STATE_W/2 if dx > 0 else -STATE_W/2), sy)
            tgt_pt = (tx + (-STATE_W/2 if dx > 0 else STATE_W/2), ty)
        else:
            src_pt = (sx, sy + (STATE_H/2 if dy > 0 else -STATE_H/2))
            tgt_pt = (tx, ty + (-STATE_H/2 if dy > 0 else STATE_H/2))

        # Curve offset for parallel edges.
        curve_off = (offset_idx + 1) * ARROW_CURVE * (1 if offset_idx % 2 == 0 else -1)
        mid_x = (src_pt[0] + tgt_pt[0]) / 2
        mid_y = (src_pt[1] + tgt_pt[1]) / 2
        # Perpendicular offset.
        perp_x = -dy / dist * curve_off
        perp_y =  dx / dist * curve_off
        cp_x = mid_x + perp_x
        cp_y = mid_y + perp_y

        path_d = (f"M {src_pt[0]:.1f} {src_pt[1]:.1f} "
                  f"Q {cp_x:.1f} {cp_y:.1f} {tgt_pt[0]:.1f} {tgt_pt[1]:.1f}")
        content.append(dw.Path(
            d=path_d, fill="none",
            stroke=arrow_color, stroke_width=1.5,
            marker_end="url(#st-arrow)",
        ))

        # Transition label at midpoint of curve.
        if t.label:
            lx = (src_pt[0] + 2*cp_x + tgt_pt[0]) / 4
            ly = (src_pt[1] + 2*cp_y + tgt_pt[1]) / 4
            lx += perp_x / abs(curve_off) * 12 if curve_off else 0
            ly += perp_y / abs(curve_off) * 12 if curve_off else -12
            content.append(dw.Text(
                t.label, 10, lx, ly,
                font_family=ANNOTATION_FONT, fill=text_color,
                text_anchor="middle", dominant_baseline="central",
            ))

    drawing.append(content)
    return drawing.as_svg()


def render_state_both(view: StateView, model: Model) -> tuple[str, str]:
    """Return (light_svg, dark_svg)."""
    return render_state(view, model, dark=False), render_state(view, model, dark=True)

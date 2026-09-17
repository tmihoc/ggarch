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
  column stack vertically below the chain row. Back edges (to an earlier
  column) bow outside the machine -- above the chain when they leave the
  chain row, below when they leave a deeper row -- so return paths never
  cross the forward labels.

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

    # -- Layered layout ---------------------------------------------------
    # Columns follow topological depth along forward edges (main flow
    # left -> right, matching the previous single-row render for plain
    # chains); branch targets that would share a column stack below the
    # chain row in first-appearance order. Back edges (to an earlier
    # column) are routed outside the machine in the draw pass.
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
    # Computed before the canvas so back-edge bows and label extents can
    # size the drawing. Stored as data; the draw pass replays it.
    actions_of = {sid: _collect_internal_actions(sid, behaviour.steps)
                  for sid in state_ids}
    box_h = {sid: STATE_H + len(a) * 14 for sid, a in actions_of.items()}

    pair_count: dict[tuple[str, str], int] = {}
    # (src_pt, tgt_pt, cp, label, lx, ly)
    edge_geo: list[tuple[tuple, tuple, tuple, str, float, float]] = []
    min_x = min_y = float("inf")
    max_x = max_y = float("-inf")

    for t in transitions:
        if t.source == t.target:
            continue  # self-transitions render as internal actions
        if t.source not in state_pos or t.target not in state_pos:
            continue
        sx, sy = state_pos[t.source]
        tx, ty = state_pos[t.target]
        dx, dy = tx - sx, ty - sy
        dist = math.hypot(dx, dy) or 1.0

        # Exit/entry faces based on dominant direction.
        if abs(dx) >= abs(dy):
            src_pt = (sx + (STATE_W/2 if dx > 0 else -STATE_W/2), sy)
            tgt_pt = (tx + (-STATE_W/2 if dx > 0 else STATE_W/2), ty)
        else:
            src_pt = (sx, sy + (STATE_H/2 if dy > 0 else -STATE_H/2))
            tgt_pt = (tx, ty + (-STATE_H/2 if dy > 0 else STATE_H/2))

        mid_x = (src_pt[0] + tgt_pt[0]) / 2
        mid_y = (src_pt[1] + tgt_pt[1]) / 2
        perp_hat = (-dy / dist, dx / dist)

        if col_of[t.target] >= col_of[t.source]:
            # Forward edge: parallel edges alternate sides of the chord.
            key = (min(t.source, t.target), max(t.source, t.target))
            offset_idx = pair_count.get(key, 0)
            pair_count[key] = offset_idx + 1
            off = (offset_idx + 1) * ARROW_CURVE * (1 if offset_idx % 2 == 0 else -1)
        else:
            # Back edge: bow outside the machine -- above the chain when
            # it leaves the chain row, below when it leaves a deeper row.
            off = min(max(dist * 0.18, 48.0), 150.0)
            up = slot_of[t.source] == 0
            if (perp_hat[1] > 0) if up else (perp_hat[1] < 0):
                off = -off

        cp = (mid_x + perp_hat[0] * off, mid_y + perp_hat[1] * off)

        # Label at the curve midpoint, pushed clear of the curve's flank:
        # the bow's apex sits |off|/2 from the chord at the midpoint, and a
        # horizontal label on a diagonal chord extends further along the
        # push direction by half its width * sin(chord angle).
        half_w = len(t.label) * 3.1 if t.label else 0.0  # ~6.2px/char, 10px font
        theta = math.atan2(abs(dy), abs(dx))
        push = abs(off) / 2 + 10 + half_w * math.sin(theta)
        push_dir = 1 if off >= 0 else -1
        lx = (src_pt[0] + 2*cp[0] + tgt_pt[0]) / 4 + perp_hat[0] * push_dir * push
        ly = (src_pt[1] + 2*cp[1] + tgt_pt[1]) / 4 + perp_hat[1] * push_dir * push

        # Sample the curve and label background for extents.
        for i in range(9):
            tt = i / 8
            bx = (1-tt)*(1-tt)*src_pt[0] + 2*(1-tt)*tt*cp[0] + tt*tt*tgt_pt[0]
            by = (1-tt)*(1-tt)*src_pt[1] + 2*(1-tt)*tt*cp[1] + tt*tt*tgt_pt[1]
            min_x = min(min_x, bx); max_x = max(max_x, bx)
            min_y = min(min_y, by); max_y = max(max_y, by)
        if t.label:
            min_x = min(min_x, lx - half_w - 3); max_x = max(max_x, lx + half_w + 3)
            min_y = min(min_y, ly - 8);          max_y = max(max_y, ly + 8)

        edge_geo.append((src_pt, tgt_pt, cp, t.label, lx, ly))

    # State box extents (boxes grow downward with internal actions; the
    # state name sits at cy, so the top edge is always STATE_H/2 above).
    for sid in state_ids:
        cx, cy = state_pos[sid]
        min_x = min(min_x, cx - STATE_W / 2)
        max_x = max(max_x, cx + STATE_W / 2 + 8)  # internal action text
        min_y = min(min_y, cy - STATE_H / 2)
        max_y = max(max_y, cy - STATE_H / 2 + box_h[sid])

    # Canvas: fit states, the init pseudostate, bows and labels, with margin.
    min_x = min(min_x, MARGIN)
    min_y = min(min_y, MARGIN)
    pad_x = max(0.0, MARGIN - min_x)
    pad_y = max(0.0, MARGIN - min_y)
    w = max_x - min_x + pad_x + MARGIN
    h = max_y - min_y + pad_y + MARGIN

    if pad_x or pad_y:
        state_pos = {s: (cx + pad_x, cy + pad_y)
                     for s, (cx, cy) in state_pos.items()}
        edge_geo = [
            ((sp[0] + pad_x, sp[1] + pad_y), (tp[0] + pad_x, tp[1] + pad_y),
             (c[0] + pad_x, c[1] + pad_y), lbl, lx + pad_x, ly + pad_y)
            for sp, tp, c, lbl, lx, ly in edge_geo
        ]

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
    # Transitions (replayed from the precomputed geometry). All paths
    # first, then labels: each label carries an opaque background so a
    # crossing edge (e.g. a return path) never strikes through the text.
    for src_pt, tgt_pt, cp, label, lx, ly in edge_geo:
        path_d = (f"M {src_pt[0]:.1f} {src_pt[1]:.1f} "
                  f"Q {cp[0]:.1f} {cp[1]:.1f} {tgt_pt[0]:.1f} {tgt_pt[1]:.1f}")
        content.append(dw.Path(
            d=path_d, fill="none",
            stroke=arrow_color, stroke_width=1.5,
            marker_end="url(#st-arrow)",
        ))
    for src_pt, tgt_pt, cp, label, lx, ly in edge_geo:
        if not label:
            continue
        half_w = len(label) * 3.1
        content.append(dw.Rectangle(
            lx - half_w - 3, ly - 8, half_w * 2 + 6, 16,
            fill=bg, stroke="none",
        ))
        content.append(dw.Text(
            label, 10, lx, ly,
            font_family=ANNOTATION_FONT, fill=text_color,
            text_anchor="middle", dominant_baseline="central",
        ))

    drawing.append(content)
    return drawing.as_svg()


def render_state_both(view: StateView, model: Model) -> tuple[str, str]:
    """Return (light_svg, dark_svg)."""
    return render_state(view, model, dark=False), render_state(view, model, dark=True)

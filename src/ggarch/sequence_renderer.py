"""ggarch sequence diagram renderer.

Renders a SequenceView into SVG by projecting a named Behaviour from the model.

Layout:
- Participants run left-to-right as lifeline columns.
- Time flows top-to-bottom.
- Each step occupies a fixed row height.
- loop/alt/par blocks are rectangular regions drawn behind the steps they contain.

Produces light and dark SVG strings via render_sequence() / render_sequence_both().
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import drawsvg as dw

from ggarch.model import (
    Behaviour,
    Block,
    GgarchFile,
    Lifecycle,
    Model,
    Node,
    SequenceView,
    Step,
    StepKind,
)
from ggarch.presets import get_preset, resolve_style
from ggarch.renderer import ANNOTATION_FONT, ARROWHEAD_SIZE, LABEL_FONT


# ---------------------------------------------------------------------------
# Layout constants
# ---------------------------------------------------------------------------

LIFELINE_WIDTH     = 120   # px — width of each lifeline column
LIFELINE_HEADER_H  = 40    # px — height of lifeline header box
LIFELINE_SPACING   = 40    # px — horizontal gap between lifeline columns
STEP_HEIGHT        = 36    # px — vertical space per step row
BLOCK_PAD          = 8     # px — padding inside loop/alt regions
MARGIN_TOP         = 20    # px
MARGIN_SIDE        = 20    # px
MARGIN_BOTTOM      = 30    # px
SELF_LOOP_W        = 20    # px — width of self-call loop


# ---------------------------------------------------------------------------
# Participant ordering
# ---------------------------------------------------------------------------

def _ordered_participants(
    behaviour: Behaviour,
    participants_filter: list[str],
    model: Model,
) -> list[str]:
    """Return participant ids in order of first appearance in the behaviour."""
    seen: list[str] = []
    _collect_participants_ordered(behaviour.steps, seen)
    # Apply filter if given.
    if participants_filter:
        seen = [p for p in seen if p in participants_filter]
    # Deduplicate preserving order.
    result: list[str] = []
    for p in seen:
        if p not in result:
            result.append(p)
    return result


def _collect_participants_ordered(steps, seen: list[str]) -> None:
    for item in steps:
        if isinstance(item, Step):
            if item.source not in seen:
                seen.append(item.source)
            if item.target not in seen:
                seen.append(item.target)
            _collect_participants_ordered(item.body, seen)
        elif isinstance(item, Block):
            _collect_participants_ordered(item.body, seen)
            for _, branch in item.else_branches:
                _collect_participants_ordered(branch, seen)


# ---------------------------------------------------------------------------
# Step counting (for layout height)
# ---------------------------------------------------------------------------

def _count_rows(steps) -> int:
    """Count the number of visible rows in a step list."""
    count = 0
    for item in steps:
        if isinstance(item, Step):
            count += 1
        elif isinstance(item, Block):
            count += _count_rows(item.body)
            for _, branch in item.else_branches:
                count += _count_rows(branch) + 1  # +1 for else label row
    return count


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def render_sequence(
    view: SequenceView,
    model: Model,
    dark: bool = False,
) -> str:
    """Render a SequenceView to an SVG string."""
    behaviour = model.find_behaviour(view.select.behaviour)
    if behaviour is None:
        raise ValueError(
            f"behaviour {view.select.behaviour!r} not found in model {model.name!r}"
        )

    participants = _ordered_participants(
        behaviour, view.select.participants, model
    )
    if not participants:
        raise ValueError(f"behaviour {behaviour.name!r} has no participants")

    preset = get_preset(model.style.extends)
    node_styles = resolve_style(model.style, dark=dark)

    # Geometry.
    n = len(participants)
    total_rows = _count_rows(behaviour.steps)

    col_step  = LIFELINE_WIDTH + LIFELINE_SPACING
    diagram_w = MARGIN_SIDE * 2 + n * col_step - LIFELINE_SPACING
    lifeline_h = LIFELINE_HEADER_H + total_rows * STEP_HEIGHT + MARGIN_BOTTOM
    diagram_h  = MARGIN_TOP + lifeline_h + LIFELINE_HEADER_H

    # Column centre positions.
    col_cx: dict[str, float] = {}
    for i, pid in enumerate(participants):
        col_cx[pid] = MARGIN_SIDE + i * col_step + LIFELINE_WIDTH / 2

    bg = "#1E1E2E" if dark else "#FFFFFF"
    drawing = dw.Drawing(diagram_w, diagram_h, origin=(0, 0))
    drawing.append(dw.Rectangle(0, 0, diagram_w, diagram_h, fill=bg))

    # Arrowhead marker.
    _add_sequence_arrowhead(drawing, dark)

    content = dw.Group()

    # Lifeline headers and vertical dashed lines.
    for pid in participants:
        cx = col_cx[pid]
        node = model.find_node(pid)
        label = node.label if node else pid
        lifecycle = node.lifecycle if node else Lifecycle.PERSISTENT
        style = node_styles.get(
            node.type if node else "default",
            node_styles.get("default"),
        )

        # Header box — dashed border for init lifecycle.
        rect_kwargs: dict = dict(
            fill=style.fill if style.fill != "none" else ("#2A2A3E" if dark else "#F5F5F5"),
            stroke=style.stroke,
            stroke_width=1,
            rx=4, ry=4,
        )
        if lifecycle == Lifecycle.INIT:
            rect_kwargs["stroke_dasharray"] = "4,3"

        content.append(dw.Rectangle(
            cx - LIFELINE_WIDTH / 2, MARGIN_TOP,
            LIFELINE_WIDTH, LIFELINE_HEADER_H,
            **rect_kwargs,
        ))
        # Header label.
        text_color = style.font_color or ("#CDD6F4" if dark else "#333333")
        content.append(dw.Text(
            label, 12,
            cx, MARGIN_TOP + LIFELINE_HEADER_H / 2,
            font_family=LABEL_FONT,
            fill=text_color,
            text_anchor="middle",
            dominant_baseline="central",
        ))
        # Vertical lifeline — visually distinct from arrows: thinner, lighter.
        lifeline_top = MARGIN_TOP + LIFELINE_HEADER_H
        lifeline_bot = MARGIN_TOP + lifeline_h - MARGIN_BOTTOM
        line_color = "#666666" if dark else "#CCCCCC"
        content.append(dw.Line(
            cx, lifeline_top, cx, lifeline_bot,
            stroke=line_color,
            stroke_width=1,
            stroke_dasharray="6,4",
        ))

    # Steps — rendered top-down, tracking current y offset.
    ctx = _RenderCtx(
        col_cx=col_cx,
        dark=dark,
        text_color="#CDD6F4" if dark else "#333333",
        arrow_color="#AAAAAA" if dark else "#555555",
        block_fill=("#2A2A40" if dark else "#F0F4FF"),
        block_stroke=("#5555AA" if dark else "#8888CC"),
    )
    y_start = MARGIN_TOP + LIFELINE_HEADER_H + STEP_HEIGHT / 2
    _render_steps(content, behaviour.steps, y_start, ctx)

    # Closing boxes at the bottom of each lifeline — same style as headers.
    lifeline_bot_y = MARGIN_TOP + lifeline_h - MARGIN_BOTTOM
    for pid in participants:
        cx   = col_cx[pid]
        node = model.find_node(pid)
        label = node.label if node else pid
        lifecycle = node.lifecycle if node else Lifecycle.PERSISTENT
        style = node_styles.get(
            node.type if node else "default",
            node_styles.get("default"),
        )
        rect_kwargs: dict = dict(
            fill=style.fill if style.fill != "none" else ("#2A2A3E" if dark else "#F5F5F5"),
            stroke=style.stroke,
            stroke_width=1,
            rx=4, ry=4,
        )
        if lifecycle == Lifecycle.INIT:
            rect_kwargs["stroke_dasharray"] = "4,3"
        content.append(dw.Rectangle(
            cx - LIFELINE_WIDTH / 2, lifeline_bot_y,
            LIFELINE_WIDTH, LIFELINE_HEADER_H,
            **rect_kwargs,
        ))
        text_color = style.font_color or ("#CDD6F4" if dark else "#333333")
        content.append(dw.Text(
            label, 12,
            cx, lifeline_bot_y + LIFELINE_HEADER_H / 2,
            font_family=LABEL_FONT,
            fill=text_color,
            text_anchor="middle",
            dominant_baseline="central",
        ))
    drawing.append(content)
    return drawing.as_svg()


def render_sequence_both(
    view: SequenceView,
    model: Model,
) -> tuple[str, str]:
    """Return (light_svg, dark_svg)."""
    return (
        render_sequence(view, model, dark=False),
        render_sequence(view, model, dark=True),
    )


# ---------------------------------------------------------------------------
# Arrowhead
# ---------------------------------------------------------------------------

def _add_sequence_arrowhead(drawing: dw.Drawing, dark: bool) -> None:
    color = "#AAAAAA" if dark else "#555555"
    s = ARROWHEAD_SIZE
    marker = dw.Marker(0, 0, s, s, scale=1, orient="auto",
                       id="seq-arrow", refX=s, refY=s / 2)
    marker.append(dw.Lines(0, 0, s, s / 2, 0, s, fill=color, close=True))
    drawing.append_def(marker)

    # Open arrowhead for async.
    marker_open = dw.Marker(0, 0, s, s, scale=1, orient="auto",
                            id="seq-arrow-open", refX=s, refY=s / 2)
    marker_open.append(dw.Lines(
        0, 0, s, s / 2, 0, s,
        fill="none", stroke=color, stroke_width=1.5, close=False,
    ))
    drawing.append_def(marker_open)


# ---------------------------------------------------------------------------
# Rendering context
# ---------------------------------------------------------------------------

@dataclass
class _RenderCtx:
    col_cx: dict[str, float]
    dark: bool
    text_color: str
    arrow_color: str
    block_fill: str
    block_stroke: str


# ---------------------------------------------------------------------------
# Step rendering
# ---------------------------------------------------------------------------

def _render_steps(
    g: dw.Group,
    steps: list,
    y_start: float,
    ctx: _RenderCtx,
) -> float:
    """Render steps starting at y_start; return the y after the last step."""
    y = y_start
    for item in steps:
        if isinstance(item, Step):
            y = _render_step(g, item, y, ctx)
        elif isinstance(item, Block):
            y = _render_block(g, item, y, ctx)
    return y


def _render_step(
    g: dw.Group,
    step: Step,
    y: float,
    ctx: _RenderCtx,
) -> float:
    src_cx = ctx.col_cx.get(step.source)
    tgt_cx = ctx.col_cx.get(step.target)

    if src_cx is None or tgt_cx is None:
        return y + STEP_HEIGHT  # skip — participant not in layout

    if step.source == step.target:
        # Self-call: small loop on the right.
        _render_self_step(g, step, src_cx, y, ctx)
    elif step.kind == StepKind.RETURN:
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=True, arrowhead="seq-arrow")
    elif step.kind == StepKind.ASYNC:
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=False, arrowhead="seq-arrow-open")
    else:
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=False, arrowhead="seq-arrow")

    return y + STEP_HEIGHT


def _render_arrow(
    g: dw.Group,
    x1: float,
    x2: float,
    y: float,
    label: str,
    ctx: _RenderCtx,
    dashed: bool = False,
    arrowhead: str = "seq-arrow",
) -> None:
    line_kwargs: dict = dict(
        stroke=ctx.arrow_color,
        stroke_width=1,
        marker_end=f"url(#{arrowhead})",
    )
    if dashed:
        line_kwargs["stroke_dasharray"] = "5,3"

    g.append(dw.Line(x1, y, x2, y, **line_kwargs))

    if label:
        mx = (x1 + x2) / 2
        label_bg = "#1E1E2E" if ctx.dark else "#FFFFFF"
        lw = len(label) * 6.5
        # Pill sits 2px above the line so its bottom edge doesn't touch it.
        g.append(dw.Rectangle(
            mx - lw / 2 - 3, y - 15, lw + 6, 13,
            fill=label_bg, stroke="none", fill_opacity=1,
        ))
        g.append(dw.Text(
            label, 11, mx, y - 8,
            font_family=LABEL_FONT,
            fill=ctx.text_color,
            text_anchor="middle",
            dominant_baseline="central",
        ))


def _render_self_step(
    g: dw.Group,
    step: Step,
    cx: float,
    y: float,
    ctx: _RenderCtx,
) -> None:
    """Self-call: rounded rectangular loop on the right of the lifeline."""
    r   = 6       # corner radius
    w   = SELF_LOOP_W
    h   = STEP_HEIGHT * 0.6
    x0  = cx      # left edge (on lifeline)
    x1b = cx + w  # right edge
    y0  = y
    y1b = y + h
    # Path: start at (x0, y0), go right, curve down-right, go down,
    # curve down-left, go left back to lifeline.
    d = (
        f"M {x0},{y0} "
        f"L {x1b - r},{y0} "
        f"Q {x1b},{y0} {x1b},{y0 + r} "
        f"L {x1b},{y1b - r} "
        f"Q {x1b},{y1b} {x1b - r},{y1b} "
        f"L {x0},{y1b}"
    )
    g.append(dw.Path(
        d=d,
        fill="none",
        stroke=ctx.arrow_color,
        stroke_width=1,
        marker_end="url(#seq-arrow)",
    ))
    if step.label:
        mx = cx + w / 2
        label_bg = "#1E1E2E" if ctx.dark else "#FFFFFF"
        lw = len(step.label) * 6.5
        g.append(dw.Rectangle(
            mx - lw / 2 - 3, y - 15, lw + 6, 13,
            fill=label_bg, stroke="none", fill_opacity=1,
        ))
        g.append(dw.Text(
            step.label, 11, mx, y - 8,
            font_family=LABEL_FONT,
            fill=ctx.text_color,
            text_anchor="middle",
            dominant_baseline="central",
        ))


def _render_block(
    g: dw.Group,
    block: Block,
    y_start: float,
    ctx: _RenderCtx,
) -> float:
    """Render a loop/alt/par block with a shaded region and corner label."""
    # Measure how many rows the block body occupies.
    body_rows = _count_rows(block.body)
    else_rows = sum(_count_rows(b) + 1 for _, b in block.else_branches)
    total_rows = body_rows + else_rows
    block_h = total_rows * STEP_HEIGHT + BLOCK_PAD * 2

    # Find leftmost and rightmost lifeline x.
    all_cx = list(ctx.col_cx.values())
    min_x = min(all_cx) - LIFELINE_WIDTH / 2 - 4
    max_x = max(all_cx) + LIFELINE_WIDTH / 2 + 4
    block_w = max_x - min_x

    # Background region.
    g.append(dw.Rectangle(
        min_x, y_start - BLOCK_PAD,
        block_w, block_h,
        fill=ctx.block_fill,
        stroke=ctx.block_stroke,
        stroke_width=1,
        rx=4, ry=4,
        fill_opacity=0.4,
    ))
    # Corner label: kind + condition.
    kind_label = f"[{block.kind}] {block.label}" if block.label else f"[{block.kind}]"
    g.append(dw.Text(
        kind_label, 10,
        min_x + 6, y_start - BLOCK_PAD + 4,
        font_family=ANNOTATION_FONT,
        fill=ctx.block_stroke,
        dominant_baseline="hanging",
    ))

    y = y_start
    y = _render_steps(g, block.body, y, ctx)

    # Else branches.
    for else_label, else_steps in block.else_branches:
        # Divider line.
        g.append(dw.Line(
            min_x, y, max_x, y,
            stroke=ctx.block_stroke, stroke_width=1,
            stroke_dasharray="4,3",
        ))
        g.append(dw.Text(
            f"[else] {else_label}" if else_label else "[else]",
            10, min_x + 6, y + 4,
            font_family=ANNOTATION_FONT,
            fill=ctx.block_stroke,
            dominant_baseline="hanging",
        ))
        y += STEP_HEIGHT
        y = _render_steps(g, else_steps, y, ctx)

    return y

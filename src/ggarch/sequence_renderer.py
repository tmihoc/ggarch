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
LIFELINE_HEADER_H  = 40    # px — single-line header height; extended per diagram
LIFELINE_LINE_H    = 16    # px — line height inside a header label
LIFELINE_SPACING   = 60    # px — horizontal gap between lifeline columns
STEP_HEIGHT        = 36    # px — vertical space per step row
BLOCK_PAD          = 8     # px — padding inside loop/alt/opt/par regions
MARGIN_TOP         = 20    # px
MARGIN_SIDE        = 30    # px
MARGIN_BOTTOM      = 30    # px
SELF_LOOP_W        = 20    # px — width of self-call loop
ACTIVATION_W       = 10    # px — width of activation bar on lifeline


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
            if item.kind == "par":
                # par: each branch's rows are stacked sequentially, plus a
                # separator row between branches.
                count += _count_rows(item.body)
                for _, branch in item.else_branches:
                    count += _count_rows(branch) + 1  # +1 for separator
            else:
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

    # Header height: accommodate the tallest multi-line label.
    max_lines = max(
        (len((model.find_node(pid).label if model.find_node(pid) else pid).split("\\n"))
         for pid in participants),
        default=1,
    )
    header_h = max(LIFELINE_HEADER_H, 12 + max_lines * LIFELINE_LINE_H)

    col_step  = LIFELINE_WIDTH + LIFELINE_SPACING
    diagram_w = MARGIN_SIDE * 2 + n * col_step - LIFELINE_SPACING + SELF_LOOP_W + 100
    lifeline_h = header_h + total_rows * STEP_HEIGHT + MARGIN_BOTTOM
    diagram_h  = MARGIN_TOP + lifeline_h + header_h

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
            LIFELINE_WIDTH, header_h,
            **rect_kwargs,
        ))
        # Header label — split on \n.
        text_color = style.font_color or ("#CDD6F4" if dark else "#333333")
        lines = label.split("\\n")
        lh = LIFELINE_LINE_H
        total_text_h = len(lines) * lh
        start_y = MARGIN_TOP + header_h / 2 - total_text_h / 2 + lh * 0.5
        for i, line in enumerate(lines):
            content.append(dw.Text(
                line, 12, cx, start_y + i * lh,
                font_family=LABEL_FONT,
                fill=text_color,
                text_anchor="middle",
                dominant_baseline="central",
            ))
        # Vertical lifeline.
        lifeline_top = MARGIN_TOP + header_h
        lifeline_bot = MARGIN_TOP + lifeline_h - MARGIN_BOTTOM
        line_color = "#666666" if dark else "#CCCCCC"
        content.append(dw.Line(
            cx, lifeline_top, cx, lifeline_bot,
            stroke=line_color,
            stroke_width=1,
            stroke_dasharray="6,4",
        ))

    # Steps — rendered top-down, tracking current y offset.
    # bars_group is appended to drawing first so activation bars appear
    # behind the arrow lines.
    bars_group = dw.Group()
    ctx = _RenderCtx(
        col_cx=col_cx,
        dark=dark,
        text_color="#CDD6F4" if dark else "#333333",
        arrow_color="#AAAAAA" if dark else "#555555",
        block_fill=("#2A2A40" if dark else "#F0F4FF"),
        block_stroke=("#5555AA" if dark else "#8888CC"),
        bars_group=bars_group,
        activation_stack=[],
        bg="#1E1E2E" if dark else "#FFFFFF",
    )
    content.append(bars_group)  # append before steps so bars paint behind arrows
    y_start = MARGIN_TOP + header_h + int(STEP_HEIGHT * 1.5)
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
            LIFELINE_WIDTH, header_h,
            **rect_kwargs,
        ))
        text_color = style.font_color or ("#CDD6F4" if dark else "#333333")
        lines = label.split("\\n")
        lh = LIFELINE_LINE_H
        total_text_h = len(lines) * lh
        start_y = lifeline_bot_y + header_h / 2 - total_text_h / 2 + lh * 0.5
        for i, line in enumerate(lines):
            content.append(dw.Text(
                line, 12, cx, start_y + i * lh,
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
    bars_group: dw.Group         # group for activation bars (drawn behind arrows)
    activation_stack: list       # [(lifeline_id, open_y), ...]
    bg: str                      # canvas background (masks self-call labels)


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
        _render_self_step(g, step, src_cx, y, ctx)
    elif step.kind == StepKind.CALL:
        # Push activation bar onto the target lifeline.
        ctx.activation_stack.append((step.target, y))
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=False, arrowhead="seq-arrow")
    elif step.kind == StepKind.RETURN:
        # Close the matching activation bar if one is open.
        _close_activation(ctx, step.source, y)
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=True, arrowhead="seq-arrow")
    elif step.kind == StepKind.ASYNC:
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=False, arrowhead="seq-arrow-open")
    else:
        _render_arrow(g, src_cx, tgt_cx, y, step.label, ctx,
                      dashed=False, arrowhead="seq-arrow")

    return y + STEP_HEIGHT


def _close_activation(ctx: _RenderCtx, lifeline_id: str, close_y: float) -> None:
    """Draw an activation bar if there is an open call on lifeline_id."""
    # Search the stack from the top for the most recent open call to this lifeline.
    for i in range(len(ctx.activation_stack) - 1, -1, -1):
        lid, open_y = ctx.activation_stack[i]
        if lid == lifeline_id:
            ctx.activation_stack.pop(i)
            cx = ctx.col_cx.get(lifeline_id)
            if cx is None:
                return
            bar_x = cx - ACTIVATION_W / 2
            bar_y = open_y
            bar_h = close_y - open_y
            if bar_h < 4:
                bar_h = 4
            bar_fill  = "#CCCCEE" if not ctx.dark else "#334466"
            bar_stroke = ctx.block_stroke
            ctx.bars_group.append(dw.Rectangle(
                bar_x, bar_y, ACTIVATION_W, bar_h,
                fill=bar_fill, stroke=bar_stroke, stroke_width=1,
            ))
            return


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
        CHAR_W = 5.5  # px at 11px font
        max_chars = max(int(abs(x2 - x1) * 0.85 / CHAR_W), 10)
        raw_lines = label.split("\\n")
        wrapped: list[str] = []
        for raw in raw_lines:
            words = raw.split()
            if not words:
                wrapped.append("")
                continue
            cur = words[0]
            for w in words[1:]:
                if len(cur) + 1 + len(w) <= max_chars:
                    cur += " " + w
                else:
                    wrapped.append(cur)
                    cur = w
            wrapped.append(cur)
        lh = 13
        total_h = lh * len(wrapped)
        start_y = (y - 14) - total_h / 2 + lh * 0.5
        for i, line in enumerate(wrapped):
            g.append(dw.Text(
                line, 11, mx, start_y + i * lh,
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
    """Self-call: compact rounded loop on the right; label beside it."""
    r   = 5        # corner radius
    w   = SELF_LOOP_W
    h   = r * 2 + 4
    x0  = cx
    x1b = cx + w
    y0  = y - h / 2
    y1b = y0 + h
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
        # Label to the right of the loop, vertically centred on it (the
        # UML convention for self-messages). A centred label straddles
        # the lifeline and its activation bar; a long label can still
        # reach a neighbouring lifeline, so an opaque background masks
        # any strike.
        label_w = len(step.label) * 6
        bg_x = x1b + 4
        g.append(dw.Rectangle(
            bg_x, y - 8, label_w + 6, 16,
            fill=ctx.bg, stroke="none",
        ))
        g.append(dw.Text(
            step.label, 11, bg_x + 3, y,
            font_family=LABEL_FONT,
            fill=ctx.text_color,
            text_anchor="start",
            dominant_baseline="central",
        ))


def _render_block(
    g: dw.Group,
    block: Block,
    y_start: float,
    ctx: _RenderCtx,
) -> float:
    """Render a loop/alt/opt/par block."""
    if block.kind == "par":
        return _render_par_block(g, block, y_start, ctx)

    # loop / alt / opt — rectangular shaded region.
    body_rows = _count_rows(block.body)
    else_rows = sum(_count_rows(b) + 1 for _, b in block.else_branches)
    total_rows = body_rows + else_rows
    block_h = total_rows * STEP_HEIGHT + BLOCK_PAD * 2

    all_cx = list(ctx.col_cx.values())
    min_x = min(all_cx) - LIFELINE_WIDTH / 2 - 4
    max_x = max(all_cx) + LIFELINE_WIDTH / 2 + 4
    block_w = max_x - min_x

    g.append(dw.Rectangle(
        min_x, y_start - BLOCK_PAD,
        block_w, block_h,
        fill=ctx.block_fill,
        stroke=ctx.block_stroke,
        stroke_width=1,
        rx=4, ry=4,
        fill_opacity=0.4,
    ))
    kind_label = f"[{block.kind}] {block.label}" if block.label else f"[{block.kind}]"
    # Tab sits just above the top border of the region, attached to it.
    tab_w = len(kind_label) * 5.5 + 10
    tab_h = 14
    tab_y = y_start - BLOCK_PAD - tab_h + 1  # bottom of tab = top of region border
    g.append(dw.Rectangle(
        min_x, tab_y, tab_w, tab_h,
        fill=ctx.block_stroke, stroke="none", rx=2, ry=2,
        fill_opacity=0.9,
    ))
    g.append(dw.Text(
        kind_label, 9,
        min_x + 5, tab_y + tab_h / 2,
        font_family=ANNOTATION_FONT,
        fill="#FFFFFF",
        dominant_baseline="central",
    ))

    y = y_start
    y = _render_steps(g, block.body, y, ctx)

    for else_label, else_steps in block.else_branches:
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


def _render_par_block(
    g: dw.Group,
    block: Block,
    y_start: float,
    ctx: _RenderCtx,
) -> float:
    """Render a par block as stacked parallel lanes separated by dashed lines."""
    # Collect all branches: the main body counts as branch 0.
    # (par has no else_branches in the current model; body holds all steps
    # between the braces. A future multi-branch par would use else_branches.)
    branches: list[list] = [block.body]
    for _, b in block.else_branches:
        branches.append(b)

    total_rows = sum(_count_rows(br) for br in branches)
    total_rows += len(branches) - 1  # separator rows between branches
    block_h = total_rows * STEP_HEIGHT + BLOCK_PAD * 2

    all_cx = list(ctx.col_cx.values())
    min_x = min(all_cx) - LIFELINE_WIDTH / 2 - 4
    max_x = max(all_cx) + LIFELINE_WIDTH / 2 + 4
    block_w = max_x - min_x

    # Outer shaded region.
    par_fill   = "#F0FFF0" if not ctx.dark else "#1A2A1A"
    par_stroke = "#66AA66" if not ctx.dark else "#559955"
    g.append(dw.Rectangle(
        min_x, y_start - BLOCK_PAD,
        block_w, block_h,
        fill=par_fill, stroke=par_stroke,
        stroke_width=1, rx=4, ry=4,
        fill_opacity=0.4,
    ))
    g.append(dw.Text(
        "[par]", 10,
        min_x + 6, y_start - BLOCK_PAD + 4,
        font_family=ANNOTATION_FONT,
        fill=par_stroke,
        dominant_baseline="hanging",
    ))

    y = y_start
    for i, branch in enumerate(branches):
        y = _render_steps(g, branch, y, ctx)
        if i < len(branches) - 1:
            # Dashed separator between lanes.
            g.append(dw.Line(
                min_x, y, max_x, y,
                stroke=par_stroke, stroke_width=1,
                stroke_dasharray="4,3",
            ))
            y += STEP_HEIGHT

    return y

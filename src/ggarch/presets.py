"""ggarch built-in style presets.

A preset is a complete StyleSpec: resolved colours, shapes, and edge styles
for both light and dark modes. The model's style block may extend a preset
and override individual rules.

The 'juju' preset gives colour exactly one meaning, ownership:
- Orange border: Juju machinery (Juju software, charms, nodes, units,
  Pebble, records, databases).
- Grey border (one grey per mode): everything outside Juju (people,
  clouds and other external systems, workloads).
No node has a fill, so shapes read the same on light and dark pages.
Kind is carried by shape (person icon, cylinder) and lifecycle by the
border dash, never by colour.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class NodeStyle:
    fill: str = "#FFFFFF"
    stroke: str = "#999999"
    font_color: str = "#333333"
    font_size: int = 13
    shape: str = "rectangle"   # rectangle | person | cylinder | diamond
    stroke_width: int = 1
    stroke_dash: str = ""      # "" | "4" | "2"
    border_radius: int = 4
    badge: str = ""            # kind badge (round 24 verdict A): "" |
                               # "juju" | "charm" | "record" — the ~14px
                               # corner badge carries the semantic kind
                               # (the person's icon is the precedent)


@dataclass
class EdgeStyle:
    stroke: str = "#666666"
    stroke_width: int = 1
    stroke_dash: str = ""      # "" | "6,3" | "2,2"
    arrowhead: str = "filled"  # filled | open | hollow | none (ADR-004 commitment)
    font_color: str = "#444444"
    font_size: int = 11


@dataclass
class ResolvedStyle:
    """Fully resolved style for a diagram — light and dark mode."""
    node_light: dict[str, NodeStyle] = field(default_factory=dict)
    node_dark: dict[str, NodeStyle] = field(default_factory=dict)
    edge_light: dict[str, EdgeStyle] = field(default_factory=dict)
    edge_dark: dict[str, EdgeStyle] = field(default_factory=dict)

    def node(self, type_name: str, dark: bool = False) -> NodeStyle:
        bank = self.node_dark if dark else self.node_light
        return bank.get(type_name, bank.get("default", NodeStyle()))

    def edge(self, type_name: str, dark: bool = False) -> EdgeStyle:
        bank = self.edge_dark if dark else self.edge_light
        return bank.get(type_name, bank.get("default", EdgeStyle()))


# ---------------------------------------------------------------------------
# Juju preset
# ---------------------------------------------------------------------------

_ORANGE = "#E95420"          # Juju-owned: the border colour
_GREY_LIGHT = "#AAAAAA"      # external: the one grey, light mode
_GREY_DARK = "#666666"       # external: the one grey, dark mode
_TEXT_LIGHT = "#333333"
_TEXT_DARK = "#CDD6F4"


def _nodes(grey: str, text: str) -> dict[str, NodeStyle]:
    juju = dict(fill="none", stroke=_ORANGE, font_color=text)
    outside = dict(fill="none", stroke=grey, font_color=text)
    return {
        "default": NodeStyle(**outside),
        # Outside Juju.
        "person": NodeStyle(**outside, shape="person"),
        "external": NodeStyle(**outside),
        "workload": NodeStyle(**outside),
        # Juju machinery. "container" is the older spelling of "node"
        # (a machine or a pod; machines can nest).
        "juju-software": NodeStyle(**juju),
        "charm": NodeStyle(**juju),
        "pebble": NodeStyle(**juju),
        "unit": NodeStyle(**juju, border_radius=6),
        "node": NodeStyle(**juju, border_radius=6),
        "container": NodeStyle(**juju, border_radius=6),
        "database": NodeStyle(**juju, shape="cylinder"),
        "record": NodeStyle(**juju, border_radius=2, badge="record"),
    }


def _edges(stroke: str, mute: str, text: str) -> dict[str, EdgeStyle]:
    return {
        "default": EdgeStyle(stroke=mute, font_color=text),
        "api":     EdgeStyle(stroke=stroke, font_color=text),
        "stream":  EdgeStyle(stroke=stroke, stroke_dash="6,3", font_color=text),
        "event":   EdgeStyle(stroke=mute, stroke_dash="6,3", arrowhead="open",
                             font_color=text),
        "control": EdgeStyle(stroke=stroke, font_color=text),
        "ipc":     EdgeStyle(stroke=mute, stroke_dash="2,2", font_color=text),
        # Persistence is Juju's own: the pointer between records and the
        # bridge from a running node to its record (ADR-005) take the
        # Juju colour.
        "data":    EdgeStyle(stroke=_ORANGE, arrowhead="none", font_color=text),
        "records": EdgeStyle(stroke=_ORANGE, arrowhead="none", font_color=text),
        # ADR-011: the is-a edge (kind tries). Solid, neutral, hollow
        # triangle at the parent (UML generalization).
        "generalization": EdgeStyle(stroke=stroke, arrowhead="hollow",
                                    font_color=text),
    }


_JUJU_LIGHT_NODES = _nodes(_GREY_LIGHT, _TEXT_LIGHT)
_JUJU_DARK_NODES = _nodes(_GREY_DARK, _TEXT_DARK)
_JUJU_LIGHT_EDGES = _edges("#555555", "#888888", "#444444")
_JUJU_DARK_EDGES = _edges("#AAAAAA", "#888888", _TEXT_DARK)

# ---------------------------------------------------------------------------
# Preset registry
# ---------------------------------------------------------------------------

JUJU_PRESET = ResolvedStyle(
    node_light=_JUJU_LIGHT_NODES,
    node_dark=_JUJU_DARK_NODES,
    edge_light=_JUJU_LIGHT_EDGES,
    edge_dark=_JUJU_DARK_EDGES,
)

_PRESETS: dict[str, ResolvedStyle] = {
    "juju": JUJU_PRESET,
    "": JUJU_PRESET,   # default when no extends declared
}


def get_preset(name: str) -> ResolvedStyle:
    """Return a named preset, falling back to the juju preset."""
    return _PRESETS.get(name, JUJU_PRESET)


def resolve_style(model_style, dark: bool = False) -> dict[str, NodeStyle]:
    """Merge a model's style block onto the preset, returning node styles."""
    preset = get_preset(model_style.extends)
    bank = dict(preset.node_dark if dark else preset.node_light)
    rules = model_style.dark_node_rules if dark else model_style.node_rules
    for type_name, rule in rules.items():
        existing = bank.get(type_name, NodeStyle())
        # Override only fields that were explicitly set in the model.
        merged = NodeStyle(
            fill=rule.fill or existing.fill,
            stroke=rule.stroke or existing.stroke,
            font_color=rule.font_color or existing.font_color,
            font_size=rule.font_size or existing.font_size,
            shape=rule.shape or existing.shape,
            border_radius=existing.border_radius,
        )
        bank[type_name] = merged
    return bank

def resolve_edge_style(model_style, dark: bool = False) -> dict[str, EdgeStyle]:
    """Merge a model's edge style rules onto the preset's edge styles."""
    preset = get_preset(model_style.extends)
    bank = dict(preset.edge_dark if dark else preset.edge_light)
    rules = model_style.dark_edge_rules if dark else model_style.edge_rules
    for type_name, rule in rules.items():
        existing = bank.get(type_name, EdgeStyle())
        # Override only fields that were explicitly set in the model.
        bank[type_name] = EdgeStyle(
            stroke=rule.stroke or existing.stroke,
            stroke_width=rule.stroke_width or existing.stroke_width,
            stroke_dash=rule.stroke_dash or existing.stroke_dash,
            arrowhead=rule.arrowhead or existing.arrowhead,
            font_color=rule.font_color or existing.font_color,
            font_size=rule.font_size or existing.font_size,
        )
    return bank

"""ggarch built-in style presets.

A preset is a complete StyleSpec: resolved colours, shapes, and edge styles
for both light and dark modes. The model's style block may extend a preset
and override individual rules.

The 'juju' preset encodes Canonical's visual grammar for Juju diagrams:
- Juju software: Ubuntu Orange (#E95420)
- Charm: white box with orange border
- Workload: blue (#4A90D9)
- Pebble: lighter blue (#74AADC)
- Database: amber cylinder
- Container/pod: light grey background
- Infrastructure: green tint
- External: neutral grey
- Person: outline, no fill
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
    arrowhead: str = "filled"  # filled | open | none (ADR-004 commitment)
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
# Juju preset — light mode
# ---------------------------------------------------------------------------

_JUJU_LIGHT_NODES: dict[str, NodeStyle] = {
    "default": NodeStyle(
        fill="#FFFFFF", stroke="#AAAAAA", font_color="#333333",
    ),
    "person": NodeStyle(
        fill="#F0F0F0", stroke="#777777", font_color="#444444", shape="person",
    ),
    "juju-software": NodeStyle(
        fill="#F0F0F0", stroke="#C74210", font_color="#333333",
        badge="juju",
    ),
    "charm": NodeStyle(
        fill="#F0F0F0", stroke="#E95420", font_color="#000000", stroke_width=2,
        badge="charm",
    ),
    "workload": NodeStyle(
        fill="#F5F5F5", stroke="#AAAAAA", font_color="#444444",
    ),
    "pebble": NodeStyle(
        fill="#F5F5F5", stroke="#AAAAAA", font_color="#444444",
    ),
    "database": NodeStyle(
        fill="#FFF8E1", stroke="#F9A825", font_color="#333333",
        shape="cylinder",
    ),
    "container": NodeStyle(
        fill="#FFF3EE", stroke="#E0956A", font_color="#5A2800",
        border_radius=6,
    ),
    "infrastructure": NodeStyle(
        fill="#E8F5E9", stroke="#66BB6A", font_color="#1B5E20",
    ),
    "external": NodeStyle(
        fill="#F5F5F5", stroke="#AAAAAA", font_color="#444444",
    ),
    "unit": NodeStyle(
        fill="#EEF2FF", stroke="#9999AA", font_color="#333333",
        border_radius=6,
    ),
    "record": NodeStyle(
        fill="#FFFDE7", stroke="#F9A825", font_color="#333333",
        border_radius=2,
        badge="record",
    ),
}

_JUJU_LIGHT_EDGES: dict[str, EdgeStyle] = {
    "default": EdgeStyle(stroke="#888888", stroke_dash=""),
    "api":     EdgeStyle(stroke="#555555", stroke_dash=""),
    "stream":  EdgeStyle(stroke="#555555", stroke_dash="6,3"),
    "event":   EdgeStyle(stroke="#888888", stroke_dash="6,3", arrowhead="open"),
    "data":    EdgeStyle(stroke="#F9A825", stroke_dash=""),
    "control": EdgeStyle(stroke="#555555", stroke_dash=""),
    "ipc":     EdgeStyle(stroke="#888888", stroke_dash="2,2"),
    # ADR-005: the records bridge (synthetic view edge — not a
    # declarable model type): the persistence axis. Amber, solid,
    # headless; direction belongs to the ER view's FK→PK arrows.
    "records": EdgeStyle(stroke="#F9A825", arrowhead="none"),
}

# ---------------------------------------------------------------------------
# Juju preset — dark mode
# ---------------------------------------------------------------------------

_JUJU_DARK_NODES: dict[str, NodeStyle] = {
    "default": NodeStyle(
        fill="#2A2A3E", stroke="#555555", font_color="#CDD6F4",
    ),
    "person": NodeStyle(
        fill="#252525", stroke="#999999", font_color="#CCCCCC", shape="person",
    ),
    "juju-software": NodeStyle(
        fill="#2A2A3E", stroke="#E95420", font_color="#CDD6F4",
        badge="juju",
    ),
    "charm": NodeStyle(
        fill="#252525", stroke="#E95420", font_color="#CDD6F4", stroke_width=2,
        badge="charm",
    ),
    "workload": NodeStyle(
        fill="#2A2A2A", stroke="#666666", font_color="#CCCCCC",
    ),
    "pebble": NodeStyle(
        fill="#2A2A2A", stroke="#666666", font_color="#CCCCCC",
    ),
    "database": NodeStyle(
        fill="#2A2200", stroke="#F9A825", font_color="#FFE082",
        shape="cylinder",
    ),
    "container": NodeStyle(
        fill="#2D1A0E", stroke="#C07040", font_color="#FFD0A0",
        border_radius=6,
    ),
    "infrastructure": NodeStyle(
        fill="#1A2E1A", stroke="#66BB6A", font_color="#A5D6A7",
    ),
    "external": NodeStyle(
        fill="#2A2A2A", stroke="#666666", font_color="#CCCCCC",
    ),
    "unit": NodeStyle(
        fill="#2A2A3E", stroke="#9999AA", font_color="#CDD6F4",
        border_radius=6,
    ),
    "record": NodeStyle(
        fill="#2A2200", stroke="#F9A825", font_color="#FFE082",
        border_radius=2,
        badge="record",
    ),
}

_JUJU_DARK_EDGES: dict[str, EdgeStyle] = {
    "default": EdgeStyle(stroke="#888888", stroke_dash="",    font_color="#CDD6F4"),
    "api":     EdgeStyle(stroke="#AAAAAA", stroke_dash="",    font_color="#CDD6F4"),
    "stream":  EdgeStyle(stroke="#AAAAAA", stroke_dash="6,3", font_color="#CDD6F4"),
    "event":   EdgeStyle(stroke="#888888", stroke_dash="6,3", arrowhead="open",
                         font_color="#CDD6F4"),
    "data":    EdgeStyle(stroke="#F9A825", stroke_dash="",    font_color="#CDD6F4"),
    "control": EdgeStyle(stroke="#AAAAAA", stroke_dash="",    font_color="#CDD6F4"),
    "ipc":     EdgeStyle(stroke="#888888", stroke_dash="2,2", font_color="#CDD6F4"),
    "records": EdgeStyle(stroke="#F9A825", arrowhead="none",
                         font_color="#CDD6F4"),
}

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

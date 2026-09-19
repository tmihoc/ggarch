"""ELK Layered backend (ADR-006): optional layout engine for views
without declared positions.

Activation: GGARCH_LAYOUT=elk. Requires node on PATH and the elkjs
bundled build (GGARCH_ELK_BUNDLE, or probed from ./node_modules).
When unavailable, callers fall back to the built-in synthesizer —
the floor — so this module adds no hard dependency.

Boundary: ELK owns layering, ordering, coordinate assignment and
edge routes for the views it serves. Everything above the layout —
grammar, labels (ADR-002), channel grammar (ADR-004), renderer,
audit gate — is unchanged. Authored views (declared positions) never
reach this module: position is content.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from ggarch.layout import SolvedLayout, SolvedNode, Rect
from ggarch.layout import min_size

RUNNER_JS = """
const fs = require('fs');
const ELK = require(process.argv[2]);
const elk = new (ELK.default || ELK)();
const input = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const out = [];
let pending = input.graphs.length;
(function next() {
  if (!pending) { fs.writeFileSync(process.argv[4], JSON.stringify(out)); return; }
  const g = input.graphs[input.graphs.length - pending];
  pending -= 1;
  elk.layout(g).then(res => { out.push(res); next(); })
     .catch(e => { out.push({error: String(e)}); next(); });
})();
"""


def bundle_path() -> str | None:
    """Locate the elkjs bundled build."""
    env = os.environ.get("GGARCH_ELK_BUNDLE")
    if env and Path(env).is_file():
        return env
    for probe in (
        Path.cwd() / "node_modules/elkjs/lib/elk.bundled.js",
        Path.cwd() / ".sphinx/node_modules/elkjs/lib/elk.bundled.js",
    ):
        if probe.is_file():
            return str(probe)
    return None


def available() -> bool:
    """True when node and the elkjs bundle are both present."""
    return (os.environ.get("GGARCH_LAYOUT") == "elk"
            and shutil.which("node") is not None
            and bundle_path() is not None)


def layout_view(diagram, model, select):
    """Layout one view with ELK Layered.

    Returns (SolvedLayout, routes) where routes is a list of
    (source_id, target_id, [Point, ...]) in ELK's orthogonal/polyline
    geometry, or None when the view is out of scope for this backend
    (containers with visible children are v1-out-of-scope; the caller
    falls back to the built-in synthesizer).

    Uniform leaf sizing applies (the floor's standing rule): every
    node renders at the largest member's minimum size, which gives
    ELK's layered coordinate assignment aligned faces to work with.
    """
    from ggarch.instances import materialize_instances
    from ggarch.router import Point

    nodes, edges = materialize_instances(select, model)
    sel_ids = set(select.node_ids) if select.node_ids else {n.id for n in nodes}
    # Instanced types: the select names the type id; the materialized
    # tree contains the stamped instance roots. ALL specs of a selected
    # type expand — discarding per-spec ate instances 2..n (the
    # "only application 1 / only cloud_a" corruption).
    type_ids = {s.type_id for s in select.instances}
    expanded = {s.instance_id for s in select.instances
                if s.type_id in sel_ids}
    sel_ids = (sel_ids - type_ids) | expanded
    types = set(select.edge_types) if select.edge_types else None
    # Deep selection: selected nodes may sit anywhere in the tree (the
    # floor's _find_in_tree is recursive too — unit_agent and charm are
    # model children of unit_pod yet selected flat when unit_pod is
    # not).
    view_nodes: dict = {}
    parent_of: dict[str, str] = {}

    def _walk(n, parent_id: str) -> None:
        if n.id in sel_ids:
            view_nodes[n.id] = n
            if parent_id:
                parent_of[n.id] = parent_id
        for c in n.children:
            _walk(c, n.id)
    for n in nodes:
        _walk(n, "")
    # v1 scope: flat views only — no selected container (its subtree
    # renders nested), no selected child under a selected parent
    # (nested rendering). Those views fall back to the built-in
    # synthesizer.
    if any(n.children for n in view_nodes.values()):
        return None
    if any(p in view_nodes for p in parent_of.values()):
        return None
    view_edges = [e for e in edges
                  if e.source in view_nodes and e.target in view_nodes
                  and e.source != e.target
                  and (types is None or e.type in types)]

    sizes = {nid: min_size(n.label) for nid, n in view_nodes.items()}
    w = max(w for w, _ in sizes.values())
    h = max(h for _, h in sizes.values())

    graph = {
        "id": "root",
        "layoutOptions": {
            "algorithm": "layered",
            "elk.direction": "RIGHT",
            "elk.edgeRouting": ("ORTHOGONAL"
                                if select.routing == "orthogonal"
                                else "POLYLINE"),
            "elk.spacing.nodeNode": "60",
            "elk.spacing.edgeNode": "48",
            "elk.layered.spacing.nodeNodeBetweenLayers": "80",
            "elk.layered.spacing.edgeEdgeBetweenLayers": "40",
            "elk.layered.nodePlacement": "BRANDES_KOEPF",
        },
        "children": [
            {"id": nid, "width": w, "height": h} for nid in view_nodes
        ],
        "edges": [
            {"id": f"e{i}", "sources": [e.source], "targets": [e.target]}
            for i, e in enumerate(view_edges)
        ],
    }

    bundle = bundle_path()
    runner = Path(tempfile.gettempdir()) / "ggarch-elk-runner.js"
    runner.write_text(RUNNER_JS)
    with tempfile.TemporaryDirectory() as tmp:
        fin = Path(tmp) / "in.json"
        fout = Path(tmp) / "out.json"
        fin.write_text(json.dumps({"bundle": bundle, "graphs": [graph]}))
        proc = subprocess.run(
            ["node", str(runner), bundle, str(fin), str(fout)],
            capture_output=True, text=True, timeout=120,
            cwd=str(Path(bundle).parent.parent))
        if proc.returncode != 0 or not fout.exists():
            return None
        results = json.loads(fout.read_text())
    res = results[0]
    if "error" in res or "children" not in res:
        return None

    pos = {c["id"]: c for c in res.get("children", [])}
    solved = []
    for nid, n in view_nodes.items():
        c = pos[nid]
        solved.append(SolvedNode(
            id=nid, rect=Rect(c["x"], c["y"], c["width"], c["height"]),
            label=n.label, type=n.type, lifecycle=str(n.lifecycle),
            properties=dict(n.properties), records=n.records))
    xs = [n.rect.x for n in solved]
    ys = [n.rect.y for n in solved]
    x2 = max(n.rect.x + n.rect.w for n in solved)
    y2 = max(n.rect.y + n.rect.h for n in solved)
    layout = SolvedLayout(nodes=solved,
                          bounds=Rect(min(xs), min(ys), x2 - min(xs),
                                      y2 - min(ys)))

    routes: list[tuple[str, str, list]] = []
    for i, e in enumerate(view_edges):
        ee = next(x for x in res["edges"] if x["id"] == f"e{i}")
        for sec in ee.get("sections", []):
            pts = [Point(sec["startPoint"]["x"], sec["startPoint"]["y"])]
            pts += [Point(bp["x"], bp["y"]) for bp in sec.get("bendPoints", [])]
            pts.append(Point(sec["endPoint"]["x"], sec["endPoint"]["y"]))
            routes.append((e.source, e.target, pts))
    return layout, routes

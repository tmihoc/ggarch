"""Instance materialization tests.

Covers the 0.22.0 semantics: instances stamp the type node's whole
subtree (children included, ids prefixed "<instance>/<child>"), and
model edges expand per instance -- zipped inside one instance's subtree,
fanned from outside. Multiple `instances:` clauses accumulate.
"""
from ggarch import parse, validate, solve, route


SRC = """\
model "M" {
  nodes {
    ctrl [type: juju-software, label: "Ctrl"]
    pod [type: container, label: "Pod"] {
      agent [type: juju-software, label: "Agent"]
      app   [type: charm, label: "App"]
    }
  }
  edges {
    ctrl -> pod   [type: stream, label: "drives"]
    agent -> app   [type: control, label: "runs"]
  }
}
diagram "D" from "M" {
  select {
    nodes: ctrl pod
    instances: pod [
      { id: p1, label: "pod-1" },
      { id: p2, label: "pod-2" }
    ]
  }
  positions {
    ctrl left-of p1 gap: 60
    ctrl align-middle p1
    p1   left-of p2 gap: 60
    p1   align-middle p2
  }
}
"""

SRC_MULTI = """\
model "M2" {
  nodes {
    user [type: person, label: "User"]
    app [type: external, label: "application"]
    cloud [type: external, label: "cloud"]
  }
  edges {
    user -> app [type: control, label: "operates"]
  }
}
diagram "D2" from "M2" {
  select {
    nodes: user app cloud
    instances: app [
      { id: app1, label: "application 1" },
      { id: app2, label: "application 2" }
    ]
    instances: cloud [
      { id: cloud_a, label: "cloud 1" }
    ]
  }
  positions {
    user left-of app1 gap: 60
    user align-middle app1
    app1 left-of app2 gap: 60
    app1 align-middle app2
    cloud_a above app1 gap: 50
    cloud_a align-centre app1
  }
}
"""


class TestInstanceMaterialization:
    def test_subtree_stamped_and_edges_expanded(self):
        f = parse(SRC); validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        lay = solve(d, m)
        rl = route(lay, m, d.select)

        ids = set()
        def walk(n):
            ids.add(n.id)
            for c in n.children:
                walk(c)
        for n in lay.nodes:
            walk(n)

        # Instances carry the archetype's children, prefixed per instance.
        assert {"ctrl", "p1", "p2", "p1/agent", "p1/app",
                "p2/agent", "p2/app"} <= ids
        # The instance label override renders on the stamped root.
        assert lay.find("p1").label == "pod-1"
        assert lay.find("p2").label == "pod-2"
        # The type node itself is replaced by the instances.
        assert "pod" not in ids

        # Top-level edge fans to every instance.
        pairs = {(e.source_id, e.target_id) for e in rl.edges}
        assert ("ctrl", "p1") in pairs
        assert ("ctrl", "p2") in pairs
        # Child edge is copied per instance (zipped), not cartesian.
        assert ("p1/agent", "p1/app") in pairs
        assert ("p2/agent", "p2/app") in pairs
        assert ("p1/agent", "p2/app") not in pairs
        assert ("p2/agent", "p1/app") not in pairs

    def test_multiple_instance_clauses_accumulate(self):
        f = parse(SRC_MULTI); validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        lay = solve(d, m)
        rl = route(lay, m, d.select)
        ids = {n.id for n in lay.nodes}
        # Both instance clauses survive parsing (no overwrite).
        assert {"app1", "app2", "cloud_a"} <= ids
        pairs = {(e.source_id, e.target_id) for e in rl.edges}
        assert ("user", "app1") in pairs
        assert ("user", "app2") in pairs

    def test_uninstanced_select_returns_model_verbatim(self):
        from ggarch.instances import materialize_instances
        f = parse(SRC); validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        select = d.select
        select.instances = []
        nodes, edges = materialize_instances(select, m)
        assert [n.id for n in nodes] == [n.id for n in m.nodes]
        assert [(e.source, e.target) for e in edges] == \
               [(e.source, e.target) for e in m.edges]


SRC_MESH = """\
model "M3" {
  nodes {
    node [type: container, label: "Node"] {
      dql [type: database, label: "Dqlite"]
    }
  }
  edges {
    dql -> dql [type: stream, label: "Raft sync", pairing: mesh]
  }
}
diagram "D3" from "M3" {
  select {
    nodes: node
    instances: node [
      { id: c1, label: "Node 1" },
      { id: c2, label: "Node 2" },
      { id: c3, label: "Node 3" }
    ]
  }
  positions {
    c1 left-of c2 gap: 80
    c1 align-middle c2
    c2 left-of c3 gap: 80
    c2 align-middle c3
  }
}
"""


class TestMeshPairing:
    def test_mesh_expands_to_all_distinct_pairs(self):
        from ggarch import solve
        f = parse(SRC_MESH); validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        pairs = {(e.source_id, e.target_id) for e in rl.edges}
        # Full mesh: every ordered distinct pair, no self-pairs.
        expected = {(f"c{i}/dql", f"c{j}/dql")
                     for i in (1, 2, 3) for j in (1, 2, 3) if i != j}
        assert pairs == expected
        assert len(pairs) == 6

    def test_bad_pairing_value_rejected(self):
        import pytest
        from ggarch.errors import ValidationError
        src = SRC_MESH.replace("pairing: mesh", "pairing: ring")
        f = parse(src)
        with pytest.raises(ValidationError):
            validate(f)

    def test_mesh_with_arrow_both_collapses_to_unordered_pairs(self):
        """`arrow: both` makes direction immaterial, so a mesh expands
        to one two-way arrow per unordered pair (the user's HA
        candidate: 3 two-way Raft arrows, not 6 double-headed ones)."""
        from ggarch import solve
        src = SRC_MESH.replace('[type: stream, label: "Raft sync", pairing: mesh]',
                               '[type: stream, label: "Raft sync", '
                               'pairing: mesh, arrow: both]')
        f = parse(src); validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        rl = route(solve(d, m), m, d.select)
        pairs = {(e.source_id, e.target_id) for e in rl.edges}
        expected = {("c1/dql", "c2/dql"), ("c2/dql", "c3/dql"),
                    ("c1/dql", "c3/dql")}
        assert pairs == expected
        assert len(pairs) == 3
        for e in rl.edges:
            assert e.arrow == "both"

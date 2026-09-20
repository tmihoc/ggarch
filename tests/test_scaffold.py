"""The DDL scaffold generator (ggarch scaffold).

Correctness bar: the generated fragment parses and validates —
FK-completeness by construction (every fk: field originates exactly
one edge per distinct target; every data edge starts at an fk: field).
The agent curates AFTER scaffolding, with the validator watching.
"""
from __future__ import annotations

import pytest

from ggarch import parse, validate
from ggarch.scaffold import parse_ddl, scaffold

DDL = """\
CREATE TABLE application (
    -- the application's identity
    uuid TEXT NOT NULL PRIMARY KEY,
    name TEXT NOT NULL,
    life_id INT NOT NULL,
    charm_uuid TEXT NOT NULL,
    note TEXT,
    CONSTRAINT fk_application_life
    FOREIGN KEY (life_id)
    REFERENCES life (id),
    CONSTRAINT fk_application_charm
    FOREIGN KEY (charm_uuid)
    REFERENCES charm (uuid)
);

CREATE TABLE unit (
    uuid TEXT NOT NULL PRIMARY KEY,
    app_uuid TEXT NOT NULL,
    machine_uuid TEXT,
    CONSTRAINT fk_unit_application
    FOREIGN KEY (app_uuid)
    REFERENCES application (uuid)
);

CREATE TABLE charm (
    uuid TEXT NOT NULL PRIMARY KEY,
    source_id INT NOT NULL,
    CONSTRAINT fk_charm_source
    FOREIGN KEY (source_id)
    REFERENCES charm_source (id)
);

CREATE TABLE charm_source (
    id INT PRIMARY KEY,
    url TEXT NOT NULL
);

CREATE TABLE life (
    id INT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


@pytest.fixture(scope="module")
def tables():
    return parse_ddl(DDL)


class TestParseDdl:
    def test_columns_skip_constraints_and_comments(self, tables):
        cols = {c[0] for c in tables["application"]["columns"]}
        assert "uuid" in cols and "note" in cols
        assert not any(c.startswith("CONSTRAINT") or c.startswith("fk_")
                       for c in cols)

    def test_fks_reference_parent_and_column(self, tables):
        assert ("app_uuid", "application", "uuid") in \
            [tuple(fk) for fk in tables["unit"]["fks"]]

    def test_nullable_flag(self, tables):
        by_name = {c[0]: c for c in tables["application"]["columns"]}
        assert by_name["note"][3] is True      # TEXT (nullable)
        assert by_name["name"][3] is False     # NOT NULL


class TestScaffold:
    def test_fragment_parses_and_validates(self, tables):
        """The correctness bar: the scaffold is born valid —
        FK-completeness by construction."""
        f = parse(scaffold(tables, "model"))
        validate(f)

    def test_markers(self, tables):
        src = scaffold(tables, "model")
        assert "uuid [label: \"uuid\", type: \"text\", pk: true]" in src
        assert "fk: true" in src
        # nullable column carries null: true
        assert "note [label: \"note\", type: \"text\", null: true]" in src
        # NOT NULL column does not
        assert "name [label: \"name\", type: \"text\"]" in src

    def test_edge_targets_parent_pk(self, tables):
        src = scaffold(tables, "model")
        assert "unit.app_uuid -> application.uuid [type: data]" in src

    def test_ground_pointers_carry_db(self, tables):
        assert 'ground: "model:application"' in scaffold(tables, "model")

    def test_closure_auto_includes_referenced_parents(self, tables):
        """Requesting only `unit` auto-includes the transitive FK
        parents (application, charm, charm_source, and life — which
        application references); pruning a referenced parent would
        hide the pointer."""
        src = scaffold(tables, "model", {"unit"})
        for table in ("unit", "application", "charm", "charm_source",
                      "life"):
            assert f'label: "{table}"' in src
        # a leaf table with no inbound FKs and no reference from the
        # roots: only `life` requested -> nothing else generated
        lone = scaffold(tables, "model", {"life"})
        assert lone.count('type: record') == 1

    def test_dual_reference_draws_one_edge_per_target(self, tables):
        """A DDL-sanctioned dual reference (one column, two FK targets)
        draws one pointer per distinct target — both pointers drawn."""
        import copy
        two = copy.deepcopy(tables)
        two["unit"]["fks"].append(("app_uuid", "charm_source", "id"))
        src = scaffold(two, "model")
        assert "unit.app_uuid -> application.uuid [type: data]" in src
        assert "unit.app_uuid -> charm_source.id [type: data]" in src
        f = parse(src)
        validate(f)

    def test_duplicate_target_still_rejected(self, tables):
        """The validator's law is unchanged: the same target twice is a
        double-drawn arrow."""
        import copy
        two = copy.deepcopy(tables)
        two["unit"]["fks"].append(("app_uuid", "application", "uuid"))
        f = parse(scaffold(two, "model"))
        with pytest.raises(Exception, match="same target"):
            validate(f)

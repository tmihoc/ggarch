"""Tests for Phase 9: node fields (record/class shapes, field-qualified edges)."""
import pytest
from ggarch import parse, validate, solve, route, render
from ggarch.errors import ValidationError
from ggarch.layout import FIELD_HEADER_H, FIELD_ROW_H, field_node_min_size


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

RECORD_SRC = """\
model "M" {
  nodes {
    user [type: record, label: "user"] {
      fields {
        id   [label: "id",   type: "uuid",    pk: true]
        name [label: "name", type: "text"]
        age  [label: "age",  type: "int",     null: true]
      }
    }
    post [type: record, label: "post"] {
      fields {
        id      [label: "id",      type: "uuid", pk: true]
        user_id [label: "user_id", type: "uuid", fk: true]
        body    [label: "body",    type: "text"]
      }
    }
  }
  edges {
    post.user_id -> user.id [type: data, label: "author"]
  }
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: user post  edges: type data }
  positions {
    user left-of post gap: 80
    user align-middle post
  }
}
"""

CLASS_SRC = """\
model "M" {
  nodes {
    controller [type: class, label: "Controller"] {
      fields {
        db     [label: "db",     type: "Dqlite",  pk: true]
        listen [label: "listen", type: "string"]
        stop   [label: "stop()", type: "void",    fk: true]
      }
    }
  }
  edges {}
  style { extends: juju }
}
diagram "D" from "M" {
  select { nodes: controller }
  positions {}
}
"""


def _pipeline(src):
    f = parse(src)
    validate(f)
    d = f.diagrams[0]
    m = f.get_model(d.model_name)
    return render(route(solve(d, m), m, d.select), m, d)


class TestFieldParsing:
    def test_fields_parsed(self):
        f = parse(RECORD_SRC)
        n = f.models[0].find_node("user")
        assert len(n.fields) == 3

    def test_field_attributes(self):
        f = parse(RECORD_SRC)
        n = f.models[0].find_node("user")
        id_field = next(fld for fld in n.fields if fld.id == "id")
        assert id_field.pk is True
        assert id_field.type == "uuid"

    def test_nullable_field(self):
        f = parse(RECORD_SRC)
        n = f.models[0].find_node("user")
        age_field = next(fld for fld in n.fields if fld.id == "age")
        assert age_field.nullable is True

    def test_fk_field(self):
        f = parse(RECORD_SRC)
        n = f.models[0].find_node("post")
        uid = next(fld for fld in n.fields if fld.id == "user_id")
        assert uid.fk is True

    def test_field_qualified_edge_parsed(self):
        f = parse(RECORD_SRC)
        e = f.models[0].edges[0]
        assert e.source == "post"
        assert e.source_field == "user_id"
        assert e.target == "user"
        assert e.target_field == "id"


class TestFieldValidation:
    def test_valid_record_validates(self):
        f = parse(RECORD_SRC)
        validate(f)  # must not raise

    def test_duplicate_field_id_rejected(self):
        src = RECORD_SRC.replace(
            "age  [label: \"age\",  type: \"int\",     null: true]",
            "id   [label: \"dup\",  type: \"int\"]"
        )
        f = parse(src)
        with pytest.raises(ValidationError, match="duplicate field id"):
            validate(f)

    def test_unknown_field_in_edge_rejected(self):
        src = RECORD_SRC.replace("post.user_id -> user.id", "post.bogus -> user.id")
        f = parse(src)
        with pytest.raises(ValidationError, match="undeclared field"):
            validate(f)


class TestFieldLayout:
    def test_field_node_min_size(self):
        w, h = field_node_min_size("user", 3)
        assert h == FIELD_HEADER_H + 3 * FIELD_ROW_H + 4

    def test_solved_node_carries_fields(self):
        f = parse(RECORD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        user_node = layout.find("user")
        assert len(user_node.fields) == 3

    def test_record_taller_than_plain_node(self):
        f = parse(RECORD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        user_node = layout.find("user")
        assert user_node.rect.h >= FIELD_HEADER_H + 3 * FIELD_ROW_H


class TestFieldRouting:
    def test_field_qualified_edge_anchors_at_field_row(self):
        f = parse(RECORD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        layout = solve(d, m)
        routed = route(layout, m, d.select)
        assert len(routed.edges) == 1
        e = routed.edges[0]
        # Anchor y should match the field row, not the node centre.
        post_node = layout.find("post")
        user_node = layout.find("user")
        # user_id is field index 1 in post, id is field index 0 in user
        user_id_y = post_node.rect.y + FIELD_HEADER_H + 1 * FIELD_ROW_H + FIELD_ROW_H / 2
        id_y      = user_node.rect.y + FIELD_HEADER_H + 0 * FIELD_ROW_H + FIELD_ROW_H / 2
        assert abs(e.points[0].y - user_id_y) < 1
        assert abs(e.points[-1].y - id_y) < 1


class TestFieldRendering:
    def test_record_renders_svg(self):
        svg = _pipeline(RECORD_SRC)
        assert "<svg" in svg

    def test_record_shows_pk_marker(self):
        svg = _pipeline(RECORD_SRC)
        assert "PK" in svg

    def test_record_shows_fk_marker(self):
        svg = _pipeline(RECORD_SRC)
        assert "FK" in svg

    def test_record_shows_nullable(self):
        svg = _pipeline(RECORD_SRC)
        assert "age?" in svg

    def test_record_shows_field_type(self):
        svg = _pipeline(RECORD_SRC)
        assert "uuid" in svg

    def test_record_dark_mode(self):
        f = parse(RECORD_SRC)
        validate(f)
        d = f.diagrams[0]
        m = f.get_model(d.model_name)
        svg = render(route(solve(d, m), m, d.select), m, d, dark=True)
        assert "<svg" in svg
        assert "PK" in svg

    def test_class_shows_visibility(self):
        svg = _pipeline(CLASS_SRC)
        assert "+" in svg   # public (pk=True)
        assert "-" in svg   # private default

    def test_class_shows_return_type(self):
        svg = _pipeline(CLASS_SRC)
        assert "void" in svg

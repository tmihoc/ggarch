"""ERD grammar audit (round-2 item 3): data-edge endpoints vs the
declared field rows, and cardinality end-label placement vs the stroke.

Usage:
  python scripts/audit-erd-anchors.py model.ggarch [...]

Per view, per data edge, per endpoint:
  chip        — node-qualified endpoint (collapsed node: any anchor is
                correct by the grammar)
  on-row      — endpoint sits on the declared field row's band
  off-row     — endpoint on the box face but NOT on the declared row
                (the mid-y flatten moved it off — the reviewer's
                "lines must connect the rows" failure)
  floating    — endpoint off the box entirely (the 587a37d defect class)
  face:n/s    — field-qualified endpoint attached on a horizontal face
                (the row band never reaches the face; the anchor still
                encodes the field identity via the spread x)

Per rendered 1/m end label:
  on-line     — glyph centre within 2px of the stroke
  off-line    — the session-44 outside-the-face placement (the
                convention item 3 AMENDS)

Exit 0 always; the text is the enumeration (diff against the
audit-before dump per rule 3).
"""
import sys

from drawsvg import Group

from ggarch import parse, route, solve
from ggarch import renderer as R
from ggarch.layout import FIELD_HEADER_H, FIELD_ROW_H


def _pt_seg_dist(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    ll = dx * dx + dy * dy
    if ll == 0:
        return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
    t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / ll))
    return ((px - (x1 + t * dx)) ** 2 + (py - (y1 + t * dy)) ** 2) ** 0.5


def _stroke_dist(tx, ty, pts):
    return min(_pt_seg_dist(tx, ty, pts[i][0], pts[i][1],
                            pts[i + 1][0], pts[i + 1][1])
               for i in range(len(pts) - 1))


def _endpoint_verdict(node, p, field_id):
    if not field_id:
        return "chip"
    if node is None:
        return "floating"
    if not node.fields:
        return "face (node has no field rows)"
    idx = next((i for i, f in enumerate(node.fields) if f.id == field_id),
               None)
    if idx is None:
        return "floating (field id not on node)"
    band_y = node.rect.y + FIELD_HEADER_H + idx * FIELD_ROW_H
    face = R._face_point(node, (p[0], p[1]))
    if face in ("w", "e"):
        return ("on-row" if band_y - 0.5 <= p[1] <=
                band_y + FIELD_ROW_H + 0.5 else "off-row")
    return "face:n/s (row band does not reach the face)"


def audit_file(path):
    f = parse(open(path).read())
    print("=" * 70)
    print(path)
    print("=" * 70)
    for d in f.diagrams:
        m = f.get_model(d.model_name)
        solved = solve(d, m)
        routed = route(solved, m, d.select)
        data = [e for e in routed.edges if e.edge_type == "data"]
        if not data:
            continue
        print(f"\n{d.name}: {len(data)} data edges")
        R._clear_end_label_spots()
        for e in data:
            src = solved.find(e.source_id)
            tgt = solved.find(e.target_id)
            pts = [(p.x, p.y) for p in e.points]
            sv = _endpoint_verdict(src, pts[0], e.source_field)
            tv = _endpoint_verdict(tgt, pts[-1], e.target_field)
            flags = []
            if "off-row" in sv or "floating" in sv:
                flags.append(f"SRC-FAIL {sv}")
            if "off-row" in tv or "floating" in tv:
                flags.append(f"TGT-FAIL {tv}")
            line = f"  {e.source_id}.{e.source_field or '*'} -> " \
                   f"{e.target_id}.{e.target_field or '*'}: src={sv} tgt={tv}"
            if flags:
                line += "   <<< " + " ".join(flags)
            print(line)
            # Label placement, measured through the renderer's own
            # placement code (single source, never replicated).
            g = Group()
            before = dict(R._END_LABEL_SPOTS)
            R._render_data_end_labels(g, e, solved, 0.0, 0.0, "#000")
            for key, (tx, ty) in R._END_LABEL_SPOTS.items():
                if key in before:
                    continue
                dist = _stroke_dist(tx, ty, pts)
                verdict = "on-line" if dist <= 2.0 else f"off-line ({dist:.1f}px)"
                if dist > 2.0:
                    verdict += "  <<< LABEL-FAIL"
                print(f"    label {key[2]!r} @ face {key[1]}: {verdict}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        audit_file(p)
#!/usr/bin/env python3
"""Anchor census — the where-on-the-face measurement for the
symmetric-port review (2026-09-21).

For every diagram view in the given model files, classify every ROUTED
edge endpoint (the drawn anchor, post-solve, post-route) against the
anchor classes the symmetric-port rule proposes to hard-gate:

  midpoint       — within 1.0 px of the face midpoint
  field pin      — declared field-qualified endpoint (author speech;
                   the model's `node.field_id` endpoint syntax)
  symmetric slot — a member of a >=2-anchor distribution on its face
                   that is symmetric about the face midpoint (fans,
                   anti-parallel pair-bias mirrors, symmetric ladder
                   lands — the whole principled class)
  corridor       — an off-midpoint anchor on a single-edge container
                   face aligned with a nested child's face span (the
                   shape corridors)
  UNEXPLAINED    — everything else: asymmetric multi-edge-face
                   distributions (anchor-reuse-ladder offsets), and
                   off-midpoint singles with no corridor alignment.

A face's distribution is symmetric iff for every anchor coordinate c
on the face, mid*2 - c is also present (within 1.0 px).

The previous measurement (SESSIONS Addendum 23) counted 267
midpoints + 30 fan slots explained and 47 + 27 UNEXPLAINED in
juju.ggarch. This script re-derives that census reproducibly; the
class set is the same, the assignment is geometric rather than
by-router-intent, so small count deltas are expected and stated.

Usage:  python scripts/anchor-census.py juju.ggarch [principles.ggarch]
Output: per-view table on stdout; an --out file gets full JSON
        (every endpoint record plus unexplained details).
"""
from __future__ import annotations

import argparse
import collections
import json
import math

from ggarch import parse, validate, solve, route
from ggarch.instances import materialize_instances

EPS = 1.0          # px tolerance for "on the face" / "at the midpoint"
ANCHOR_EPS = 1.0   # px tolerance for boundary membership

FIELD = "field pin"
MIDPOINT = "midpoint"
FAN_MEMBER = "fan member"
FAN_SLOT = "fan slot"
SET_SLOT = "set slot"
SYMMETRIC = "symmetric slot"
CORRIDOR = "corridor"
SEAT = "single seat"
CORNER_SEAT = "corner seat"
UNEXPLAINED = "UNEXPLAINED"

CLASSES = (FIELD, MIDPOINT, FAN_MEMBER, FAN_SLOT, SET_SLOT, SYMMETRIC,
           CORRIDOR, SEAT, CORNER_SEAT, UNEXPLAINED)


def all_nodes(layout):
    out = []

    def walk(n):
        out.append(n)
        for c in n.children:
            walk(c)
    for n in layout.nodes:
        walk(n)
    return out


def per_view_edges(select, model):
    """The same materialized edge set route() consumes, retaining the
    declared field qualifiers (field pins are author speech)."""
    _, edges = materialize_instances(select, model)
    except_pairs = set(getattr(select, "except_pairs", []) or [])
    kept = [e for e in edges
            if not any((e.source == es and e.target == et
                        and (ty == "" or ty == e.type))
                       for es, et, ty in except_pairs)]
    return kept


def classify_view(d, f, m):
    solved = solve(d, m)
    routed = route(solved, m, d.select)
    nodes = all_nodes(solved)
    rects = {n.id: n for n in nodes}
    # field pins: materialized declared edges by (source, target)
    declared = {}
    for e in per_view_edges(d.select, m):
        declared[(e.source, e.target)] = e

    face_anchors = {}   # (node_id, side) -> list of coords
    endpoints = []      # one record per routed edge endpoint

    def faces_of(p, r):
        """Every boundary face within ANCHOR_EPS, distance-then-name
        ordered (deterministic). A CORNER anchor lies on two faces —
        the census records/checks every face within eps, mirroring the
        router's corner-safe port closure (ADR-008 rule 4). At an
        exact corner the single-face pick is 1e-13-noise: kiwi's
        equivalent-solve last bits flip it run to run (measured:
        change_stream's src at domain_services' top-right corner
        flipped right/top and fan-member/UNEXPLAINED with the hash
        seed while the drawn geometry stayed byte-identical)."""
        cand = []
        cand.append((abs(p.x - r.x), "left"))
        cand.append((abs(p.x - r.x2), "right"))
        cand.append((abs(p.y - r.y), "top"))
        cand.append((abs(p.y - r.y2), "bottom"))
        cand.sort()
        return [s for d, s in cand if d <= ANCHOR_EPS]

    def face_mid(r, side):
        if side in ("right", "left"):
            return r.y + r.h / 2.0
        return r.x + r.w / 2.0

    for e in routed.edges:
        for end in ("src", "tgt"):
            nid = e.source_id if end == "src" else e.target_id
            p = e.points[0] if end == "src" else e.points[-1]
            r = rects[nid]
            sides = faces_of(p, r.rect)
            rec = {
                "view": d.name, "source": e.source_id,
                "target": e.target_id, "end": end, "label": e.label or "",
                "node": nid, "side": sides[0] if sides else "?",
                "sides": sides,
                "declared_field": bool(getattr(
                    declared.get((e.source_id, e.target_id)),
                    "source_field" if end == "src" else "target_field",
                    "")),
            }
            if not sides:
                rec["class"] = UNEXPLAINED
                rec["reason"] = "not on any boundary face"
                endpoints.append(rec)
                continue
            # corner-safe bookkeeping: the coord registers on EVERY
            # face it sits on (a corner anchor is a member of both)
            for side in sides:
                coord = (float(p.y) if side in ("right", "left")
                         else float(p.x))
                face_anchors.setdefault((nid, side), []).append(coord)
            coord = (float(p.y) if rec["side"] in ("right", "left")
                     else float(p.x))
            rec["coord"] = round(coord, 2)
            rec["point"] = (p.x, p.y)
            endpoints.append(rec)
    # link each record to its edge's other end
    by_edge = {}
    for rec in endpoints:
        by_edge.setdefault((rec["source"], rec["target"]), {})[rec["end"]] = rec

    # classification pass — port sets first (the router's symmetric
    # slots for multi-edge faces), fan groups next, then the per-face
    # rules. A FAN GROUP is >=2 edges with the same (node, side, sign);
    # the sign is src (leaves the node) or tgt (arrives). A corner
    # anchor registers under BOTH its faces; the verdict takes the
    # first EXPLAINED face (faces_of order = distance-then-name), the
    # primary face's verdict when none explains.
    port_sets = getattr(solved, "port_sets", {}) or {}
    fan_machinery = getattr(solved, "fan_faces", {}) or {}
    fan_groups = collections.defaultdict(list)   # (node, side, sign) -> [rec]
    for rec in endpoints:
        if rec["side"] == "?":
            continue
        for side in rec["sides"]:
            fan_groups[(rec["node"], side, rec["end"])].append(rec)

    def classify_at(rec, side):
        """The rule cascade for one endpoint at ONE of its faces.
        Returns (class, reason)."""
        nid, coord = rec["node"], rec["coord"]
        r = rects[nid]
        mid = face_mid(r.rect, side)
        # 1. field pin — declared field-qualified endpoint (author speech)
        if rec["declared_field"]:
            return FIELD, ""
        # 2. the face's symmetric port set (the router's): an anchor ON
        #    the set is a slot; off the set is the measured miss — but
        #    only when the DRAWN face is actually multi-edge (a set
        #    guessed for a face where one edge drew elsewhere is a
        #    phantom: a single anchor on a face is a seat, not an
        #    off-set violation).
        pset = port_sets.get(nid, {}).get(side)
        ms = sorted(face_anchors.get((nid, side), []))
        if pset and len(ms) >= 2:
            if any(abs(coord - v) <= 1.0 for v in pset):
                return SET_SLOT, ""
            return UNEXPLAINED, (f"off its symmetric set {pset} "
                                 f"(face {side})")
        # 3. this end's edge belongs to a FAN (declared FanConstraint
        # or a synthesized plane fan — SolvedLayout.fan_faces):
        # FAN-OWNED (round 24, two measured attempts): the fan
        # machinery prices its hub-face anchors at SYMMETRIC ideals
        # (center ± k*spacing/2) but the routes resolve them by
        # cost — measured: FORCING the ideals as hard port sets
        # regressed the corpus (label-clashes 8 -> 12,
        # strip-crossings +3, >2x 0 -> 3), and a member-centre
        # check is stricter still (91 vs 64) because members stack
        # at label-driven spacings. Fan-owned anchors are a
        # documented class: owned by the fan machinery's soft
        # discipline (symmetric ideals, priced), never counted
        # unexplained. Plain multi-edge faces stay under rules 5-6.
        if (rec["source"], rec["target"]) in fan_machinery:
            return FAN_SLOT, "fan-owned edge (hint-priced anchors)"
        own = fan_groups.get((nid, side, rec["end"]), [])
        if len(own) >= 2:
            if all(any(abs((mid * 2 - c) - m2) <= EPS for m2 in ms)
                   for c in ms):
                return FAN_SLOT, ""
            return UNEXPLAINED, (f"fan face {rec['end']}-{side} not "
                                 f"symmetric about mid ({len(ms)} anchors)")
        # 4. other end is a fan face — fan member side (principled by
        #    the fan machinery: member anchors follow fan geometry)
        other_end = "tgt" if rec["end"] == "src" else "src"
        other = by_edge.get((rec["source"], rec["target"]), {}).get(other_end)
        if other is not None and other["side"] != "?":
            for oside in other["sides"]:
                if len(fan_groups.get(
                        (other["node"], oside, other["end"]), [])) >= 2:
                    return FAN_MEMBER, ""
        # 5. face midpoint
        if abs(coord - mid) <= EPS:
            return MIDPOINT, ""
        # 6. multi-edge face symmetric about the midpoint (no port set
        #    was guessed for it — the geometric distribution still
        #    ought to hold)
        if len(ms) >= 2:
            if all(any(abs((mid * 2 - c) - m2) <= EPS for m2 in ms)
                   for c in ms):
                return SYMMETRIC, ""
            return UNEXPLAINED, f"asymmetric {len(ms)}-edge face"
        # 7. single-edge face: the corridor seat is the principled
        #    single (reviewer verdict 2026-09-21: single-edge corridor
        #    seats stay principled classes). A CORNER landing is not a
        #    seat — it is the ride-law's span-end remedy or the
        #    vocabulary's span-end entry, reported as its own class
        #    (measured 24 corpus-wide: within 1 px of a face end).
        on_width = side in ("top", "bottom")
        lo, hi = ((r.rect.x, r.rect.x2) if on_width
                  else (r.rect.y, r.rect.y2))
        if min(abs(coord - lo), abs(coord - hi)) <= 1.0:
            return CORNER_SEAT, "within 1 px of a face-span end"
        if len(ms) == 1 and getattr(r, "children", None):
            if any((cr.x <= coord <= cr.x2) if on_width
                   else (cr.y <= coord <= cr.y2)
                   for ch in r.children for cr in [ch.rect]):
                return CORRIDOR, ""
        return SEAT, ""

    for rec in endpoints:
        if "coord" not in rec:
            continue
        verdicts = [classify_at(rec, side) for side in rec["sides"]]
        chosen = next((v for v in verdicts if v[0] != UNEXPLAINED),
                      verdicts[0])
        chosen_side = rec["sides"][verdicts.index(chosen)]
        rec["class"], rec["reason"] = chosen
        if chosen_side != rec["side"]:
            # the explaining face is not the nearest: report it (a
            # corner anchor's face attribution is a census fact)
            note = f" (face {chosen_side})"
            rec["reason"] = ((rec["reason"] + note)
                             if rec["reason"] else note.strip())
            rec["side"] = chosen_side
            px, py = rec["point"]
            rec["coord"] = round(float(py) if chosen_side in
                                 ("right", "left") else float(px), 2)
    return endpoints, solved


def audit_file(path, out=None):
    f = parse(open(path).read())
    validate(f)
    report = {}
    for d in f.diagrams:
        m = f.get_model(d.model_name)
        endpoints, _solved = classify_view(d, f, m)
        report[d.name] = endpoints
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("files", nargs="+")
    ap.add_argument("--out", default=None, help="JSON dump path")
    ap.add_argument("--gate", action="store_true",
                    help="exit 1 when any UNEXPLAINED anchor remains "
                         "(the symmetric-port hard gate)")
    args = ap.parse_args()

    totals = {c: 0 for c in CLASSES}
    rows = []
    for path in args.files:
        report = audit_file(path)
        for view, endpoints in report.items():
            counts = {c: sum(1 for r in endpoints if r["class"] == c)
                      for c in CLASSES}
            for c in CLASSES:
                totals[c] += counts[c]
            rows.append((path.split("/")[-1], view, counts))
            for r in endpoints:
                if r["class"] == UNEXPLAINED:
                    rows.append((path.split("/")[-1], view, None, r))
    # text table
    w1 = max(len(r[1]) for r in rows if r[2] is not None) + 2
    print(f"{'file':10} {'view':{w1}} {'mid':>4} {'field':>5} "
          f"{'fan':>5} {'sym':>4} {'corr':>5} {'UNEXPLAINED':>11}")
    for r in rows:
        if len(r) < 3:
            continue
        counts = r[2]
        if counts is None:
            continue
        path, view = r[0], r[1]
        fanc = counts[FAN_MEMBER] + counts[FAN_SLOT]
        print(f"{path:10} {view:{w1}} {counts[MIDPOINT]:>4} "
              f"{counts[FIELD]:>5} {fanc:>5} {counts[SYMMETRIC]:>4} "
              f"{counts[CORRIDOR]:>5} {counts[UNEXPLAINED]:>11}")
    fanc = totals[FAN_MEMBER] + totals[FAN_SLOT]
    print(f"{'TOTAL':10} {'':{w1}} {totals[MIDPOINT]:>4} "
          f"{totals[FIELD]:>5} {fanc:>5} {totals[SYMMETRIC]:>4} "
          f"{totals[CORRIDOR]:>5} {totals[UNEXPLAINED]:>11}")
    print("\nUNEXPLAINED anchors (node/side/coord, face context):")
    for r in rows:
        if not (len(r) == 4 and r[2] is None):
            continue
        path, view = r[0], r[1]
        rec = r[3]
        print(f"  {view}: {rec['node']} {rec['side']} @{rec['coord']} "
              f"({rec.get('reason', '')}) — {rec['source']} -> "
              f"{rec['target']}"
              + (f" [{rec['label']}]" if rec["label"] else ""))
    if args.out:
        payload = {"totals": totals, "views": {}}
        for path in args.files:
            report = audit_file(path)
            for view, endpoints in report.items():
                payload["views"][view] = endpoints
        with open(args.out, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=1)
        print(f"\nJSON: {args.out}")
    if args.gate and totals[UNEXPLAINED]:
        print(f"\nGATE FAIL: {totals[UNEXPLAINED]} unexplained anchors",)
        raise SystemExit(1)
    if args.gate:
        print("\nGATE PASS: zero unexplained anchors")


if __name__ == "__main__":
    main()
#!/usr/bin/env python3
"""
Generates into overrides/ the base game's road template models with an invisible wheel surface under every lane
divider and centre line, so crossing a lane line gives a light thump and the motorway edge keeps its own, harder
rumble.

The base game feels only its edge lines: they have invisible `colprkfh*` collision parts with the `rumble_stripe`
substance, 5 mm up. Lane lines are paint decals, which are not wheel surfaces. For each model, this tool takes every
line triangle (decal material whose texture name holds "line", not a chevron) from its visible parts, leaves out the
two outermost line positions across the road (the edges) and copies the rest, flat at HEIGHT_MM, into one new part
per source part. Each new part:
- is named `collbrkN`: the engine takes road wheel contact only from parts whose names start with `coll`
  (a part named `colbrkN` was never felt; in-game canaries, 2026-11-23);
- has its source part's visibility in every variant, so a road whose look has no painted line gets no bump;
- uses the model's own `coll` piece vertex layout and material /material/drivedogs/lane_feel.mat (in overrides/,
  substance `road`: a thump with no rumble sound; the user's pick of three tunings, 2026-11-25).
The original parts, pieces and visibilities are kept byte for byte. Decisions: plan world-lane-line-feel, ADR-0009.

Outputs: overrides/road_template/**/*.pmg + .pmd (git-ignored: regenerate with this tool) and the manifest
world/lane_strips.tsv (base sha256 of both files, strips and triangles added, output sha256 of both).

usage: python tools/lane_strips.py [--check]
  --check: rebuild the models in memory and fail if the manifest or the overrides on disk are out of date.
After a game update: extract the new base, bump base_game.version, rerun this tool.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import re
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import base_dir as base_ref_dir, reference_root, repo_game, ref_fetch, ref_list, ref_path  # noqa: E402

MANIFEST = ROOT / "world" / "lane_strips.tsv"
OVERRIDES = ROOT / "overrides"
MODEL_DIR = "road_template/"
MAT = "/material/drivedogs/lane_feel.mat"
PART_PREFIX = "collbrk"     # must start with "coll" to be a road wheel surface
HEIGHT_MM = 4.0             # road40: the edge rumble is 5 mm
MAX_TRI_W = 1.1             # wider line triangles are hatching or arrows (un double-line bands are 1.0 m)
GAP = 0.3                   # line triangles closer than this across the road are one line


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


# --- SCS tokens (names of parts and attributes: up to 12 of [0-9a-z_]) ---------------------------------------------
CH = "\0" + "0123456789abcdefghijklmnopqrstuvwxyz_"


def tok(v: int) -> str:
    s = ""
    while v:
        s += CH[v % 38]
        v //= 38
    return s


def tokv(s: str) -> int:
    v = 0
    for c in reversed(s):
        v = v * 38 + CH.index(c)
    return v


# --- .pmg v21 (geometry) ---------------------------------------------------------------------------------------------
PIECE = struct.Struct("<5I4f6fI9i")   # 100 B: idx count, verts, uv mask, uv channels, material, centre xyz, radius,
#                                       bb min/max, stride, 8 vertex stream offsets, index offset (all absolute)
PART = struct.Struct("<QIIII")        # 24 B: name token, piece count, first piece, attribute count, first attribute


class Pmg:
    def __init__(self, d: bytes, what: str) -> None:
        self.d = d
        H = list(struct.unpack_from("<28I", d, 0))
        if H[0] & 0xFF != 0x15:
            raise SystemExit(f"{what}: pmg version {H[0] & 0xFF:#x}, this tool reads 0x15")
        self.H = H
        pc, partc = H[1], H[2]
        self.parts = [list(PART.unpack_from(d, H[19] + 24 * i)) for i in range(partc)]
        self.pieces = [list(PIECE.unpack_from(d, H[21] + 100 * i)) for i in range(pc)]
        self.skeleton, self.locators = d[H[18]:H[19]], d[H[20]:H[21]]
        self.strings = d[H[22]:H[22] + H[23]]
        self.verts, self.index = d[H[24]:H[24] + H[25]], d[H[26]:H[26] + H[27]]
        if not (H[20] == H[19] + 24 * partc and H[22] == H[21] + 100 * pc and H[24] == H[22] + H[23]
                and H[26] == H[24] + H[25] and H[26] + H[27] == len(d)):
            raise SystemExit(f"{what}: unexpected pmg section layout")

    def name(self, i: int) -> str:
        return tok(self.parts[i][0])

    def positions(self, k: int) -> list[tuple[float, float, float]]:
        p = self.pieces[k]
        return [struct.unpack_from("<3f", self.d, p[16] + v * p[15]) for v in range(p[1])]

    def indices(self, k: int) -> list[int]:
        p = self.pieces[k]
        return list(struct.unpack_from(f"<{p[0]}H", self.d, p[24]))

    def with_pieces(self, new_parts: list[list[int]], new_pieces: list[tuple[list, bytes, bytes]]) -> bytes:
        """Appends parts and pieces; new piece records carry stream offsets relative to their own vertex bytes."""
        H = list(self.H)
        parts = self.parts + new_parts
        partc, pc = len(parts), len(self.pieces) + len(new_pieces)
        o_parts = 112 + len(self.skeleton)
        o_loc = o_parts + 24 * partc
        o_pieces = o_loc + len(self.locators)
        o_str = o_pieces + 100 * pc
        o_v = o_str + len(self.strings)
        vbytes, ibytes = bytearray(self.verts), bytearray(self.index)
        recs = []
        for p in self.pieces:
            p = list(p)
            for j in range(16, 24):
                if p[j] != -1:
                    p[j] += o_v - H[24]
            recs.append(p)
        added = []
        for rec, vb, ib in new_pieces:
            added.append((rec, len(vbytes), len(ibytes)))
            vbytes += vb
            ibytes += ib
        o_i = o_v + len(vbytes)
        for p in recs:
            p[24] += o_i - H[26]
        for rec, vo, io in added:
            p = list(rec)
            for j in range(16, 24):
                if p[j] != -1:
                    p[j] += o_v + vo
            p[24] = o_i + io
            recs.append(p)
        H[1], H[2] = pc, partc
        H[18], H[19], H[20], H[21] = 112, o_parts, o_loc, o_pieces
        H[22], H[23], H[24], H[25], H[26], H[27] = o_str, len(self.strings), o_v, len(vbytes), o_i, len(ibytes)
        out = [struct.pack("<28I", *H), self.skeleton]
        out += [PART.pack(*p) for p in parts] + [self.locators] + [PIECE.pack(*p) for p in recs]
        out += [self.strings, bytes(vbytes), bytes(ibytes)]
        return b"".join(out)


# --- .pmd v4 (looks, variants, part visibility, materials) -----------------------------------------------------------
class Pmd:
    HEADER = struct.Struct("<16I")

    def __init__(self, data: bytes, what: str) -> None:
        (ver, self.materials, looks, self.pieces, variants, self.parts, attribs, self.values_size, strings_size,
         look_off, variant_off, part_off, values_off, attrib_off, table_off, strings_off) = self.HEADER.unpack_from(data)
        if ver != 4 or strings_off + strings_size != len(data):
            raise SystemExit(f"{what}: pmd version {ver} or layout this tool does not read")
        self.looks = list(struct.unpack_from(f"<{looks}Q", data, look_off))
        self.variants = list(struct.unpack_from(f"<{variants}Q", data, variant_off))
        self.part_ranges = [list(struct.unpack_from("<II", data, part_off + 8 * i)) for i in range(self.parts)]
        self.attrib_defs = [list(struct.unpack_from("<QII", data, attrib_off + 16 * i)) for i in range(attribs)]
        self.values = [bytearray(data[values_off + i * self.values_size:values_off + (i + 1) * self.values_size])
                       for i in range(variants)]
        rows = struct.unpack_from(f"<{looks * self.materials}I", data, table_off)
        self.table = [[o - strings_off for o in rows[i * self.materials:(i + 1) * self.materials]] for i in range(looks)]
        self.strings = bytearray(data[strings_off:])

    def material(self, i: int, look: int = 0) -> str:
        return bytes(self.strings[self.table[look][i]:]).split(b"\0")[0].decode()

    def visible(self, part: int) -> list[int]:
        a, b = self.part_ranges[part]
        for t, _typ, off in self.attrib_defs[a:b]:
            if tok(t) == "visible":
                return [struct.unpack_from("<I", v, off)[0] for v in self.values]
        raise SystemExit(f"part {part} has no visible attribute")

    def add_material(self, path: str) -> int:
        off = len(self.strings)
        self.strings += path.encode() + b"\0"
        for row in self.table:
            row.append(off)
        self.materials += 1
        return self.materials - 1

    def add_part(self, vis: list[int]) -> None:
        a = len(self.attrib_defs)
        self.attrib_defs.append([tokv("visible"), 0, self.values_size])
        for v, val in zip(self.values, vis):
            v += struct.pack("<I", val)
        self.values_size += 4
        self.part_ranges.append([a, a + 1])
        self.parts += 1

    def to_bytes(self) -> bytes:
        look_off = 64
        variant_off = look_off + 8 * len(self.looks)
        part_off = variant_off + 8 * len(self.variants)
        attrib_off = part_off + 8 * self.parts
        values_off = attrib_off + 16 * len(self.attrib_defs)
        table_off = values_off + self.values_size * len(self.variants)
        strings_off = table_off + 4 * self.materials * len(self.looks)
        out = [self.HEADER.pack(4, self.materials, len(self.looks), self.pieces, len(self.variants), self.parts,
                                len(self.attrib_defs), self.values_size, len(self.strings), look_off, variant_off,
                                part_off, values_off, attrib_off, table_off, strings_off),
               struct.pack(f"<{len(self.looks)}Q", *self.looks),
               struct.pack(f"<{len(self.variants)}Q", *self.variants)]
        out += [struct.pack("<II", *r) for r in self.part_ranges]
        out += [struct.pack("<QII", *a) for a in self.attrib_defs]
        out += [bytes(v) for v in self.values]
        out += [struct.pack(f"<{len(self.looks) * self.materials}I", *(o + strings_off for r in self.table for o in r))]
        out += [bytes(self.strings)]
        return b"".join(out)


# --- strips ----------------------------------------------------------------------------------------------------------
class Inputs:
    def __init__(self) -> None:
        ref = reference_root(repo_game(ROOT))
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = base_ref_dir(ref, mp["base_game"]["version"])
        if not self.base.is_dir():
            sys.exit(f"missing {self.base} — extract-reference base")
        # a template a merged source also ships would need its strips built on that winner instead
        self.shipped: dict[str, str] = {}
        for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if row and not row[0].startswith("#") and row[0] != "path":
                    self.shipped[row[0].lower()] = s["id"]
        self._line: dict[str, bool] = {}

    def models(self) -> list[str]:
        """Every road template model except the far LODs (no collision there)."""
        return [p for p in ref_list(self.base, MODEL_DIR, ".pmg") if "_far" not in p.rsplit("/", 1)[-1]]

    def is_line_mat(self, path: str) -> bool:
        if path not in self._line:
            f = ref_path(self.base, path.lstrip("/"))
            ok = False
            if f.is_file():
                t = f.read_text(encoding="utf-8", errors="replace")
                eff = re.search(r'effect\s*:\s*"([^"]+)"', t)
                tex = [s.rsplit("/", 1)[-1] for s in re.findall(r'source\s*:\s*"([^"]+)"', t)]
                ok = bool(eff and "decal" in eff.group(1) and any("line" in s and "chevron" not in s for s in tex))
            self._line[path] = ok
        return self._line[path]


def face_up_sign(g: Pmg, k: int) -> float:
    """Sign (as a value) of the y component of the first triangle normal of piece k."""
    P, I = g.positions(k), g.indices(k)
    a, b, c = P[I[0]], P[I[1]], P[I[2]]
    u = [b[i] - a[i] for i in range(3)]
    v = [c[i] - a[i] for i in range(3)]
    return u[2] * v[0] - u[0] * v[2]


def add_strips(i: Inputs, rel: str, pmg: bytes, pmd: bytes) -> tuple[bytes, bytes, int, int] | None:
    """-> (pmg, pmd, strips added, triangles added), or None when the model has no lane line to cover."""
    g, m = Pmg(pmg, f"base {rel}"), Pmd(pmd, f"base {rel[:-4]}.pmd")
    if m.parts != len(g.parts):
        sys.exit(f"{rel}: pmd and pmg part counts differ")
    names = [g.name(k) for k in range(len(g.parts))]
    if any(n.startswith(PART_PREFIX) for n in names):
        sys.exit(f"{rel}: already has a {PART_PREFIX}* part — the base game changed; review this tool")
    coll = [k for k, n in enumerate(names) if n.startswith("coll")]
    if not coll:
        return None
    line_mi = {k for k in range(m.materials) if i.is_line_mat(m.material(k))}
    tris: dict[int, list] = {}
    for k, pt in enumerate(g.parts):
        if names[k].startswith("col"):
            continue
        for piece in range(pt[2], pt[2] + pt[1]):
            if g.pieces[piece][4] not in line_mi:
                continue
            P, I = g.positions(piece), g.indices(piece)
            for t in range(0, len(I), 3):
                tri = [P[I[t]], P[I[t + 1]], P[I[t + 2]]]
                xs = [q[0] for q in tri]
                if max(xs) - min(xs) <= MAX_TRI_W:
                    tris.setdefault(k, []).append(tri)
    if not tris:
        return None
    clusters: list[list[float]] = []
    for a, b in sorted((min(q[0] for q in t), max(q[0] for q in t)) for ts in tris.values() for t in ts):
        if clusters and a - clusters[-1][1] < GAP:
            clusters[-1][1] = max(clusters[-1][1], b)
        else:
            clusters.append([a, b])
    edges = [clusters[0], clusters[-1]] if len(clusters) >= 2 else []

    def on_edge(t: list) -> bool:
        xc = sum(q[0] for q in t) / 3
        return any(a - 1e-4 <= xc <= b + 1e-4 for a, b in edges)

    keep_by_part = {k: [t for t in ts if not on_edge(t)] for k, ts in tris.items()}
    keep_by_part = {k: ts for k, ts in keep_by_part.items() if ts}
    if not keep_by_part:
        return None

    ck = g.parts[coll[0]][2]
    cp = g.pieces[ck]
    stride = cp[15]
    rel_off = [x - cp[16] if x != -1 else -1 for x in cp[16:24]]
    if not (rel_off[0] == 0 and rel_off[1] == 12 and rel_off[3] == 24
            and all(r == -1 or 0 <= r < stride for r in rel_off)):
        sys.exit(f"{rel}: coll vertex layout {cp[15:24]} is not position, normal, colour first — review this tool")
    up = face_up_sign(g, ck)
    color = struct.unpack_from("<I", g.d, cp[19])[0]
    height = HEIGHT_MM / 1000
    mat = m.add_material(MAT)
    new_parts, new_pieces, ntris = [], [], 0
    for k, keep in keep_by_part.items():
        vmap: dict[tuple[float, float], int] = {}
        vb, idx = bytearray(), []
        for t in keep:
            ids = []
            for q in t:
                key = (round(q[0], 4), round(q[2], 4))
                if key not in vmap:
                    vmap[key] = len(vmap)
                    v = bytearray(stride)        # uv and any other stream stay 0
                    struct.pack_into("<3f3fI", v, 0, q[0], height, q[2], 0.0, 1.0, 0.0, color)
                    vb += v
                ids.append(vmap[key])
            a, b, c = t
            ny = (b[2] - a[2]) * (c[0] - a[0]) - (b[0] - a[0]) * (c[2] - a[2])
            idx += ids if (ny > 0) == (up > 0) else [ids[0], ids[2], ids[1]]
        if len(vmap) > 65535:
            sys.exit(f"{rel} {names[k]}: too many strip vertices")
        xs = [q[0] for t in keep for q in t]
        zs = [q[2] for t in keep for q in t]
        bb = (min(xs), height, min(zs), max(xs), height, max(zs))
        cx, cz = (bb[0] + bb[3]) / 2, (bb[2] + bb[5]) / 2
        rad = ((bb[3] - cx) ** 2 + (bb[5] - cz) ** 2) ** 0.5
        rec = [len(idx), len(vmap), cp[2], cp[3], mat, cx, height, cz, rad, *bb, stride] + rel_off + [-1]
        new_pieces.append((rec, bytes(vb), struct.pack(f"<{len(idx)}H", *idx)))
        new_parts.append([tokv(f"{PART_PREFIX}{len(new_parts)}"), 1, len(g.pieces) + len(new_pieces) - 1, 0, 0])
        m.add_part(m.visible(k))
        ntris += len(keep)
    out_pmg, out_pmd = g.with_pieces(new_parts, new_pieces), m.to_bytes()
    verify(rel, pmg, pmd, out_pmg, out_pmd, [k for k in keep_by_part])
    return out_pmg, out_pmd, len(new_parts), ntris


def verify(rel: str, pmg: bytes, pmd: bytes, out_pmg: bytes, out_pmd: bytes, src_parts: list[int]) -> None:
    """The original model is unchanged, and each strip is well formed, at HEIGHT_MM, seen where its line is."""
    a, b = Pmg(pmg, rel), Pmg(out_pmg, f"built {rel}")
    ma, mb = Pmd(pmd, rel), Pmd(out_pmd, f"built {rel}")
    errs = []
    if mb.parts != len(b.parts) or len(b.parts) != len(a.parts) + len(src_parts):
        errs.append("part counts")
    if b.parts[:len(a.parts)] != a.parts:
        errs.append("original parts changed")
    if b.verts[:len(a.verts)] != a.verts or b.index[:len(a.index)] != a.index:
        errs.append("original vertex or index data changed")
    dv, di = b.H[24] - a.H[24], b.H[26] - a.H[26]
    for k in range(len(a.pieces)):
        pa, pb = a.pieces[k], b.pieces[k]
        moved = [x + dv if x != -1 else -1 for x in pa[16:24]] + [pa[24] + di]
        if pa[:16] != pb[:16] or pb[16:25] != moved:
            errs.append(f"piece {k} changed")
    if any(ma.visible(k) != mb.visible(k) for k in range(len(a.parts))):
        errs.append("original visibility changed")
    if ma.table != [row[:-1] for row in mb.table] or ma.looks != mb.looks or ma.variants != mb.variants:
        errs.append("looks, variants or materials changed")
    if mb.material(mb.materials - 1) != MAT:
        errs.append("strip material")
    for j, k in enumerate(src_parts):
        n = len(a.parts) + j
        piece = b.parts[n][2]
        P, I = b.positions(piece), b.indices(piece)
        if b.name(n) != f"{PART_PREFIX}{j}" or mb.visible(n) != ma.visible(k):
            errs.append(f"strip {j} name or visibility")
        if not I or len(I) % 3 or max(I) >= len(P) or b.pieces[piece][4] != mb.materials - 1:
            errs.append(f"strip {j} indices or material")
        if {round(q[1], 6) for q in P} != {round(HEIGHT_MM / 1000, 6)}:
            errs.append(f"strip {j} height")
    if errs:
        sys.exit(f"{rel}: built model fails its check: {'; '.join(errs[:5])}")


def build(i: Inputs) -> tuple[list[list[str]], dict[str, bytes]]:
    """Manifest rows [path, base pmg sha, base pmd sha, strips, triangles], output bytes per path."""
    models = i.models()
    if not models:
        sys.exit(f"the base game ({i.base.name}) lists no {MODEL_DIR}*.pmg")
    files = ref_fetch(i.base, [p for m in models for p in (m, m[:-4] + ".pmd")])
    rows, outs = [], {}
    for n, rel in enumerate(models):
        pmg_file, pmd_file = files[2 * n], files[2 * n + 1]
        if not pmg_file.is_file() or not pmd_file.is_file():
            sys.exit(f"{rel}: the base game ({i.base.name}) has no such model pair")
        pmg, pmd = pmg_file.read_bytes(), pmd_file.read_bytes()
        res = add_strips(i, rel, pmg, pmd)
        if res is None:
            continue
        for p in (rel, rel[:-4] + ".pmd"):
            if p.lower() in i.shipped:
                sys.exit(f"{p} is shipped by source {i.shipped[p.lower()]} — build its strips on that winner first")
        outs[rel], outs[rel[:-4] + ".pmd"] = res[0], res[1]
        rows.append([rel, sha(pmg), sha(pmd), str(res[2]), str(res[3])])
    return rows, outs


def read_manifest() -> tuple[list[list[str]], dict[str, str]]:
    rows, outs = [], {}
    if MANIFEST.is_file():
        for row in csv.reader(MANIFEST.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "path":
                rows.append(row[:5])
                outs[row[0]], outs[row[0][:-4] + ".pmd"] = row[5], row[6]
    return rows, outs


def write_manifest(rows: list[list[str]], outs: dict[str, bytes]) -> None:
    lines = [f"# GENERATED by tools/lane_strips.py — do not edit by hand. Strips {HEIGHT_MM:g} mm, material {MAT}.",
             "path\tbase_pmg_sha256\tbase_pmd_sha256\tstrips\ttriangles\toutput_pmg_sha256\toutput_pmd_sha256"]
    lines += ["\t".join(r + [sha(outs[r[0]]), sha(outs[r[0][:-4] + ".pmd"])]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def stale(outs: dict[str, bytes]) -> list[pathlib.Path]:
    return [f for f in (OVERRIDES / MODEL_DIR).rglob("*") if f.suffix in (".pmg", ".pmd")
            and f.relative_to(OVERRIDES).as_posix() not in outs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if not (OVERRIDES / MAT.lstrip("/")).is_file():
        sys.exit(f"missing overrides{MAT}")
    rows, outs = build(Inputs())
    print(f"{len(rows)} models, {sum(int(r[3]) for r in rows)} strips, {sum(int(r[4]) for r in rows)} triangles")

    if args.check:
        old_rows, old_outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (base game or this tool)")
        for rel, data in outs.items():
            f = OVERRIDES / rel
            if old_outs.get(rel) != sha(data) or not f.is_file() or sha(f.read_bytes()) != sha(data):
                problems.append(f"{f.relative_to(ROOT).as_posix()} missing or changed")
        problems += [f"{f.relative_to(ROOT).as_posix()} is not produced by this tool any more" for f in stale(outs)]
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/lane_strips.py")
        return 1 if problems else 0

    for f in stale(outs):
        f.unlink()
        print(f"removed stale {f.relative_to(ROOT).as_posix()}")
    for rel, data in outs.items():
        f = OVERRIDES / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    write_manifest(rows, outs)
    print(f"wrote {MANIFEST.relative_to(ROOT)}, {len(rows)} models to overrides/{MODEL_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

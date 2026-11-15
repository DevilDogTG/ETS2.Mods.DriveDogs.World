#!/usr/bin/env python3
"""
Generates into overrides/ the base game's asphalt-patch decal models with a low bump the wheels feel: Daniel's
Random Events Mod (Daniel, https://forum.scssoft.com/viewtopic.php?t=265242) gives `newapsh_decal`, `_1` and `_2`
the collision parts `startcol`, `centercol` and `endcol`, flat copies of the visible patch at its own height (20 mm,
13.4 mm for `_1`): a sharp step on and off. World carries his idea at a lower height the maintainer picked in a
playtest (2026-11-15, test package `half`): 10 mm, 6.5 mm for `_1`. Decisions: plan world-patch-bump.

Built on the current base game, not on Daniel's 2024 re-export: every base part, piece and vertex is kept byte for
byte (the game's own look and materials), and one collision part per visible part is appended, named as Daniel named
them (the engine collides with them; the base patch has none). Each is the visible piece's triangles, flat at the
height below, in the base game's own collision format: SCS's road collision material
`/automat/04/045631c4dd16cdaf.mat` (`eut2.none`, substance `road`, as on every road template's `coll` part), so it is
not drawn and the wheels meet the road's own surface; stride 28 (position, normal (0,1,0), colour), no uv. The .pmd
gets that material and the three parts, visible in every variant.

Where the game places them: `building_scheme` mod_scene_8/9/10 in SCS's patch scenes (map/scenes/decal_build_3/4/5,
decal_build_l_1/2) and Daniel's asphalt-patch road events (`_1` only there).

Outputs: overrides/model2/props/street/<model>.pmd/.pmg (git-ignored: regenerate with this tool) and the manifest
world/patch_bump.tsv (base sha256, collision height, output sha256).

usage: python tools/patch_bump.py [--check]
  --check: rebuild the models in memory and fail if the manifest or the overrides on disk are out of date.
After a game update: extract the new base, bump base_game.version, rerun this tool (it fails loudly if SCS changed
a patch model's parts or made it non-flat).
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import math
import pathlib
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import base_dir as base_ref_dir, reference_root, repo_game, ref_fetch, ref_path  # noqa: E402
from pmg import HEADER, PART, PIECE, Pmg, token_value  # noqa: E402
from model_variants import Pmd  # noqa: E402  (the .pmd reader/writer World already uses)

MANIFEST = ROOT / "world" / "patch_bump.tsv"
OVERRIDES = ROOT / "overrides"
MODEL_DIR = "model2/props/street/"
# collision plate height (m) per model; the visible patch stays at the base game's height (20 mm, 13.4 mm for _1)
HEIGHTS = {"newapsh_decal": 0.010, "newapsh_decal_1": 0.0065, "newapsh_decal_2": 0.010}
VISIBLE = ("center", "end", "start")            # the base parts; each gets <name> + "col"
COL_MATERIAL = "/automat/04/045631c4dd16cdaf.mat"   # base road collision: eut2.none.rfx, substance "road"
COL_COLOR = 0xFF000000                          # the colour the base collision pieces carry
COL_STRIDE = 28                                 # position, normal, colour
VERTEX = struct.Struct("<3f3fI")


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Inputs:
    def __init__(self) -> None:
        ref = reference_root(repo_game(ROOT))
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = base_ref_dir(ref, mp["base_game"]["version"])
        if not self.base.is_dir():
            sys.exit(f"missing {self.base} — extract-reference base")
        # a model a merged source also ships would need the collision parts carried onto that winner instead
        self.shipped: dict[str, str] = {}
        for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if row and not row[0].startswith("#") and row[0] != "path":
                    self.shipped[row[0].lower()] = s["id"]


def positions(g: Pmg, k: int) -> list[tuple[float, float, float]]:
    p = g.pieces[k]
    return [struct.unpack_from("<3f", g.data, p[16] + v * p[15]) for v in range(p[1])]


def indices(g: Pmg, k: int) -> bytes:
    p = g.pieces[k]
    return g.data[p[24]:p[24] + 2 * p[0]]


def with_collision(rel: str, data: bytes, height: float, material: int) -> bytes:
    """The .pmg with one flat collision piece per visible part appended (part `<name>col`, material index
    `material`), at `height`. Existing bytes are kept; sections after the parts shift, and the model bounds grow to
    take the plates in."""
    g = Pmg(data, f"base {rel}")
    if (g.skeleton_off != HEADER.size or g.parts_off + PART.size * g.part_count != g.locators_off
            or g.locators_off != g.pieces_off):
        sys.exit(f"{rel}: unexpected section layout before the pieces")
    names = [p[0] for p in g.parts]
    if sorted(names) != sorted(VISIBLE) or g.locator_count or g.bone_count:
        sys.exit(f"{rel}: parts {names}, {g.locator_count} locators, {g.bone_count} bones — expected only "
                 f"{list(VISIBLE)}: the base model changed, review the collision parts")
    new_parts, new_pieces = [], []          # (part record), (piece record, vertex bytes, index bytes)
    for name, count, first, _, _ in g.parts:
        if count != 1:
            sys.exit(f"{rel} {name}: {count} pieces, expected 1")
        p = g.pieces[first]
        P = positions(g, first)
        ys = [y for _, y, _ in P]
        if max(ys) - min(ys) > 1e-4 or min(ys) <= height:   # exporter float noise is ~5e-8
            sys.exit(f"{rel} {name}: visible patch at y {min(ys):.6f}..{max(ys):.6f}, expected flat and above {height}")
        vb = b"".join(VERTEX.pack(x, height, z, 0.0, 1.0, 0.0, COL_COLOR) for x, _, z in P)
        ib = indices(g, first)
        ib += b"\0" * (-len(ib) % 4)        # each piece's indices start 4-byte aligned, as the exporter writes them
        rec = [p[0], p[1], -1, 0, material,
               p[5], height, p[7], p[8],                      # sphere: the visible piece's, moved down
               p[9], height, p[11], p[12], height, p[14],     # box: the visible piece's, flat at the height
               COL_STRIDE] + [-1] * 9
        new_pieces.append((rec, vb, ib))
        new_parts.append([token_value(name + "col"), 1, g.piece_count + len(new_parts), 0, 0])

    grow = PART.size * len(new_parts) + PIECE.size * len(new_pieces)
    vertex_off = g.vertex_off + grow
    index_off = vertex_off + g.vertex_size + sum(len(vb) for _, vb, _ in new_pieces)
    pieces = []
    for p in g.pieces:
        p = list(p)
        for f in range(16, 24):
            if p[f] >= 0:
                p[f] += grow
        p[24] += index_off - g.index_off
        pieces.append(p)
    vo, io = vertex_off + g.vertex_size, index_off + g.index_size
    for rec, vb, ib in new_pieces:
        rec[16], rec[17], rec[19] = vo, vo + 12, vo + 24
        rec[24] = io
        pieces.append(rec)
        vo += len(vb)
        io += len(ib)

    # HEADER fields: 2 piece count, 3 part count, 8-10 sphere centre, 11 radius, 12-14 box min, 15-17 box max,
    # 18 skeleton, 19 parts, 20 locators, 21 pieces, 22/23 string pool, 24/25 vertex pool, 26/27 index pool
    header = list(HEADER.unpack_from(data, 0))
    header[2] += len(new_pieces)
    header[3] += len(new_parts)
    header[20] += PART.size * len(new_parts)
    header[21] += PART.size * len(new_parts)
    header[22] += grow
    header[24] += grow
    header[25] = g.vertex_size + sum(len(vb) for _, vb, _ in new_pieces)
    header[26] = index_off
    header[27] = g.index_size + sum(len(ib) for _, _, ib in new_pieces)
    every = [q for k in range(g.piece_count) for q in positions(g, k)] + \
            [(x, height, z) for _, vb, _ in new_pieces for x, _, z in
             (VERTEX.unpack_from(vb, i)[:3] for i in range(0, len(vb), VERTEX.size))]
    center = header[8:11]
    header[11] = max(header[11], max(math.dist(center, q) for q in every))
    header[13] = min(q[1] for q in every)
    header[16] = max(q[1] for q in every)

    out = bytearray(HEADER.pack(*header))
    out += data[g.skeleton_off:g.parts_off]
    out += data[g.parts_off:g.parts_off + PART.size * g.part_count]
    out += b"".join(PART.pack(*p) for p in new_parts)
    out += data[g.locators_off:g.pieces_off]
    out += b"".join(PIECE.pack(*p) for p in pieces)
    out += data[g.pool_off:g.pool_off + g.pool_size]
    out += data[g.vertex_off:g.vertex_off + g.vertex_size]
    out += b"".join(vb for _, vb, _ in new_pieces)
    out += data[g.index_off:g.index_off + g.index_size]
    out += b"".join(ib for _, _, ib in new_pieces)
    Pmg(bytes(out), f"patched {rel}")       # re-parse: section layout must hold
    return bytes(out)


def with_collision_parts(rel: str, data: bytes) -> tuple[bytes, int]:
    """The .pmd with the collision material added to every look and one part per visible part, visible in every
    variant. Returns (bytes, the new material's index)."""
    m = Pmd(data, f"base {rel}")
    if m.parts != len(VISIBLE):
        sys.exit(f"{rel}: {m.parts} parts in the .pmd, expected {len(VISIBLE)}")
    material = m.materials
    off = len(m.strings)
    m.strings += COL_MATERIAL.encode("ascii") + b"\0"
    for row in m.table:
        row.append(off)
    m.materials += 1
    ranges, defs = bytearray(m.part_ranges), bytearray(m.attrib_defs)
    values = [bytearray(v) for v in m.values]
    for _ in VISIBLE:
        a = m.attribs
        ranges += struct.pack("<II", a, a + 1)
        defs += struct.pack("<QII", token_value("visible"), 0, m.values_size)
        for v in values:
            v += struct.pack("<I", 1)
        m.values_size += 4
        m.attribs += 1
        m.parts += 1
    m.part_ranges, m.attrib_defs, m.values = bytes(ranges), bytes(defs), [bytes(v) for v in values]
    return m.to_bytes(), material


def build(i: Inputs) -> tuple[list[list[str]], dict[str, bytes]]:
    """Manifest rows [path, base sha, height mm], output bytes per path."""
    rels = [f"{MODEL_DIR}{m}{x}" for m in HEIGHTS for x in (".pmd", ".pmg")]
    ref_fetch(i.base, rels)
    rows, outs = [], {}
    for model, height in HEIGHTS.items():
        pmd_rel, pmg_rel = f"{MODEL_DIR}{model}.pmd", f"{MODEL_DIR}{model}.pmg"
        data = {}
        for rel in (pmd_rel, pmg_rel):
            if rel.lower() in i.shipped:
                sys.exit(f"{rel} is shipped by source {i.shipped[rel.lower()]} — carry the collision onto that winner")
            f = ref_path(i.base, rel)
            if not f.is_file():
                sys.exit(f"{rel}: the base game ({i.base.name}) has no such model")
            data[rel] = f.read_bytes()
        outs[pmd_rel], material = with_collision_parts(pmd_rel, data[pmd_rel])
        outs[pmg_rel] = with_collision(pmg_rel, data[pmg_rel], height, material)
        for rel in (pmd_rel, pmg_rel):
            rows.append([rel, sha(data[rel]), f"{height * 1000:g}"])
    return rows, outs


def read_manifest() -> tuple[list[list[str]], dict[str, str]]:
    rows, outs = [], {}
    if MANIFEST.is_file():
        for row in csv.reader(MANIFEST.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "path":
                rows.append(row[:3])
                outs[row[0]] = row[3]
    return rows, outs


def write_manifest(rows: list[list[str]], outs: dict[str, bytes]) -> None:
    lines = ["# GENERATED by tools/patch_bump.py — do not edit by hand.",
             "path\tbase_sha256\tcollision_mm\toutput_sha256"]
    lines += ["\t".join(r + [sha(outs[r[0]])]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def stale(outs: dict[str, bytes]) -> list[pathlib.Path]:
    """Overrides this tool wrote before (in the old manifest) but no longer produces."""
    return [OVERRIDES / r[0] for r in read_manifest()[0] if r[0] not in outs and (OVERRIDES / r[0]).is_file()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    rows, outs = build(Inputs())
    print(f"{len(HEIGHTS)} patch models, collision at " + ", ".join(f"{m} {h * 1000:g} mm" for m, h in HEIGHTS.items()))

    if args.check:
        old_rows, old_outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (base game or heights)")
        for rel, data in outs.items():
            f = OVERRIDES / rel
            if old_outs.get(rel) != sha(data) or not f.is_file() or sha(f.read_bytes()) != sha(data):
                problems.append(f"{f.relative_to(ROOT).as_posix()} missing or changed")
        problems += [f"{f.relative_to(ROOT).as_posix()} is not produced by this tool any more" for f in stale(outs)]
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/patch_bump.py")
        return 1 if problems else 0

    for f in stale(outs):
        f.unlink()
        print(f"removed stale {f.relative_to(ROOT).as_posix()}")
    for rel, data in outs.items():
        f = OVERRIDES / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    write_manifest(rows, outs)
    print(f"wrote {MANIFEST.relative_to(ROOT)}, {len(outs)} files to overrides/{MODEL_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

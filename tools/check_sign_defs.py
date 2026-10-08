#!/usr/bin/env python3
"""
Checks that every sign atlas and frame definition World ships matches the texture that wins in the build.

Sign atlas (`def/sign/atlas/*.sii`, images_coords) and frame (`def/sign/frame/*.sii`, *_coords_l/r/b/t)
definitions give texture coordinates in pixels. A source that ships larger textures needs its own definitions
scaled to them, and a definition must follow whichever texture wins. Otherwise the game draws part of each image
(DBM Road Signs 2.1 shipped 4x textures without definitions: every sign showed the top-left quarter, World
1.0.0-1.2.0-dev.2). `megapack check` cannot see this: the paths are all valid, only the numbers disagree.

For each definition whose definition or texture is not the base game's, the expected coordinates are the base
game's scaled by (winning texture size / base texture size), +-1 px. A definition the base game lacks is checked
against its texture's bounds. Winners are read from the lock (lock/<source>.tsv, lock/collisions.tsv) and
overrides/, as the build resolves them, so rerun `megapack lock` first.

usage: python tools/check_sign_defs.py
Read-only: writes nothing. Exits 1 and lists each mismatch. Run before every build (see README).
"""
from __future__ import annotations

import csv
import pathlib
import re
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section, ref_path  # noqa: E402

LOCK = ROOT / "lock"
OVERRIDES = ROOT / "overrides"
DEF_DIRS = ("def/sign/atlas/", "def/sign/frame/")
COORDS = re.compile(r"images_coords\[\d*\]\s*:\s*\(([^)]*)\)")
FRAME_KEY = re.compile(r"^\s*(\w+_coords_[lrbt])\s*:\s*(-?[\d.]+)", re.M)
DDS_IN_TOBJ = re.compile(rb"(/[\x21-\x7e]+?\.dds)")
SOURCE = re.compile(r'(?:source|texture)\s*:\s*"([^"]+\.tobj)"')   # new-style `source`, old-style `texture`
MATERIAL = re.compile(r'(?:material_path|material)\s*:\s*"([^"]+)"')


class Tree:
    """Which file the build ships at a path: overrides/, else the lock's winner, else the base game."""

    def __init__(self) -> None:
        ref_root = pathlib.Path(host_section("Extracted Reference Root")["root"])
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
        self.base = ref_root / "base" / str(mp["base_game"]["version"])
        self.dirs = {s["id"]: ref_root / "workshop" / str(s["workshop"]) / str(s["version"]) for s in src}
        for p in [self.base, *self.dirs.values()]:
            if not p.is_dir():
                sys.exit(f"missing extraction {p} — run extract-reference first")
        self.owner: dict[str, tuple[str, str]] = {}   # lower-case path -> (source id, path as locked)
        for sid in self.dirs:
            tsv = LOCK / f"{sid}.tsv"
            if not tsv.is_file():
                sys.exit(f"missing {tsv} — run megapack lock first")
            for line in tsv.read_text(encoding="utf-8").splitlines():
                if line and not line.startswith("#"):
                    rel = line.split("\t", 1)[0]
                    self.owner.setdefault(rel.lower(), (sid, rel))
        with open(LOCK / "collisions.tsv", encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f, delimiter="\t"):
                if row["winner"] in self.dirs:
                    self.owner[row["path"].lower()] = (row["winner"], row["path"])

    def find(self, rel: str) -> tuple[str, pathlib.Path | None]:
        """-> (owner: 'overrides' | source id | 'base', file or None when nobody ships it)."""
        rel = rel.lstrip("/")
        if (OVERRIDES / rel).is_file():
            return "overrides", OVERRIDES / rel
        if rel.lower() in self.owner:
            sid, locked = self.owner[rel.lower()]
            return sid, self.dirs[sid] / locked
        p = ref_path(self.base, rel)          # base assets are fetched on demand
        return ("base", p) if p.is_file() else ("base", None)

    def defs(self) -> list[str]:
        rels = {p.relative_to(self.base).as_posix() for d in DEF_DIRS for p in (self.base / d).glob("*.sii")}
        rels |= {locked for _, locked in self.owner.values() if locked.startswith(DEF_DIRS)}
        rels |= {p.relative_to(OVERRIDES).as_posix() for d in DEF_DIRS for p in (OVERRIDES / d).glob("*.sii")}
        return sorted(rels)


def read(p: pathlib.Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def dds_size(p: pathlib.Path) -> tuple[int, int]:
    head = p.read_bytes()[:20]
    if head[:4] != b"DDS ":
        raise ValueError(f"not a DDS file: {p}")
    h, w = struct.unpack_from("<II", head, 12)
    return w, h


def texture(tree: Tree, mat_path: str, base_only: bool) -> tuple[str, pathlib.Path] | None:
    """Material -> its .tobj -> the .dds it names, each resolved as the build ships it (or from the base game)."""
    def get(rel: str) -> tuple[str, pathlib.Path | None]:
        if base_only:
            p = ref_path(tree.base, rel)
            return "base", p if p.is_file() else None
        return tree.find(rel)

    _, mat = get(mat_path)
    if mat is None:
        return None
    m = SOURCE.search(read(mat))
    if not m:
        return None
    tobj_rel = m.group(1) if m.group(1).startswith("/") else f"{pathlib.PurePosixPath(mat_path).parent}/{m.group(1)}"
    _, tobj = get(tobj_rel)
    if tobj is None:
        return None
    d = DDS_IN_TOBJ.search(tobj.read_bytes())
    dds_rel = d.group(1).decode() if d else str(pathlib.PurePosixPath(tobj_rel).with_suffix(".dds"))
    owner, dds = get(dds_rel)
    return (owner, dds) if dds is not None else None


def coords(text: str, frame: bool) -> list[tuple[str, float]]:
    """-> [(axis 'x' | 'y', value)] in file order: l/r scale with width, b/t with height."""
    if frame:
        return [("x" if k[-1] in "lr" else "y", float(v)) for k, v in sorted(FRAME_KEY.findall(text))]
    out = []
    for c in COORDS.findall(text):
        l, r, b, t = (float(v) for v in c.split(","))
        out += [("x", l), ("x", r), ("y", b), ("y", t)]
    return out


def check(tree: Tree, rel: str) -> str | None:
    frame = rel.startswith("def/sign/frame/")
    def_owner, def_file = tree.find(rel)
    if def_file is None:
        return None
    text = read(def_file)
    mat = MATERIAL.search(text)
    if not mat:
        return f"{rel} ({def_owner}): no material"
    tex = texture(tree, mat.group(1), base_only=False)
    if tex is None:
        return f"{rel} ({def_owner}): texture of {mat.group(1)} not found"
    tex_owner, tex_file = tex
    if def_owner == "base" and tex_owner == "base":
        return None                                    # the base game's own pair
    w, h = dds_size(tex_file)
    got = coords(text, frame)
    base_def = tree.base / rel
    if not base_def.is_file():                         # a source's own sign: stay inside its texture
        bad = [v for axis, v in got if v < -1 or v > (w if axis == "x" else h) + 1]
        return f"{rel} ({def_owner}): coords {bad[:4]} outside {w}x{h} texture ({tex_owner})" if bad else None
    base_text = read(base_def)
    base_tex = texture(tree, (MATERIAL.search(base_text) or mat).group(1), base_only=True)
    if base_tex is None:
        return f"{rel}: base game texture not found"
    bw, bh = dds_size(base_tex[1])
    want = [(axis, v * (w / bw if axis == "x" else h / bh)) for axis, v in coords(base_text, frame)]
    if len(want) != len(got):
        return f"{rel} ({def_owner}): {len(got) // (1 if frame else 4)} images, base game has {len(want) // (1 if frame else 4)}"
    off = [(g, round(x, 1)) for (_, g), (_, x) in zip(got, want) if abs(g - x) > 1.0]
    if off:
        return (f"{rel}: def from {def_owner}, {w}x{h} texture from {tex_owner} (base {bw}x{bh}): "
                f"coords {[g for g, _ in off[:4]]}, expected {[x for _, x in off[:4]]}")
    return None


def main() -> int:
    tree = Tree()
    rels = tree.defs()
    errors = [e for e in (check(tree, rel) for rel in rels) if e]
    for e in errors:
        print("MISMATCH", e)
    print(f"sign defs: {len(rels)} checked, {len(errors)} mismatch(es)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

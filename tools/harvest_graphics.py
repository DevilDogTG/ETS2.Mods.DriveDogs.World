#!/usr/bin/env python3
"""
Generates world/graphics.yaml: the game-config values World takes from its graphics sources, as edits of the
current base game (megapack `base_edits`). The sources ship these files as whole copies (excluded in
sources.yaml); a whole copy drops whatever the game added since the mod was made (Grass's terrain_material
copies lack 11 of 1.61's materials), so only the chosen values are carried. Decisions, one row per value:
plan world-graphics `assets/config-decisions.md`; the ADR is docs/adr/ADR-0002-world-graphics.md.

  diox-nature      def/game_data.sii                         leaves_lod_start/end (its economy keys, dead
                                                             ambient-sound keys and rain strengths are not taken)
  juninho-grass    def/world/detail_vegetation.sii           .grass density
  juninho-grass    def/world/terrain_material*.sii           color tints, except on materials whose textures
                                                             DIOX supplies alone (tuned for Grass's textures)
  realistic-rain   def/vehicle/interior_glass_config_rain.sii windshield drops (every value)

OURS holds World's own values (tuning after play tests); they replace a carried value of the same key.

Every value a source changes but World does not take is printed as `skip`, so a source update that adds a
change shows up in review. A carried unit or key missing from the base game aborts without writing.

usage: python tools/harvest_graphics.py [--check]    (--check: fail if world/graphics.yaml would change)
Inputs: the extracted-reference root of this host (profile host file), at the versions in megapack.yaml
(base_game) and sources.yaml.
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section  # noqa: E402
from siiedit import SiiFile  # noqa: E402

OUT = ROOT / "world" / "graphics.yaml"

# (source id, file, keys to carry; "*" = every key the source changes)
CARRY = [
    ("diox-nature", "def/game_data.sii", ["leaves_lod_start", "leaves_lod_end"]),
    ("juninho-grass", "def/world/detail_vegetation.sii", ["density"]),
    ("juninho-grass", "def/world/terrain_material.sii", ["color"]),
    ("juninho-grass", "def/world/terrain_material.base_share.sii", ["color"]),
    ("realistic-rain", "def/vehicle/interior_glass_config_rain.sii", ["*"]),
]
# World's own values: {file: {unit: {key: value}}}. Empty for the first build: the rain reflection strengths
# (rain_cube/planar/specular_strength) start at the base game's 0.9, which needs no edit.
OURS: dict[str, dict[str, dict[str, str]]] = {}
TINT_FILES = {"def/world/terrain_material.sii", "def/world/terrain_material.base_share.sii"}
TEX_SOURCE = re.compile(r'source\s*:\s*"([^"]+)"')
NUM = re.compile(r"^-?\d+(\.\d+)?$")


def canon(v: str) -> str:
    v = re.sub(r"\s+", "", v).strip('"')
    parts = v.strip("()").split(",")
    if all(NUM.match(p) for p in parts):
        nums = ",".join(str(float(p)) for p in parts)
        return f"({nums})" if v.startswith("(") else nums
    return v


def load() -> tuple[pathlib.Path, dict[str, pathlib.Path], list[str]]:
    """-> (base dir, {source id: extracted dir}, source ids from lowest to highest layer)."""
    ref_root = pathlib.Path(host_section("Extracted Reference Root")["root"])
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    base = ref_root / "base" / str(mp["base_game"]["version"])
    dirs = {s["id"]: ref_root / "workshop" / str(s["workshop"]) / str(s["version"]) for s in src if s.get("workshop")}
    for p in [base, *dirs.values()]:
        if not p.is_dir():
            sys.exit(f"missing extraction {p} — run extract-reference first")
    order = [s["id"] for s in sorted(src, key=lambda s: s["layer"])]
    excludes = {s["id"]: s.get("exclude") or [] for s in src}
    return base, {i: d for i, d in dirs.items()}, [i for i in order if i in dirs], excludes


def excluded(rel: str, patterns: list[str]) -> bool:
    return any(fnmatch.fnmatchcase(rel, p) for p in patterns if "/" in p)


def texture_owner(stem: str, base: pathlib.Path, dirs: dict, order: list[str], excludes: dict) -> str:
    """Which source wins a texture (its .tobj or .dds), or 'base'."""
    owner = "base" if any((base / (stem + e)).is_file() for e in (".tobj", ".dds")) else "missing"
    for sid in order:
        for ext in (".tobj", ".dds"):
            rel = stem + ext
            if (dirs[sid] / rel).is_file() and not excluded(rel, excludes[sid]):
                owner = sid
    return owner


def tint_kept(mat_path: str, base: pathlib.Path, dirs: dict, order: list[str], excludes: dict) -> tuple[bool, str]:
    """Grass tuned its tints for its own textures: drop the tint when DIOX supplies every non-vanilla texture."""
    mat = base / mat_path.lstrip("/")
    if not mat.is_file():
        return True, "material not in base"
    owners = set()
    for tex in TEX_SOURCE.findall(mat.read_text(encoding="utf-8", errors="replace")):
        path = tex if tex.startswith("/") else str(pathlib.PurePosixPath(mat_path).parent / tex)
        owners.add(texture_owner(re.sub(r"\.(tobj|dds)$", "", path.lstrip("/")), base, dirs, order, excludes))
    modded = owners - {"base", "missing"}
    diox_only = bool(modded) and all(o.startswith("diox-") for o in modded)
    return not diox_only, "+".join(sorted(owners))


def harvest(base: pathlib.Path, dirs: dict, order: list[str], excludes: dict) -> tuple[dict, list[str], list[str]]:
    edits: dict = {}
    skipped: list[str] = []
    errors: list[str] = []
    tint_counts = {"kept": 0, "dropped": 0}
    for sid, rel, keys in CARRY:
        bpath, mpath = base / rel, dirs[sid] / rel
        if not bpath.is_file() or not mpath.is_file():
            errors.append(f"{sid}: {rel}: missing in {'base' if not bpath.is_file() else 'source'}")
            continue
        b, m = SiiFile.read(bpath), SiiFile.read(mpath)
        missing = [u for u in b.order if u not in m.units]
        if missing:
            skipped.append(f"{sid}: {rel}: {len(missing)} base unit(s) the source lacks keep base values: "
                           + ", ".join(missing[:12]) + (" …" if len(missing) > 12 else ""))
        for unit in m.order:
            if unit not in b.units:
                skipped.append(f"{sid}: {rel}: unit {unit} not in base game")
                continue
            ukeys = {k for _, k, _ in m.units[unit].attrs} | {k for _, k, _ in b.units[unit].attrs}
            for key in sorted(ukeys):
                mv, bv = m.values(unit, key), b.values(unit, key)
                if [canon(v) for v in mv] == [canon(v) for v in bv]:
                    continue
                if not ("*" in keys or key in keys) or not mv:
                    skipped.append(f"{sid}: {rel}: {unit} {key}: {bv} -> {mv}")
                    continue
                if len(mv) > 1 and not key.endswith("[]"):
                    errors.append(f"{sid}: {rel}: {unit} {key}: set {len(mv)} times")
                    continue
                if rel in TINT_FILES and key == "color":
                    keep, owners = tint_kept(b.values(unit, "path")[0].strip('"'), base, dirs, order, excludes)
                    tint_counts["kept" if keep else "dropped"] += 1
                    if not keep:
                        skipped.append(f"{sid}: {rel}: {unit} color {mv[0]}: textures from {owners} (DIOX only)")
                        continue
                ops = edits.setdefault(rel, {}).setdefault(unit, {}).setdefault("set", {})
                ops[key] = mv if key.endswith("[]") else mv[0]
    for rel, units in OURS.items():
        b = SiiFile.read(base / rel)
        for unit, kv in units.items():
            if unit not in b.units:
                errors.append(f"OURS: {rel}: unit {unit} not in base game")
                continue
            edits.setdefault(rel, {}).setdefault(unit, {}).setdefault("set", {}).update(kv)
    skipped.append(f"terrain tints: {tint_counts['kept']} kept, {tint_counts['dropped']} dropped (DIOX textures)")
    return edits, skipped, errors


def render(edits: dict) -> str:
    head = (
        "# GENERATED by tools/harvest_graphics.py — do not edit by hand; change the script and rerun it.\n"
        "# Game-config values World takes from its graphics sources (and its own tuning), as edits of the base\n"
        "# game in megapack.yaml. See docs/adr/ADR-0002-world-graphics.md.\n")
    body = yaml.safe_dump({k: edits[k] for k in sorted(edits)}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    edits, skipped, errors = harvest(*load())
    for s in skipped:
        print(f"skip  {s}")
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    text = render(edits)
    n = sum(len(u) for u in edits.values())
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print(f"{OUT.relative_to(ROOT)} {'up to date' if same else 'OUT OF DATE'} ({len(edits)} files, {n} units)")
        return 0 if same else 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {len(edits)} files, {n} units, {len(skipped)} skip lines")
    return 0


if __name__ == "__main__":
    sys.exit(main())

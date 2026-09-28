#!/usr/bin/env python3
"""
Generates world/edits.yaml: the train and level-crossing edits World applies to the current base game
(megapack `base_edits`), harvested per unit from two Workshop mods that ship whole-file copies:

  Realistic Train Lengths 3209674677  trailer_chains[], lod_dist[] and the train physics values it
                                      carries (max_speed, engine_power, vehicle_mass, cargo_mass; these come
                                      from Sound Fixes Pack 26.66, which it was built on)
  Real Train Sounds (Cip) 2439106226  per-train sound_move/sound_horn, max_speed, crossing sounds[]

Only attributes listed in CARRY are taken, and only on units that exist in the base game, so units the base
game added since a mod was made (e.g. 1.61's traffic.frt.nl) keep their vanilla values instead of being
dropped. Lengths' sound lines and @includes (Sound Fixes Pack's) are not carried. Cip's edits are applied
after Lengths', so on a unit both change, Cip's max_speed wins.

Every carried value is checked: trailer_chains tokens must name a base-game trailer or trailer type, and every
`bank#event` must be an event of a bank Cip ships. Any failure aborts without writing.

usage: python tools/harvest_edits.py [--check]    (--check: fail if world/edits.yaml would change)
Inputs are read from the extracted-reference root of this host (profile host file), at the versions in
megapack.yaml (base_game, references) and sources.yaml (Cip).
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section  # noqa: E402
from siiedit import SiiFile  # noqa: E402

OUT = ROOT / "world" / "edits.yaml"
LENGTHS_ID, CIP_ID = 3209674677, 2439106226

CARRY = {
    "lengths": ["trailer_chains[]", "lod_dist[]", "max_speed", "engine_power", "vehicle_mass", "cargo_mass"],
    "cip": ["sound_move[]", "sound_horn[]", "sound_move", "max_speed", "sounds[]"],
}
# Cip ships these under pre-1.61 file names that no storage file includes any more; carried onto the
# current files. {old file: (current file, {old unit: current unit})}
RETARGET = {
    "def/vehicle/ai/locomotive_dv_12.sui": ("def/vehicle/ai/locomotive_dv_12.dlc_balt.sui",
                                           {"traffic.fs_dv_12": "traffic.fs_dv_12"}),
    "def/vehicle/ai/locomotive_e_405.sui": ("def/vehicle/ai/train_e_405_locomotive.sui",
                                           {"traffic.fs_e_405": "traffic.fs_e_405.it"}),
}
SII_SUFFIXES = {".sii", ".sui"}
NUM = re.compile(r"^-?\d+(\.\d+)?$")
BANK_REF = re.compile(r'"/?(sound/[^"#]+\.bank)#([^"]+)"')


def canon(v: str) -> str:
    v = re.sub(r"\s+", "", v).strip('"')
    return str(float(v)) if NUM.match(v) else v


def values(f: SiiFile, unit: str, key: str) -> list[str]:
    return [v for _, k, v in f.units[unit].attrs if k == key]


def paths() -> tuple[pathlib.Path, pathlib.Path, pathlib.Path]:
    ref_root = pathlib.Path(host_section("Extracted Reference Root")["root"])
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    base = ref_root / "base" / str(mp["base_game"]["version"])
    lver = next(str(r["version"]) for r in mp["references"] if r["workshop"] == LENGTHS_ID)
    cver = next(str(s["version"]) for s in src["sources"] if s.get("workshop") == CIP_ID)
    # Train Lengths keeps its content under base/ inside the package (the game mounts that folder).
    lengths = ref_root / "workshop" / str(LENGTHS_ID) / lver / "base"
    cip = ref_root / "workshop" / str(CIP_ID) / cver
    for p in (base, lengths, cip):
        if not p.is_dir():
            sys.exit(f"missing extraction {p} — run extract-reference first")
    return base, lengths, cip


def base_catalog(base: pathlib.Path) -> set[str]:
    """Names a trailer_chains token may use: traffic_trailer units and traffic_trailer_type short names."""
    names = set()
    for p in (base / "def" / "vehicle").rglob("*"):
        if p.suffix not in SII_SUFFIXES:
            continue
        text = p.read_text(encoding="utf-8", errors="replace")
        names.update(re.findall(r"^\s*traffic_trailer\s*:\s*([\w.]+)", text, re.M))
        names.update(re.findall(r"^\s*traffic_trailer_type\s*:\s*traffic\.trailer_type\.([\w.]+)", text, re.M))
    return names


def bank_events(cip: pathlib.Path) -> dict[str, set[str]]:
    """{bank path: {event path}} from Cip's .bank.guids files."""
    out = {}
    for g in cip.rglob("*.bank.guids"):
        bank = g.relative_to(cip).as_posix()[: -len(".guids")]
        out[bank] = set(re.findall(r"event:/(\S+)", g.read_text(encoding="utf-8", errors="replace")))
    return out


def harvest(tag: str, base: pathlib.Path, mod: pathlib.Path, edits: dict, skipped: list[str]) -> None:
    for p in sorted(p for p in (mod / "def").rglob("*") if p.suffix in SII_SUFFIXES):
        rel = p.relative_to(mod).as_posix()
        target, unit_map = RETARGET.get(rel, (rel, None))
        if not (base / target).is_file():
            skipped.append(f"{tag}: {rel}: not in base game")
            continue
        b, m = SiiFile.read(base / target), SiiFile.read(p)
        for unit in m.order:
            bunit = unit_map.get(unit) if unit_map is not None else unit
            if bunit is None or bunit not in b.units:
                skipped.append(f"{tag}: {rel}: unit {unit} not in base game")
                continue
            keys = {k for _, k, _ in m.units[unit].attrs} | {k for _, k, _ in b.units[bunit].attrs}
            for key in sorted(keys):
                mv, bv = values(m, unit, key), values(b, bunit, key)
                if [canon(v) for v in mv] == [canon(v) for v in bv]:
                    continue
                if key not in CARRY[tag] or not mv:
                    skipped.append(f"{tag}: {rel}: {unit} {key}: {bv} -> {mv}")
                    continue
                if not key.endswith("[]") and len(mv) > 1:
                    # a repeated scalar: the game keeps the last line, so that is what the mod really set
                    skipped.append(f"{tag}: {rel}: {unit} {key}: {len(mv)} lines, last kept: {mv[-1]}")
                    mv = mv[-1:]
                ops = edits.setdefault(target, {}).setdefault(bunit, {}).setdefault("set", {})
                ops[key] = mv if key.endswith("[]") else mv[0]


def validate(edits: dict, catalog: set[str], events: dict[str, set[str]]) -> list[str]:
    errors = []
    for rel, units in edits.items():
        for unit, ops in units.items():
            for key, v in ops["set"].items():
                for val in (v if isinstance(v, list) else [v]):
                    # "" is a valid chain: no trailers (vanilla tractors; a locomotive running light)
                    if key == "trailer_chains[]" and val.strip('"'):
                        for part in val.strip('"').split("|"):
                            token = (part.split() or [""])[0]
                            if token not in catalog:
                                errors.append(f"{rel}: {unit}: chain token {token!r} is not a base-game trailer")
                    for bank, event in BANK_REF.findall(val):
                        if bank not in events:
                            errors.append(f"{rel}: {unit}: {bank} is not shipped by Cip")
                        elif event not in events[bank]:
                            errors.append(f"{rel}: {unit}: event {event!r} not in {bank}")
    return errors


def render(edits: dict) -> str:
    head = (
        "# GENERATED by tools/harvest_edits.py — do not edit by hand; change the script and rerun it.\n"
        "# Edits of base-game files (megapack base_edits), applied at build to the base game in megapack.yaml.\n"
        "# Train lengths/physics from Realistic Train Lengths 3209674677; sounds, speeds and crossing sounds\n"
        "# from Real Train Sounds 2439106226 (Cip). See docs/adr/ADR-0001-world-megapack.md.\n")
    body = yaml.safe_dump({k: edits[k] for k in sorted(edits)}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    base, lengths, cip = paths()
    edits: dict = {}
    skipped: list[str] = []
    harvest("lengths", base, lengths, edits, skipped)
    harvest("cip", base, cip, edits, skipped)
    errors = validate(edits, base_catalog(base), bank_events(cip))
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
    print(f"wrote {OUT.relative_to(ROOT)}: {len(edits)} files, {n} units, {len(skipped)} skipped diffs")
    return 0


if __name__ == "__main__":
    sys.exit(main())

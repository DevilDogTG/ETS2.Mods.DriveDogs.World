#!/usr/bin/env python3
"""
Generates world/brands.yaml (and world/units/): the game definitions of Real companies & gas stations (MLH82,
4of25; source `real-companies`) as edits of the current base game. The mod ships whole copies of 1.61 files
(company names in def/company/*.sui, trailer paint-job masks in def/vehicle/trailer/*/company_paint_job/*.sii);
a whole copy drops whatever a game update adds, so only the keys it changes are carried. Its assets (textures,
materials, sign and gas-station models) merge as a plain source; sources.yaml excludes its def/.

  def file in 1.61       -> every changed or added key `set` on its unit (arrays set in place); a key the mod
                            drops, or a unit 1.61 lacks, is printed as `skip`. A company `trailer_look` is only
                            carried when that look exists (`plain`, or some trailer has company_paint_job/<look>.sii
                            in the base game or the mod): the mod still names looks older versions had (norr_food,
                            skoda, volvo_dlr...), which would leave those companies' trailers without a livery
  def file not in 1.61   -> def/company/*.sui: dropped (def/company*.sii include the companies by name, so a new
                            one is never loaded); anything else (e.g. a paint job for a trailer look the base
                            game lacks on that trailer) is copied whole to world/units/<path> as a new file

usage: python tools/harvest_brands.py [--check]    (--check: fail if world/brands.yaml or world/units/ would change)
"""
from __future__ import annotations

import argparse
import pathlib
import re
import shutil
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import reference_root, repo_game  # noqa: E402
from siiedit import SiiFile  # noqa: E402

OUT = ROOT / "world" / "brands.yaml"
UNITS = ROOT / "world" / "units"
OWNED = "def/vehicle/"   # this tool's part of world/units/ (tools/bus_stop_people.py writes other paths there)
SOURCE = "real-companies"
INDEXED = re.compile(r"^(\w+)\[(\d*)\]$")


def dirs() -> tuple[pathlib.Path, pathlib.Path]:
    ref = reference_root(repo_game(ROOT))
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    src = next(s for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
               if s["id"] == SOURCE)
    base = ref / "base" / str(mp["base_game"]["version"])
    mod = ref / "workshop" / str(src["workshop"]) / str(src["version"])
    for d in (base, mod):
        if not d.is_dir():
            sys.exit(f"missing extraction {d} — run extract-reference first")
    return base, mod


def keyed(sii: SiiFile, unit: str) -> dict[str, list[str]]:
    """key -> values; `k[i]`/`k[]` entries collected under `k[]`, the count line `k: N` dropped."""
    out: dict[str, list[str]] = {}
    for _, key, val in sii.unit(unit).attrs:
        m = INDEXED.match(key)
        out.setdefault(f"{m.group(1)}[]" if m else key, []).append(val.strip())
    for k in [k for k in out if k.endswith("[]")]:
        out.pop(k[:-2], None)
    return out


def looks(*roots: pathlib.Path) -> set[str]:
    return {"plain"} | {p.stem for r in roots for p in (r / "def/vehicle/trailer").glob("*/company_paint_job/*.sii")}


def harvest(base: pathlib.Path, mod: pathlib.Path) -> tuple[dict, dict[str, pathlib.Path], list[str]]:
    edits: dict = {}
    known = looks(base, mod)
    new_files: dict[str, pathlib.Path] = {}
    report: list[str] = []
    for f in sorted(p for p in (mod / "def").rglob("*") if p.is_file() and p.suffix in (".sii", ".sui")):
        rel = f.relative_to(mod).as_posix()
        b = base / rel
        if not b.is_file():
            if rel.startswith("def/company/"):
                report.append(f"skip  {rel}: no such company in the base game (never included)")
            else:
                new_files[rel] = f
            continue
        bs, ms = SiiFile.read(b), SiiFile.read(f)
        for unit in ms.order:
            if unit not in bs.units:
                report.append(f"skip  {rel}: unit {unit} not in the base file")
                continue
            bk, mk = keyed(bs, unit), keyed(ms, unit)
            ops = {}
            for key, vals in mk.items():
                if bk.get(key) == vals:
                    continue
                if key == "trailer_look" and vals[0] not in known:
                    report.append(f"skip  {rel}: trailer_look {vals[0]} has no paint jobs (kept {bk[key][0]})")
                    continue
                ops[key] = vals if key.endswith("[]") else vals[0]
            for key in bk.keys() - mk.keys():
                report.append(f"skip  {rel}: {unit}.{key} dropped by the mod (kept)")
            if ops:
                edits.setdefault(rel, {})[unit] = {"set": ops}
    return edits, new_files, report


def render(edits: dict) -> str:
    head = ("# GENERATED by tools/harvest_brands.py — do not edit by hand; change the script and rerun it.\n"
            "# Real companies & gas stations (MLH82, 4of25): company names and trailer paint-job masks as edits of the\n"
            "# base game files.\n")
    return head + yaml.safe_dump(edits, sort_keys=True, allow_unicode=True, width=10_000)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    edits, new_files, report = harvest(*dirs())
    for r in report:
        print(r)
    n_units = sum(len(u) for u in edits.values())
    print(f"{len(edits)} files, {n_units} units edited; {len(new_files)} new file(s) to world/units/")
    text = render(edits)
    outside = sorted(r for r in new_files if not r.startswith(OWNED))
    if outside:
        sys.exit(f"new file(s) outside world/units/{OWNED}: {outside} — widen OWNED, checking no other tool writes there")
    owned = UNITS / OWNED
    have = {p.relative_to(UNITS).as_posix(): p for p in owned.rglob("*") if p.is_file()} if owned.is_dir() else {}
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == text and set(have) == set(new_files) and all(
            have[r].read_bytes() == f.read_bytes() for r, f in new_files.items())
        print(f"{OUT.relative_to(ROOT)} + world/units/ {'up to date' if same else 'OUT OF DATE'}")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    for rel in set(have) - set(new_files):
        have[rel].unlink()
    for rel, f in new_files.items():
        dest = UNITS / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(f, dest)
    print(f"wrote {OUT.relative_to(ROOT)} and world/units/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

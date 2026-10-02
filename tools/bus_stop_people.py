#!/usr/bin/env python3
"""
Generates World's take on Workshop 2893480838 (people at bus stops; manifest version 1.00, last updated 2022-11-26)
into overrides/: the current base game's bus-stop models with the mod's locators added. The mod's own models are
never merged. They are 2022 re-exports of 28 base-game models: they put back the old shared road materials and
some old geometry, and they drop 1.61's cutscene locators. Its 6 textures are the base game's images in the old
encoding. So only its locators (people, a parked bus, a lamp) are carried, per part, onto the base model of the
same path. Base geometry, materials (.pmd) and existing locators stay as they are. The mod's definitions (mover
groups and hookups, parked bus, lamp) are carried separately as new units in world/units/.
Decisions: plan world-bus-stop-people.

Outputs: overrides/<path>.pmg for each of the mod's models (git-ignored: regenerate with this tool), and the manifest
world/bus_stop_people.tsv (base and mod sha256, locators added per part, output sha256).

usage: python tools/bus_stop_people.py [--check]
  --check: rebuild the models in memory and fail if the manifest or the overrides on disk are out of date.
After a game update: extract the new base, bump base_game.version, rerun this tool. A model or part the base no
longer has is an error.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section  # noqa: E402
from pmg import Locator, Pmg  # noqa: E402

MOD_ID, MOD_VERSION = "2893480838", "1.00"   # <reference root>/workshop/<id>/<version>/ (extract-reference)
MANIFEST = ROOT / "world" / "bus_stop_people.tsv"
OVERRIDES = ROOT / "overrides"
MODEL_DIRS = ("prefab/", "prefab2/")         # where the mod's models live; stale outputs are looked for here only


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def same(a: Locator, b: Locator) -> bool:
    return a.name == b.name and a.hookup == b.hookup and all(abs(x - y) < 1e-4 for x, y in zip(a.position, b.position))


class Inputs:
    def __init__(self) -> None:
        ref = pathlib.Path(host_section("Extracted Reference Root")["root"])
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = ref / "base" / str(mp["base_game"]["version"])
        self.mod = ref / "workshop" / MOD_ID / MOD_VERSION
        for d, how in [(self.base, "extract-reference base"), (self.mod, f"extract-reference workshop {MOD_ID}")]:
            if not d.is_dir():
                sys.exit(f"missing {d} — {how}")
        # a model a merged source also ships would need its locators carried onto that winner instead
        self.shipped: dict[str, str] = {}
        for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if row and not row[0].startswith("#") and row[0] != "path":
                    self.shipped[row[0].lower()] = s["id"]


def build(i: Inputs) -> tuple[list[list[str]], dict[str, bytes], list[str]]:
    """Manifest rows [path, base sha, mod sha, added], output bytes per path, report lines."""
    rows, outs, report = [], {}, []
    for f in sorted(i.mod.rglob("*.pmg")):
        rel = f.relative_to(i.mod).as_posix()
        if rel.lower() in i.shipped:
            sys.exit(f"{rel} is shipped by source {i.shipped[rel.lower()]} — carry the locators onto that winner first")
        base_file = i.base / rel
        if not base_file.is_file():
            sys.exit(f"{rel}: the base game ({i.base.name}) has no such model any more")
        mod_data, base_data = f.read_bytes(), base_file.read_bytes()
        mod, base = Pmg(mod_data, rel), Pmg(base_data, f"base {rel}")
        have = base.part_locators()
        added: dict[str, list[Locator]] = {}
        for part, locs in mod.part_locators().items():
            new = [l for l in locs if not any(same(l, b) for b in have.get(part, []))]
            if len(new) < len(locs):
                report.append(f"keep  {rel} {part}: {len(locs) - len(new)} locator(s) already in the base")
            if new:
                added[part] = new
        outs[rel] = base.with_locators(added)   # raises if the base lacks a part
        rows.append([rel, sha(base_data), sha(mod_data), ";".join(f"{p}:{len(l)}" for p, l in sorted(added.items()))])
    return rows, outs, report


def read_manifest() -> tuple[list[list[str]], dict[str, str]]:
    rows, outs = [], {}
    if MANIFEST.is_file():
        for row in csv.reader(MANIFEST.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "path":
                rows.append(row[:4])
                outs[row[0]] = row[4]
    return rows, outs


def write_manifest(rows: list[list[str]], outs: dict[str, bytes]) -> None:
    lines = ["# GENERATED by tools/bus_stop_people.py — do not edit by hand.",
             "path\tbase_sha256\tmod_sha256\tlocators_added\toutput_sha256"]
    lines += ["\t".join(r + [sha(outs[r[0]])]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def stale(outs: dict[str, bytes]) -> list[pathlib.Path]:
    """Model overrides this tool wrote before but no longer produces."""
    found = []
    for top in MODEL_DIRS:
        for f in (OVERRIDES / top).rglob("*.pmg"):
            if f.relative_to(OVERRIDES).as_posix() not in outs:
                found.append(f)
    return found


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    i = Inputs()
    rows, outs, report = build(i)
    for r in report:
        print(r)
    total = sum(int(n) for r in rows for n in (x.split(":")[1] for x in r[3].split(";") if x))
    print(f"{len(rows)} models, {total} locators added")

    if args.check:
        old_rows, old_outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (base game or the mod)")
        for rel, data in outs.items():
            f = OVERRIDES / rel
            if old_outs.get(rel) != sha(data) or not f.is_file() or sha(f.read_bytes()) != sha(data):
                problems.append(f"overrides/{rel} missing or changed")
        problems += [f"overrides/{f.relative_to(OVERRIDES).as_posix()} is not produced by this tool any more"
                     for f in stale(outs)]
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/bus_stop_people.py")
        return 1 if problems else 0

    for rel, data in outs.items():
        dest = OVERRIDES / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    for f in stale(outs):
        f.unlink()
        print(f"removed stale overrides/{f.relative_to(OVERRIDES).as_posix()}")
    write_manifest(rows, outs)
    print(f"wrote {MANIFEST.relative_to(ROOT)}, {len(outs)} models in overrides/")
    return 0


if __name__ == "__main__":
    sys.exit(main())

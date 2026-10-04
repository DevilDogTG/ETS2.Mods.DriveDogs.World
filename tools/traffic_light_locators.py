#!/usr/bin/env python3
"""
Generates into overrides/ the base game's standard traffic-light models with a flashing-green locator added: every
`flare.traffic.green` locator is copied, in the same part and at the same position, rotation and scale, as a
`flare.traffic.green.trans` locator. That is how the base game's own flashing-green models are built (AT, Baltics,
Balkans, GR, ES: the green.trans locator sits exactly on the green one), and the base hookup unit
`flare.traffic.green.trans` (Better Flares: same unit with its glow) blinks in the semaphore's green_trans state.

The models are the ones behind the units in world/traffic_lights.yaml, whose state_transition turns the last seconds
of green into green_trans. Without this locator a standard model has nothing lit in green_trans: the TrafficLights
add-on 1.0.0 borrowed the night sleep blinker (`flare.traffic.yellow.blink.sleep`) for it, which left night sleep mode
a steady yellow (user, 2026-10-04). With it, the sleep blinker goes back to its own job. Decisions: plan
world-night-yellow, ADR-0005.

Outputs: overrides/model/traffic_light/<model>.pmg (git-ignored: regenerate with this tool) and the manifest
world/traffic_light_locators.tsv (base sha256, locators added per part, output sha256).

usage: python tools/traffic_light_locators.py [--check]
  --check: rebuild the models in memory and fail if the manifest or the overrides on disk are out of date.
After a game update: extract the new base, bump base_game.version, regenerate world/traffic_lights.yaml in the
TrafficLights repo, rerun this tool.
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
from siiedit import SiiFile  # noqa: E402

TIMING = ROOT / "world" / "traffic_lights.yaml"
MANIFEST = ROOT / "world" / "traffic_light_locators.tsv"
OVERRIDES = ROOT / "overrides"
MODEL_DIR = "model/traffic_light/"
GREEN, FLASH = "flare.traffic.green", "flare.traffic.green.trans"
PREFIX = "gt_"   # new locator name = PREFIX + the green locator's name (names are tokens: up to 12 of [0-9a-z_])


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Inputs:
    def __init__(self) -> None:
        ref = pathlib.Path(host_section("Extracted Reference Root")["root"])
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = ref / "base" / str(mp["base_game"]["version"])
        if not self.base.is_dir():
            sys.exit(f"missing {self.base} — extract-reference base")
        # a model a merged source also ships would need its locators carried onto that winner instead
        self.shipped: dict[str, str] = {}
        for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if row and not row[0].startswith("#") and row[0] != "path":
                    self.shipped[row[0].lower()] = s["id"]

    def models(self) -> list[str]:
        """The .pmg paths behind the units that get a state_transition in world/traffic_lights.yaml."""
        out: set[str] = set()
        for rel, units in yaml.safe_load(TIMING.read_text(encoding="utf-8")).items():
            sii = SiiFile.read(self.base / rel)
            for unit in units:
                desc = sii.values(unit, "model_desc")[0].strip().strip('"').lstrip("/")
                if not desc.startswith(MODEL_DIR) or not desc.endswith(".pmd"):
                    sys.exit(f"{rel} {unit}: model {desc} is not a {MODEL_DIR}*.pmd")
                out.add(desc[:-4] + ".pmg")
        return sorted(out)


def build(i: Inputs) -> tuple[list[list[str]], dict[str, bytes]]:
    """Manifest rows [path, base sha, added], output bytes per path."""
    rows, outs = [], {}
    for rel in i.models():
        if rel.lower() in i.shipped:
            sys.exit(f"{rel} is shipped by source {i.shipped[rel.lower()]} — carry the locators onto that winner first")
        base_file = i.base / rel
        if not base_file.is_file():
            sys.exit(f"{rel}: the base game ({i.base.name}) has no such model")
        data = base_file.read_bytes()
        model = Pmg(data, f"base {rel}")
        added: dict[str, list[Locator]] = {}
        for part, locs in model.part_locators().items():
            if any(l.hookup == FLASH for l in locs):
                sys.exit(f"{rel} {part}: already has {FLASH} — the base flashes natively; drop it from the timing")
            new = [Locator(PREFIX + l.name, l.position, FLASH, l.scale, l.rotation) for l in locs if l.hookup == GREEN]
            if new:
                added[part] = new
        if not added:
            sys.exit(f"{rel}: no {GREEN} locator")
        outs[rel] = model.with_locators(added)
        rows.append([rel, sha(data), ";".join(f"{p}:{len(l)}" for p, l in sorted(added.items()))])
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
    lines = ["# GENERATED by tools/traffic_light_locators.py — do not edit by hand.",
             "path\tbase_sha256\tlocators_added\toutput_sha256"]
    lines += ["\t".join(r + [sha(outs[r[0]])]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def stale(outs: dict[str, bytes]) -> list[pathlib.Path]:
    return [f for f in (OVERRIDES / MODEL_DIR).rglob("*.pmg") if f.relative_to(OVERRIDES).as_posix() not in outs]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    rows, outs = build(Inputs())
    total = sum(int(n) for r in rows for n in (x.split(":")[1] for x in r[2].split(";")))
    print(f"{len(rows)} models, {total} {FLASH} locators added")

    if args.check:
        old_rows, old_outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (base game or world/traffic_lights.yaml)")
        for rel, data in outs.items():
            f = OVERRIDES / rel
            if old_outs.get(rel) != sha(data) or not f.is_file() or sha(f.read_bytes()) != sha(data):
                problems.append(f"{f.relative_to(ROOT).as_posix()} missing or changed")
        problems += [f"{f.relative_to(ROOT).as_posix()} is not produced by this tool any more" for f in stale(outs)]
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/traffic_light_locators.py")
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

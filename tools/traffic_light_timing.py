#!/usr/bin/env python3
"""
Generates world/traffic_lights.yaml: flashing-green timing on the base game's standard traffic lights, as edits of
the current base game (megapack `base_edits`).

Flashing green uses the engine's own `green_trans` state: state_transition[3] turns the last FLASH_SECONDS of every
green into green_trans, whatever the profile's green length. A semaphore model gets it only when its .pmg carries
exactly the four standard flare locators (green, red, yellow, yellow.blink.sleep) and its unit has no
state_transition yet; any other green flare on it (arrows, trams, white signals) would go dark during green_trans.
tools/traffic_light_locators.py then adds a `flare.traffic.green.trans` locator on every green lens of these
models, like the base game's native flashing-green models, and the base hookup unit of that name (Better Flares:
same unit with its glow) blinks there.

The timing has to live in World: semaphore models are found by unit id (tr_sem_mdl.<model>[.<country>]), so it can
only be set in the semaphore_model*.sii files World already edits. Ported from the deprecated TrafficLights add-on's
`generate_traffic_lights.py --world-edits` (World owns it since 2026-10-29; ADR-0006); the add-on's hookup half
(Better Flares' file, the empty tr_light_flares0.sii) is not needed: World ships no hookup file.

usage: python tools/traffic_light_timing.py [--check]    (--check: fail if world/traffic_lights.yaml would change)
Inputs: the extracted base game of this host (profile host file) at the version in megapack.yaml.
After a game update: extract the new base, bump base_game.version, rerun this tool, then traffic_light_locators.py.
"""
from __future__ import annotations

import argparse
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import reference_root, ref_fetch, ref_path, repo_game  # noqa: E402

OUT = ROOT / "world" / "traffic_lights.yaml"
FLASH_SECONDS = 3.0          # green_trans length at the end of green
HOOKUP = "unit/hookup/tr_light_flares.sii"
SEMAPHORE_DIR = "def/world"
SEMAPHORE_SOURCES = (
    "semaphore_model.sii",
    "semaphore_model.mod_polar_circle.sii",
    "semaphore_model.mod_benelux_reskin.sii",
    "semaphore_model.dlc_iberia.sii",
    "semaphore_model.dlc_balkan_w.sii",
)
STANDARD_LOCATORS = frozenset({
    "flare.traffic.green", "flare.traffic.red",
    "flare.traffic.yellow", "flare.traffic.yellow.blink.sleep",
})
FLASH_UNIT = "flare.traffic.green.trans"   # what traffic_light_locators.py's added locators hook up to

FLARE_RE = re.compile(r"^flare_traffic_light\s*:\s*([\w.]+)[ \t]*\r?\n\{.*?^\}", re.M | re.S)
SEM_UNIT_RE = re.compile(r"^tr_semaphore_model\s*:\s*([\w.]+)[ \t]*\r?\n\{.*?^\}", re.M | re.S)
ATTR_RE = re.compile(r"^(\s*)(\w+(?:\[\d*\])?)(\s*:\s*)([^#\r\n]*?)(\s*(?:#[^\r\n]*)?)(\r?\n)?$")
HOOKUP_NAME_RE = re.compile(rb"flare\.traffic[\w.]*")


def base_dir() -> pathlib.Path:
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    base = reference_root(repo_game(ROOT)) / "base" / str(mp["base_game"]["version"])
    if not base.is_dir():
        sys.exit(f"missing extraction {base} — run extract-reference first")
    return base


def read(path: pathlib.Path) -> str:
    with open(path, encoding="utf-8", newline="") as f:
        return f.read()


def units(text: str, regex: re.Pattern) -> dict[str, re.Match]:
    found: dict[str, re.Match] = {}
    for m in regex.finditer(text):
        if m.group(1) in found:
            sys.exit(f"duplicate unit {m.group(1)}")
        found[m.group(1)] = m
    return found


def attr(block: str, key: str) -> str | None:
    for line in block.splitlines():
        m = ATTR_RE.match(line)
        if m and m.group(2) == key:
            return m.group(4)
    return None


def num(value: float) -> str:
    return f"{value:.1f}" if float(value).is_integer() else f"{value:g}"


def check_flash_unit(base: pathlib.Path) -> None:
    """The base hookup unit the added locators use must still blink in green_trans."""
    flares = units(read(base / HOOKUP), FLARE_RE)
    if FLASH_UNIT not in flares or attr(flares[FLASH_UNIT].group(0), "semaphore_states[]") != "green_trans":
        sys.exit(f"base {HOOKUP}: {FLASH_UNIT} no longer blinks in green_trans; re-check the game update")


def locators(base: pathlib.Path, model_desc: str) -> frozenset[str] | None:
    pmg = ref_path(base, model_desc.lstrip("/")[:-4] + ".pmg")
    if not pmg.exists():
        return None
    return frozenset(x.decode() for x in HOOKUP_NAME_RE.findall(pmg.read_bytes()))


def flash_targets(base: pathlib.Path) -> tuple[dict[str, list[str]], list[str]]:
    """Semaphore models that get state_transition: exactly the standard locators, no transition yet."""
    targets: dict[str, list[str]] = {}
    report = []
    for src in SEMAPHORE_SOURCES:
        path = base / SEMAPHORE_DIR / src
        if not path.exists():
            sys.exit(f"missing {path}")
        picked, skipped = [], 0
        sems = units(read(path), SEM_UNIT_RE)
        descs = {attr(m.group(0), "model_desc") for m in sems.values()} - {None}
        ref_fetch(base, [d.strip('"').lstrip("/")[:-4] + ".pmg" for d in descs])   # one fetch per archive
        for unit_id, m in sems.items():
            block = m.group(0)
            desc = attr(block, "model_desc")
            if desc and "state_transition" not in block \
                    and locators(base, desc.strip('"')) == STANDARD_LOCATORS:
                picked.append(unit_id)
            else:
                skipped += 1
        targets[f"{SEMAPHORE_DIR}/{src}"] = picked
        report.append(f"  {src}: {len(picked)} flash targets, {skipped} left alone")
    return targets, report


def render(targets: dict[str, list[str]]) -> str:
    values = ", ".join(num(v) for v in (0.0, 0.0, 0.0, FLASH_SECONDS))
    lines = [
        "# GENERATED by tools/traffic_light_timing.py — do not edit by hand; change the script and rerun it.",
        "# Flashing green: the last FLASH_SECONDS of green become green_trans (state_transition[3]) on semaphore",
        "# models with only the standard four flare locators. World's tools/traffic_light_locators.py adds a",
        "# flare.traffic.green.trans locator on their green lenses; without it these lights go dark instead.",
        "# state_transition[]: orange_to_red, red, orange_to_green, green",
    ]
    for path, ids in targets.items():
        if ids:
            lines.append(f"{path}:")
            for unit_id in ids:
                lines += [f"  {unit_id}:", "    set:", f"      state_transition[]: [{values}]"]
    return "\n".join(lines) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    base = base_dir()
    check_flash_unit(base)
    targets, report = flash_targets(base)
    text = render(targets)
    n = sum(len(ids) for ids in targets.values())
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print(f"{OUT.relative_to(ROOT)} {'up to date' if same else 'OUT OF DATE'} ({n} units)")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}: {n} units", *report, sep="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())

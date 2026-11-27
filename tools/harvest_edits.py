#!/usr/bin/env python3
"""
Generates world/edits.yaml: the train and level-crossing edits World applies to the current base game
(megapack `base_edits`), harvested per unit from two Workshop mods that ship whole-file copies:

  Realistic Train Lengths 3209674677  trailer_chains[], lod_dist[] and the train physics values it
                                      carries (max_speed, engine_power, vehicle_mass, cargo_mass; these come
                                      from Sound Fixes Pack 26.66, which it was built on)
  Real Train Sounds (Cip) 2439106226  per-train sound_move/sound_horn, max_speed, crossing sounds[]
  Sound Fixes Pack 648591060          only the picks in SFP_PICKS (garage-door sounds, train headlights) and the
                                      units in SFP_NEW_UNITS (Class 252 locomotives for Spain and Portugal).
                                      World ships none of SFP's files, so picked sounds play from SFP itself,
                                      which must load below World (ADR-0001 decision 6)

Only attributes listed in CARRY are taken, and only on units that exist in the base game, so units the base
game added since a mod was made (e.g. 1.61's traffic.frt.nl) keep their vanilla values instead of being
dropped. Lengths' sound lines and @includes (Sound Fixes Pack's) are not carried. Cip's edits are applied
after Lengths', so on a unit both change, Cip's max_speed wins. SFP's picks are applied last.

Every carried value is checked: trailer_chains tokens must name a base-game trailer or trailer type, and every
`bank#event` must be an event of a bank Cip ships, and every sound a pick sets must resolve (soundref -> bank ->
event) in SFP or the base game. Units added from SFP must be new to their file, reference only units of their own
group (each once) or base-game files, use base-game chain tokens and resolving sounds. Any failure aborts without
writing.

usage: python tools/harvest_edits.py [--check]    (--check: fail if world/edits.yaml would change)
Inputs are read from the extracted-reference root of this host (profile host file), at the versions in
megapack.yaml (base_game, references: Lengths, SFP) and sources.yaml (Cip).
"""
from __future__ import annotations

import argparse
import fnmatch
import pathlib
import re
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import base_dir as base_ref_dir, reference_root, repo_game  # noqa: E402
from siiedit import SiiFile  # noqa: E402

OUT = ROOT / "world" / "edits.yaml"
LENGTHS_ID, CIP_ID, SFP_ID = 3209674677, 2439106226, 648591060

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
# Sound Fixes Pack lines World takes: (file, unit pattern, keys). SFP's values (its @includes inlined) replace the
# base game's on every matching base-game unit; a key SFP drops is unset. A file glob applies only to the files World
# already ships (never adds one: World would then hide SFP's other changes in it). A pick that matches no base-game
# unit is an error.
SFP_PICKS = [
    # garage doors: SFP's door sound instead of the game's iron gate
    ("def/world/semaphore_model.sii", r"tr_sem_mdl\.(garage_sc|g_exp_door|g_mid_door|g_poor_door)", ["sounds[]"]),
    # locomotive headlights: SFP's warm halogen colour and wide beam (the game sets none on trains)
    ("def/vehicle/ai/*", r"traffic\..+", ["headlights_angle", "headlights_diffuse"]),
]
# Sound Fixes Pack units World adds to a base-game file: (file, anchor unit, SFP unit pattern, {vehicle: twin}).
# SFP's matching units (its @includes inlined) are inserted after the anchor's closing brace, in SFP's order, with
# SFP's values except the TWIN_KEYS, which come from the twin vehicle as World ships it (base game + the edits
# above), so the added trains sound and draw like the same locomotive World already has.
SFP_NEW_UNITS = [
    # Class 252 locomotives that spawn on their own in Spain / Portugal, on top of the country lists' Class 252
    ("def/vehicle/ai/train_class334_locomotive.sui", ".cls334_loco.sp.rwheel", r"\.?(traffic\.)?cls252_loco\.sp\.mod(\..+)?",
     {"traffic.cls252_loco.sp.mod": ("def/vehicle/ai/train_cls252_locomotive.sui", "traffic.cls252_loco.sp")}),
    ("def/vehicle/ai/train_class334_locomotive.sui", ".cls334_loco.pt.rwheel", r"\.?(traffic\.)?cls252_loco\.pt\.mod(\..+)?",
     {"traffic.cls252_loco.pt.mod": ("def/vehicle/ai/train_cls252_locomotive.sui", "traffic.cls252_loco.pt")}),
]
TWIN_KEYS = re.compile(r"sound.*|lod_dist\[\]")
REFS = ("accessories[]", "spawn_condition[]")  # keys naming other units
SII_SUFFIXES = {".sii", ".sui"}
NUM = re.compile(r"^-?\d+(\.\d+)?$")
BANK_REF = re.compile(r'"/?(sound/[^"#]+\.bank)#([^"]+)"')
INCLUDE = re.compile(r'^\s*@include\s+"([^"]+)"', re.M)
SOUND_PATH = re.compile(r'/[\w./\-]+?\.(?:soundref|bank)(?:#[^"|\s]+)?')
SOURCE = re.compile(r'source\s*=\s*"([^"]+)"')


def canon(v: str) -> str:
    v = re.sub(r"\s+", "", v).strip('"')
    return str(float(v)) if NUM.match(v) else v


def values(f: SiiFile, unit: str, key: str) -> list[str]:
    return [v for _, k, v in f.units[unit].attrs if k == key]


def paths() -> tuple[pathlib.Path, pathlib.Path, pathlib.Path, pathlib.Path]:
    ref_root = reference_root(repo_game(ROOT))
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))
    base = base_ref_dir(ref_root, mp["base_game"]["version"])
    lver = next(str(r["version"]) for r in mp["references"] if r["workshop"] == LENGTHS_ID)
    sver = next(str(r["version"]) for r in mp["references"] if r["workshop"] == SFP_ID)
    cver = next(str(s["version"]) for s in src["sources"] if s.get("workshop") == CIP_ID)
    # Train Lengths keeps its content under base/ inside the package (the game mounts that folder).
    lengths = ref_root / "workshop" / str(LENGTHS_ID) / lver / "base"
    cip = ref_root / "workshop" / str(CIP_ID) / cver
    sfp = ref_root / "workshop" / str(SFP_ID) / sver
    for p in (base, lengths, cip, sfp):
        if not p.is_dir():
            sys.exit(f"missing extraction {p} — run extract-reference first")
    return base, lengths, cip, sfp


def other_edits() -> dict[str, set[str]]:
    """{file: {unit}} edited by the other base_edits files in megapack.yaml (a unit is edited in one file only)."""
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    out: dict[str, set[str]] = {}
    for rel in mp["base_edits"]["edits"]:
        if (ROOT / rel).resolve() == OUT.resolve():
            continue
        for f, units in (yaml.safe_load((ROOT / rel).read_text(encoding="utf-8")) or {}).items():
            out.setdefault(f, set()).update(units or {})
    return out


def inline(root: pathlib.Path, path: pathlib.Path, errors: list[str]) -> str:
    """The file's text with each @include line replaced by the included file (relative to the including file,
    or to the mod root when it starts with "/"), recursively."""
    def rep(m: re.Match) -> str:
        ref = m.group(1)
        p = root / ref.lstrip("/") if ref.startswith("/") else path.parent / ref
        if not p.is_file():
            errors.append(f"{path.relative_to(root).as_posix()}: @include {ref!r} not found")
            return ""
        return inline(root, p, errors)
    return INCLUDE.sub(rep, path.read_text(encoding="utf-8", errors="replace"))


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


def harvest_sfp(base: pathlib.Path, sfp: pathlib.Path, edits: dict, shipped: dict[str, set[str]],
                skipped: list[str], errors: list[str]) -> None:
    """SFP_PICKS onto the base game's units, after Lengths' and Cip's edits."""
    seen: dict[str, str | None] = {}
    for pick, pattern, keys in SFP_PICKS:
        glob = any(c in pick for c in "*?[")
        files = sorted(f for f in set(edits) | set(shipped) if fnmatch.fnmatchcase(f, pick)) if glob else [pick]
        matched = 0
        for rel in files:
            if not (sfp / rel).is_file() or not (base / rel).is_file():
                if not glob:
                    errors.append(f"sfp: {rel}: not in "
                                  f"{'Sound Fixes Pack' if (base / rel).is_file() else 'the base game'}")
                continue
            b, m = SiiFile.read(base / rel), SiiFile(inline(sfp, sfp / rel, errors))
            for unit in (u for u in m.order if re.fullmatch(pattern, u)):
                if unit not in b.units:
                    skipped.append(f"sfp: {rel}: unit {unit} not in base game")
                    continue
                matched += 1
                harvest_sfp_unit(rel, unit, keys, b, m, sfp, base, edits, shipped, skipped, errors, seen)
        if not matched:
            errors.append(f"sfp: {pick}: pick {pattern!r} matches no base-game unit")


def harvest_sfp_unit(rel: str, unit: str, keys: list[str], b: SiiFile, m: SiiFile, sfp: pathlib.Path,
                     base: pathlib.Path, edits: dict, shipped: dict[str, set[str]], skipped: list[str],
                     errors: list[str], seen: dict[str, str | None]) -> None:
    for key in keys:
        mv, bv = values(m, unit, key), values(b, unit, key)
        if not mv and not bv:
            continue
        if [canon(v) for v in mv] == [canon(v) for v in bv]:
            skipped.append(f"sfp: {rel}: {unit} {key}: same as the base game")
            continue
        if unit in shipped.get(rel, ()):
            errors.append(f"sfp: {rel}: {unit} is edited by another base_edits file; carry SFP's {key} there")
            continue
        for v in mv:
            for ref in SOUND_PATH.findall(v):
                if why := check_sound(ref, (sfp, base), seen):
                    errors.append(f"sfp: {rel}: {unit}: {key}: {why}")
        ops = edits.setdefault(rel, {}).setdefault(unit, {})
        if not mv:
            ops.setdefault("unset", []).append(key)
            ops.get("set", {}).pop(key, None)
            continue
        if not key.endswith("[]") and len(mv) > 1:
            skipped.append(f"sfp: {rel}: {unit} {key}: {len(mv)} lines, last kept: {mv[-1]}")
            mv = mv[-1:]
        ops.setdefault("set", {})[key] = mv if key.endswith("[]") else mv[0]


def shipped_values(base: pathlib.Path, edits: dict, rel: str, unit: str) -> list[tuple[str, str]]:
    """(key, value) lines of a base-game unit as World ships it: the base game's, with the `set` edits so far."""
    b = SiiFile.read(base / rel)
    ops = edits.get(rel, {}).get(unit, {})
    out, done = [], set()
    for _, key, v in b.units[unit].attrs:
        if key in ops.get("unset", []):
            continue
        if key in ops.get("set", {}):
            if key not in done:
                new = ops["set"][key]
                out += [(key, x) for x in (new if isinstance(new, list) else [new])]
                done.add(key)
            continue
        out.append((key, v))
    for key, new in ops.get("set", {}).items():
        if key not in done:
            out += [(key, x) for x in (new if isinstance(new, list) else [new])]
    return out


def harvest_sfp_new_units(base: pathlib.Path, sfp: pathlib.Path, cip: pathlib.Path, edits: dict,
                          shipped: dict[str, set[str]], catalog: set[str], errors: list[str]) -> None:
    """SFP_NEW_UNITS as `after:` lines on their anchor units (TWIN_KEYS from the twin as World ships it)."""
    seen: dict[str, str | None] = {}
    for rel, anchor, pattern, twins in SFP_NEW_UNITS:
        where = f"sfp new units: {rel}"
        b, m = SiiFile.read(base / rel), SiiFile(inline(sfp, sfp / rel, errors))
        if anchor not in b.units or anchor in shipped.get(rel, ()):
            errors.append(f"{where}: anchor {anchor} " + ("not in base game" if anchor not in b.units
                                                          else "is edited by another base_edits file"))
            continue
        group = [u for u in m.order if re.fullmatch(pattern, u)]
        if not group or not set(twins) <= set(group):
            errors.append(f"{where}: {pattern!r} matches {group}, missing {sorted(set(twins) - set(group))}")
            continue
        lines: list[str] = []
        refs: list[str] = []
        for name in group:
            u = m.units[name]
            if name in b.units:
                errors.append(f"{where}: {name} is already a base-game unit")
            attrs = [(k, v) for _, k, v in u.attrs]
            if name in twins:
                trel, tunit = twins[name]
                theirs = [(k, v) for k, v in shipped_values(base, edits, trel, tunit) if TWIN_KEYS.fullmatch(k)]
                at = next((i for i, (k, _) in enumerate(attrs) if TWIN_KEYS.fullmatch(k)), len(attrs))
                attrs = [a for a in attrs[:at] if not TWIN_KEYS.fullmatch(a[0])] + theirs + \
                        [a for a in attrs[at:] if not TWIN_KEYS.fullmatch(a[0])]
            for k, v in attrs:
                if k in REFS:
                    refs.append(v.strip().strip('"'))
                elif k == "data_path" and not (base / v.strip().strip('"').lstrip("/")).is_file():
                    errors.append(f"{where}: {name}: data_path {v} not in base game")
                elif k == "trailer_chains[]" and v.strip().strip('"'):
                    for part in v.strip().strip('"').split("|"):
                        token = (part.split() or [""])[0]
                        if token not in catalog:
                            errors.append(f"{where}: {name}: chain token {token!r} is not a base-game trailer")
                elif k.startswith("sound"):
                    for ref in SOUND_PATH.findall(v):
                        if why := check_sound(ref, (cip, base), seen):
                            errors.append(f"{where}: {name}: {k}: {why}")
            lines += ["", f"{u.type} : {name}", "{"] + [f"\t{k}: {v}" for k, v in attrs] + ["}"]
        for ref in sorted(set(refs)):
            if ref not in group or refs.count(ref) != 1:
                errors.append(f"{where}: {ref} must be a unit of the added group, referenced once "
                              f"({refs.count(ref)} references)")
        edits.setdefault(rel, {}).setdefault(anchor, {}).setdefault("after", []).extend(lines)


def guid_events(bank: pathlib.Path) -> set[str] | None:
    guids = bank.with_name(bank.name + ".guids")
    if not guids.is_file():
        return None
    return set(re.findall(r"event:/(\S+)", guids.read_text(encoding="utf-8", errors="replace")))


def check_sound(ref: str, roots: tuple[pathlib.Path, ...], seen: dict[str, str | None]) -> str | None:
    """None when `/path.soundref` or `/path.bank#event` resolves in the first root that has the file, else why not."""
    if ref in seen:
        return seen[ref]
    path, _, event = ref.partition("#")
    if path.endswith(".soundref"):
        hit = next((r / path.lstrip("/") for r in roots if (r / path.lstrip("/")).is_file()), None)
        why = f"{path} not found"
        if hit is not None:
            src = SOURCE.findall(hit.read_text(encoding="utf-8-sig", errors="replace"))
            why = f"{path} has no source" if not src else None
            for s in src:
                why = why or check_sound(s, roots, seen)
    else:
        # banks: the .bank.guids lists the events; the base game's text tier has the .guids without the .bank
        guided = next((r / path.lstrip("/") for r in roots
                       if (r / (path.lstrip("/") + ".guids")).is_file()), None)
        events = guid_events(guided) if guided is not None else None
        why = (f"{path} not found" if events is None
               else f"event {event!r} not in {path}" if event and event not in events else None)
    seen[ref] = why
    return why


def validate(edits: dict, catalog: set[str], events: dict[str, set[str]]) -> list[str]:
    errors = []
    for rel, units in edits.items():
        for unit, ops in units.items():
            for key, v in ops.get("set", {}).items():
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
        "# from Real Train Sounds 2439106226 (Cip); from Sound Fixes Pack 648591060 the garage-door sounds (played\n"
        "# from SFP itself, loaded below World), locomotive headlights and Class 252 locomotives for Spain and\n"
        "# Portugal. See docs/adr/ADR-0001-world-megapack.md.\n")
    body = yaml.safe_dump({k: edits[k] for k in sorted(edits)}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    base, lengths, cip, sfp = paths()
    edits: dict = {}
    skipped: list[str] = []
    errors: list[str] = []
    harvest("lengths", base, lengths, edits, skipped)
    harvest("cip", base, cip, edits, skipped)
    shipped, catalog = other_edits(), base_catalog(base)
    harvest_sfp(base, sfp, edits, shipped, skipped, errors)
    harvest_sfp_new_units(base, sfp, cip, edits, shipped, catalog, errors)
    errors += validate(edits, catalog, bank_events(cip))
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

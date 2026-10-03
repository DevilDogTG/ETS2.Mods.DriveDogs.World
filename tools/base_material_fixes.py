#!/usr/bin/env python3
"""
Generates overrides/ copies of base-game materials whose texture paths point at files the game no longer has,
with the path corrected. Only materials that show up in a test game.log are listed (a scan of the 92,614 base
materials of 1.61.1.1 finds 153 broken texture references, nearly all on models nothing places).

  /automat/08/088ed9a0256b508b.mat   eut2.glass of the Class 334 loco (AI train and the static Iberia/UK model):
      /vehicle/ai/train/class252/loco_glass_mask.tobj -> /vehicle/ai/train_cls252/loco_glass_mask.tobj
      (Class 334 has no glass mask of its own; 1.61 moved Class 252 to train_cls252/. game.log:
      `Failed to init update for object '/vehicle/ai/train/class252/loco_glass_mask.tobj'`)

Decisions: plan world-flash-timing, sub-plan log-fixes. The output is the base file with only those strings
replaced. Fails when the base material is gone, no longer has the old path (the game fixed or moved it: drop or
adjust the entry), or the new texture is missing. Writes world/base_material_fixes.tsv (base sha256, output
sha256); tools/rain_reflections.py, which owns the rest of overrides/automat/, skips the paths listed there.

usage: python tools/base_material_fixes.py [--check]    (--check: fail if an output or the manifest would change)
Inputs: the extracted base game of this host (profile host file) at the version in megapack.yaml.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import pathlib
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section  # noqa: E402

OVERRIDES = ROOT / "overrides"
MANIFEST = ROOT / "world" / "base_material_fixes.tsv"
RAIN_MANIFEST = ROOT / "world" / "rain_reflections.tsv"   # tools/rain_reflections.py: must not claim the same path

# {material: {old texture path: new texture path}}
FIXES: dict[str, dict[str, str]] = {
    "automat/08/088ed9a0256b508b.mat": {
        "/vehicle/ai/train/class252/loco_glass_mask.tobj": "/vehicle/ai/train_cls252/loco_glass_mask.tobj",
    },
}


def base_dir() -> pathlib.Path:
    mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
    base = pathlib.Path(host_section("Extracted Reference Root")["root"]) / "base" / str(mp["base_game"]["version"])
    if not base.is_dir():
        sys.exit(f"missing extraction {base} — run extract-reference first")
    return base


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def build(base: pathlib.Path) -> tuple[dict[str, bytes], list[list[str]], list[str]]:
    """-> ({path: output bytes}, manifest rows, errors)."""
    rain = RAIN_MANIFEST.read_text(encoding="utf-8") if RAIN_MANIFEST.is_file() else ""
    outs, rows, errors = {}, [], []
    for rel, swaps in sorted(FIXES.items()):
        src = base / rel
        if not src.is_file():
            errors.append(f"{rel}: not in the base game any more")
            continue
        if f"\n{rel}\t" in f"\n{rain}":
            errors.append(f"{rel}: also produced by tools/rain_reflections.py; one tool per file")
            continue
        data = src.read_bytes()
        text = data.decode("utf-8")
        for old, new in swaps.items():
            if f'"{old}"' not in text:
                errors.append(f"{rel}: base no longer references {old} (fixed or moved by the game?)")
            if not (base / new.lstrip("/")).is_file():
                errors.append(f"{rel}: replacement {new} is not in the base game")
            text = text.replace(f'"{old}"', f'"{new}"')
        out = text.encode("utf-8")
        outs[rel] = out
        rows.append([rel, sha(data), sha(out)])
    return outs, rows, errors


def manifest_text(rows: list[list[str]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, delimiter="\t", lineterminator="\n")
    w.writerow(["path", "base_sha256", "output_sha256"])
    w.writerows(rows)
    return buf.getvalue()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    outs, rows, errors = build(base_dir())
    for e in errors:
        print(f"ERROR {e}")
    if errors:
        return 1
    manifest = manifest_text(rows)
    if args.check:
        stale = [rel for rel, out in outs.items()
                 if not (OVERRIDES / rel).is_file() or (OVERRIDES / rel).read_bytes() != out]
        if not MANIFEST.is_file() or MANIFEST.read_text(encoding="utf-8") != manifest:
            stale.append(str(MANIFEST.relative_to(ROOT)))
        for s in stale:
            print(f"OUT OF DATE  {s}")
        print("up to date" if not stale else f"{len(stale)} problem(s) — rerun tools/base_material_fixes.py")
        return 1 if stale else 0
    for rel, out in outs.items():
        (OVERRIDES / rel).parent.mkdir(parents=True, exist_ok=True)
        (OVERRIDES / rel).write_bytes(out)
    MANIFEST.write_text(manifest, encoding="utf-8", newline="\n")
    print(f"wrote {len(outs)} material(s) to overrides/ and {MANIFEST.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""
Checks that every model World ships pairs a description (.pmd) with geometry (.pmg) the game can draw.

The game loads `<model>.pmd` and `<model>.pmg` from whichever archive wins each path, so a source that ships one
without the other pairs it with the base game's copy. When the base game changes that model, the pair no longer
fits, and the game crashes on load:
- a piece names a material the .pmd does not have: `Index outside array boundaries` on `material_u`. DBM Vegetation
  1.8 shipped its 1.61 `city_flower_curve2_blke_lod1.pmd` (1 material) over 1.62's .pmg (4), World 1.5.0-dev.6,
  quick travel to Larissa.
- the part counts differ: `Mismatch between number of parts in geometry (.pmg) and description (.pmd)`.
`megapack check` cannot see this: both paths are valid, only their contents disagree.

Every .pmd/.pmg path a source or overrides/ ships is paired with its counterpart as the build resolves it
(overrides/, else the lock's winner, else the base game). Pairs whose both files are the base game's are skipped.
Winners are read from the lock, so rerun `megapack lock` first.

usage: python tools/check_model_pairs.py
Read-only: writes nothing. Exits 1 and lists each bad pair. Run before every build and after a game or source
update (see README).
"""
from __future__ import annotations

import struct
import sys

from check_sign_defs import OVERRIDES, Tree

from megapack import ref_exists, ref_fetch  # noqa: E402  (check_sign_defs puts the megapack skill on sys.path)
from pmg import Pmg, PmgError  # noqa: E402

SUFFIXES = (".pmd", ".pmg")


def stems(tree: Tree) -> dict[str, str]:
    """-> {lower-case path without suffix: that path as shipped} for every .pmd/.pmg a source or overrides/ ships."""
    out: dict[str, str] = {}
    for _, locked in tree.owner.values():
        if locked.lower().endswith(SUFFIXES):
            out.setdefault(locked[:-4].lower(), locked[:-4])
    for p in OVERRIDES.rglob("*"):
        if p.suffix.lower() in SUFFIXES:
            rel = p.relative_to(OVERRIDES).as_posix()
            out.setdefault(rel[:-4].lower(), rel[:-4])
    return out


def check(tree: Tree, stem: str) -> str | None:
    (pmd_owner, pmd), (pmg_owner, pmg) = tree.find(stem + ".pmd"), tree.find(stem + ".pmg")
    if pmd_owner == "base" and pmg_owner == "base":
        return None
    if pmd is None or pmg is None:
        return f"{stem}: .pmd {pmd_owner if pmd else 'missing'}, .pmg {pmg_owner if pmg else 'missing'}"
    data = pmd.read_bytes()
    materials, parts = struct.unpack_from("<I", data, 4)[0], struct.unpack_from("<I", data, 20)[0]
    try:
        geometry = Pmg(pmg.read_bytes(), str(pmg))
    except PmgError as e:
        return f"{stem}: .pmg from {pmg_owner} unreadable: {e}"
    issues = []
    top = max((piece[4] for piece in geometry.pieces), default=-1)
    if top >= materials:
        issues.append(f"a piece uses material {top}, the .pmd has {materials}")
    if parts != geometry.part_count:
        issues.append(f".pmd has {parts} parts, the .pmg {geometry.part_count}")
    return f"{stem}: .pmd from {pmd_owner}, .pmg from {pmg_owner}: " + "; ".join(issues) if issues else None


def main() -> int:
    tree = Tree()
    models = stems(tree)
    # fetch the base game's counterparts in batches; tree.find would fetch them one at a time
    missing = [f"{s}{x}" for s in models.values() for x in SUFFIXES
               if not (OVERRIDES / f"{s}{x}").is_file() and f"{s}{x}".lower() not in tree.owner]
    missing = [rel for rel in missing if ref_exists(tree.base, rel)]
    for k in range(0, len(missing), 500):
        ref_fetch(tree.base, missing[k:k + 500])
    errors = [e for e in (check(tree, models[s]) for s in sorted(models)) if e]
    for e in errors:
        print("BAD", e)
    print(f"model pairs: {len(models)} checked, {len(errors)} bad")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())

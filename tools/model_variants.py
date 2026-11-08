#!/usr/bin/env python3
"""
Patches merged models that are older than the current base game: copies a source ships of a base model that lack
look or variant names the base model has. The game logs `Unknown variant name 'x' on model ...` (or an unknown look)
for every map item that asks for a name the winning model does not have, and draws its first variant / look instead.
Real companies 2.04.13 (supports ETS2 up to 1.61) ships the gas-station price signs and prefabs that ETS2 1.62
gave new names (Primel `price2`/`price3`, the `bi` looks); the 1.62 playtest log (2026-11-07) showed the Primel
errors in Greece. Decisions: docs/adr/ADR-0007, plan log-errors-162.

world/model_variants.yaml says, per model, which existing look / variant each missing name copies:
  .pmd (visual model, version 4): the missing variant gets a copy of the mapped variant's part attribute values
       (visibility etc.), the missing look a copy of the mapped look's material row. Geometry (.pmg) is untouched.
  .pmc (collision): written as the base game's own copy, and only when the source's collision geometry is the base
       game's (the source shipped an older copy of the base file); otherwise an error.
  `ignore: <reason>` leaves a mismatch as it is (one the game never asks for).
Every locked .pmd/.pmc whose base model has a name the shipped copy lacks must be listed, so a source update or a
game update that changes the set fails --check. When Real companies (or any source) ships a 1.62 update, rerun this
tool: entries the update makes unnecessary are reported as `no longer needed` and should be removed.

Outputs: overrides/<path> for each patched model (git-ignored: regenerate with this tool), the manifest
world/model_variants.tsv (source, base and source sha256, names added, output sha256), and a resolutions.yaml
entry per patched model (run it after `megapack lock`: the entries carry the locked hashes).

usage: python tools/model_variants.py [--check]
  --check: rebuild the models in memory and fail if the manifest or the overrides on disk are out of date.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import pathlib
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import base_dir as base_ref_dir, reference_root, repo_game, ref_exists, ref_fetch, ref_path  # noqa: E402
from pmg import token, token_value  # noqa: E402

CONFIG = ROOT / "world" / "model_variants.yaml"
MANIFEST = ROOT / "world" / "model_variants.tsv"
RESOLUTIONS = ROOT / "resolutions.yaml"
OVERRIDES = ROOT / "overrides"
SUFFIXES = (".pmd", ".pmc")
NOTE = "tools/model_variants.py"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Pmd:
    """Prism model descriptor, version 4: header, look and variant tokens, part attribute ranges, attribute
    definitions, attribute values per variant, a look x material table of absolute offsets into the material
    path strings, then the strings."""

    HEADER = struct.Struct("<16I")

    def __init__(self, data: bytes, name: str) -> None:
        h = self.HEADER.unpack_from(data)
        (ver, self.materials, looks, self.pieces, variants, self.parts, self.attribs, self.values_size,
         strings_size, look_off, variant_off, part_off, values_off, attrib_off, table_off, strings_off) = h
        if ver != 4:
            raise ValueError(f"{name}: pmd version {ver}, expected 4")
        order = [look_off, variant_off, part_off, attrib_off, values_off, table_off, strings_off]
        if order != sorted(order) or strings_off + strings_size != len(data):
            raise ValueError(f"{name}: unexpected pmd layout")
        self.looks = [token(v) for v in struct.unpack_from(f"<{looks}Q", data, look_off)]
        self.variants = [token(v) for v in struct.unpack_from(f"<{variants}Q", data, variant_off)]
        self.part_ranges = data[part_off:attrib_off]
        self.attrib_defs = data[attrib_off:values_off]
        if len(self.part_ranges) != 8 * self.parts or len(self.attrib_defs) != 16 * self.attribs:
            raise ValueError(f"{name}: unexpected pmd section sizes")
        self.values = [data[values_off + i * self.values_size:values_off + (i + 1) * self.values_size]
                       for i in range(variants)]
        if values_off + variants * self.values_size != table_off:
            raise ValueError(f"{name}: unexpected pmd attribute value size")
        rows = struct.unpack_from(f"<{looks * self.materials}I", data, table_off)
        # offsets are kept relative to the string block, so the block can move
        self.table = [[o - strings_off for o in rows[i * self.materials:(i + 1) * self.materials]]
                      for i in range(looks)]
        if table_off + 4 * looks * self.materials != strings_off:
            raise ValueError(f"{name}: unexpected pmd material table size")
        self.strings = data[strings_off:]

    def add_variant(self, new: str, like: str) -> None:
        self.variants.append(new)
        self.values.append(self.values[self.variants.index(like)])

    def add_look(self, new: str, like: str) -> None:
        self.looks.append(new)
        self.table.append(list(self.table[self.looks.index(like)]))

    def to_bytes(self) -> bytes:
        look_off = self.HEADER.size
        variant_off = look_off + 8 * len(self.looks)
        part_off = variant_off + 8 * len(self.variants)
        attrib_off = part_off + len(self.part_ranges)
        values_off = attrib_off + len(self.attrib_defs)
        table_off = values_off + self.values_size * len(self.variants)
        strings_off = table_off + 4 * self.materials * len(self.looks)
        out = [self.HEADER.pack(4, self.materials, len(self.looks), self.pieces, len(self.variants), self.parts,
                                self.attribs, self.values_size, len(self.strings), look_off, variant_off, part_off,
                                values_off, attrib_off, table_off, strings_off),
               struct.pack(f"<{len(self.looks)}Q", *map(token_value, self.looks)),
               struct.pack(f"<{len(self.variants)}Q", *map(token_value, self.variants)),
               self.part_ranges, self.attrib_defs, *self.values,
               struct.pack(f"<{len(self.looks) * self.materials}I", *(o + strings_off for r in self.table for o in r)),
               self.strings]
        return b"".join(out)


class Pmc:
    """Prism collision, version 6: only what this tool needs. Header: version, look count, variant count, two
    counts, then section offsets; look tokens and variant tokens come first. The geometry (everything after the
    variant tokens) is compared as a whole against the base game's copy."""

    def __init__(self, data: bytes, name: str) -> None:
        h = struct.unpack_from("<10I", data)
        if h[0] != 6:
            raise ValueError(f"{name}: pmc version {h[0]}, expected 6")
        self.looks = [token(v) for v in struct.unpack_from(f"<{h[1]}Q", data, h[5])]
        self.variants = [token(v) for v in struct.unpack_from(f"<{h[2]}Q", data, h[6])]
        self.data = data

    def vertices(self) -> bytes:
        """Vertex and index data of the first piece: the collision shape, independent of names and variants."""
        piece = struct.unpack_from("<10I", self.data)[8]
        _, nverts, verts, idx, end = struct.unpack_from("<5I", self.data, piece)
        return self.data[verts:end]


def names(data: bytes, rel: str) -> tuple[list[str], list[str]]:
    m = Pmd(data, rel) if rel.endswith(".pmd") else Pmc(data, rel)
    return m.looks, m.variants


class Inputs:
    def __init__(self) -> None:
        ref = reference_root(repo_game(ROOT))
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = base_ref_dir(ref, mp["base_game"]["version"])
        if not self.base.is_dir():
            sys.exit(f"missing {self.base} — extract-reference base")
        self.winner: dict[str, tuple[str, pathlib.Path]] = {}   # rel (lower) -> (source id, file) of the top layer
        self.rel: dict[str, str] = {}
        self.inputs: dict[str, dict[str, str]] = {}   # rel (lower) -> {source id: sha256} of every source shipping it
        layer: dict[str, int] = {}
        for s in yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]:
            root = ref / "workshop" / str(s["workshop"]) / s["version"]
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if row and not row[0].startswith("#") and row[0] != "path" and row[0].lower().endswith(SUFFIXES):
                    lower = row[0].lower()
                    self.inputs.setdefault(lower, {})[s["id"]] = row[2]
                    if s["layer"] >= layer.get(lower, -1):
                        layer[lower] = s["layer"]
                        self.winner[lower] = (s["id"], root / row[0])
                        self.rel[lower] = row[0]
        self.config = yaml.safe_load(CONFIG.read_text(encoding="utf-8")) or {}


def build(i: Inputs) -> tuple[list[list[str]], dict[str, bytes], list[str], list[str]]:
    """Manifest rows [path, source, base sha, source sha, added], outputs per path, report lines, errors."""
    rows, outs, report, errors = [], {}, [], []
    models = (i.config.get("models") or {})
    ref_fetch(i.base, [r for r in sorted(i.rel.values()) if ref_exists(i.base, r)])   # fetched on demand
    for lower, (src, f) in sorted(i.winner.items()):
        rel = i.rel[lower]
        base_file = ref_path(i.base, rel)
        if not base_file.is_file():
            if rel in models:
                errors.append(f"{rel}: the base game ({i.base.name}) has no such model any more")
            continue
        data, base_data = f.read_bytes(), base_file.read_bytes()
        try:
            looks, variants = names(data, rel)
            blooks, bvariants = names(base_data, f"base {rel}")
        except ValueError as e:
            errors.append(str(e))
            continue
        missing_looks = [n for n in blooks if n not in looks]
        missing_variants = [n for n in bvariants if n not in variants]
        entry = models.get(rel)
        if not missing_looks and not missing_variants:
            if entry is not None:
                report.append(f"no longer needed  {rel} ({src} now has every base name): remove it from "
                              f"{CONFIG.relative_to(ROOT).as_posix()}")
            continue
        want = f"looks {missing_looks} variants {missing_variants}"
        if entry is None:
            errors.append(f"{rel} ({src}) lacks base {want}: add it to {CONFIG.relative_to(ROOT).as_posix()}")
            continue
        if "ignore" in entry:
            report.append(f"ignore  {rel} ({src}) lacks base {want}: {entry['ignore']}")
            continue
        if entry.get("source") != src:
            errors.append(f"{rel}: winner is {src}, the config says {entry.get('source')}")
            continue
        if rel.endswith(".pmc"):
            if not entry.get("base_copy"):
                errors.append(f"{rel}: a .pmc can only be patched with `base_copy: true`")
                continue
            if Pmc(data, rel).vertices() != Pmc(base_data, rel).vertices():
                errors.append(f"{rel}: {src}'s collision shape is not the base game's — needs a real pmc patch")
                continue
            out, added = base_data, "base copy (same shape): " + want
        else:
            m = Pmd(data, rel)
            look_map, variant_map = entry.get("looks") or {}, entry.get("variants") or {}
            if sorted(look_map) != sorted(missing_looks) or sorted(variant_map) != sorted(missing_variants):
                errors.append(f"{rel}: config maps looks {sorted(look_map)} variants {sorted(variant_map)}, "
                              f"the source lacks {want}")
                continue
            bad = [v for v in look_map.values() if v not in m.looks] + \
                  [v for v in variant_map.values() if v not in m.variants]
            if bad:
                errors.append(f"{rel}: config copies {bad}, which {src}'s model does not have")
                continue
            for new, like in look_map.items():
                m.add_look(new, like)
            for new, like in variant_map.items():
                m.add_variant(new, like)
            out = m.to_bytes()
            added = ";".join([f"look {n}<-{l}" for n, l in look_map.items()] +
                             [f"variant {n}<-{v}" for n, v in variant_map.items()])
        outs[rel] = out
        rows.append([rel, src, sha(base_data), sha(data), added])
    for rel in models:
        if rel.lower() not in i.winner:
            errors.append(f"{rel}: listed in {CONFIG.relative_to(ROOT).as_posix()} but no source ships it")
    return rows, outs, report, errors


def read_manifest() -> tuple[list[list[str]], dict[str, str]]:
    rows, outs = [], {}
    if MANIFEST.is_file():
        for row in csv.reader(MANIFEST.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "path":
                rows.append(row[:5])
                outs[row[0]] = row[5]
    return rows, outs


def write_manifest(rows: list[list[str]], outs: dict[str, bytes]) -> None:
    lines = ["# GENERATED by tools/model_variants.py — do not edit by hand.",
             "path\tsource\tbase_sha256\tsource_sha256\tadded\toutput_sha256"]
    lines += ["\t".join(r + [sha(outs[r[0]])]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def resolutions_text(i: Inputs, rows: list[list[str]]) -> str:
    """resolutions.yaml with this tool's entries (one per patched model, stamped with every shipping source's hash)
    replaced; other tools' and hand-written entries are kept."""
    text = RESOLUTIONS.read_text(encoding="utf-8")
    head, _, _ = text.partition("\nresolutions:")
    doc = yaml.safe_load(text) or {}
    entries = doc.get("resolutions") or []
    # hand-written entries first, then ours, then other tools' (tools/rain_reflections.py appends its own last)
    hand = [r for r in entries if not str(r.get("note", "")).startswith("tools/")]
    tools = [r for r in entries if str(r.get("note", "")).startswith("tools/")
             and not str(r.get("note", "")).startswith(NOTE)]
    ours = [{"path": r[0], "merged": f"overrides/{r[0]}", "inputs": i.inputs[r[0].lower()],
             "note": f"{NOTE}: the {r[1]} model given the base game's newer names ({r[4]})"} for r in rows]
    body = yaml.safe_dump({"resolutions": hand + ours + tools}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + "\n" + body


def stale(outs: dict[str, bytes]) -> list[pathlib.Path]:
    """Overrides this tool wrote before (in the old manifest) but no longer produces."""
    return [OVERRIDES / r[0] for r in read_manifest()[0] if r[0] not in outs and (OVERRIDES / r[0]).is_file()]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    i = Inputs()
    rows, outs, report, errors = build(i)
    for r in report:
        print(r)
    for e in errors:
        print("ERROR  " + e)
    print(f"{len(rows)} models patched")
    if errors:
        return 1
    res = resolutions_text(i, rows)

    if args.check:
        old_rows, old_outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (base game, a source or the config)")
        for rel, data in outs.items():
            f = OVERRIDES / rel
            if old_outs.get(rel) != sha(data) or not f.is_file() or sha(f.read_bytes()) != sha(data):
                problems.append(f"{f.relative_to(ROOT).as_posix()} missing or changed")
        problems += [f"{f.relative_to(ROOT).as_posix()} is not produced by this tool any more" for f in stale(outs)]
        if res != RESOLUTIONS.read_text(encoding="utf-8"):
            problems.append("resolutions.yaml entries out of date")
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/model_variants.py")
        return 1 if problems else 0

    for f in stale(outs):
        f.unlink()
        print(f"removed stale {f.relative_to(ROOT).as_posix()}")
    for rel, data in outs.items():
        f = OVERRIDES / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
    write_manifest(rows, outs)
    RESOLUTIONS.write_text(res, encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}, {len(outs)} models to overrides/, resolutions.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())

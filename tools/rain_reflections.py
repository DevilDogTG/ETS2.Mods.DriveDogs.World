#!/usr/bin/env python3
"""
Generates World's take on Realistic Rain Reflections Standalone (Grimes, v1.4; not on the Workshop) into
overrides/: wet-road puddles blended into the winning road normal maps, and its reflection/shine values on base
materials. The mod itself is never merged: its road colour textures lose to Asphalt_improved, and its junction
models, truck headlights, climate, env_data and rain files are old whole copies or effects World takes from
elsewhere. Decisions: plan world-graphics, sub-plan rain-extras; ADR docs/adr/ADR-0002-world-graphics.md.

1. Puddles (normal-map blend). RRR gives road materials its own lane-wide normal maps (`ntex/road_ntex_*_nrm`,
   wheel tracks tilted so water and reflections collect in them), replacing the road's own normal map. Asphalt
   ships its own normal maps on the same materials, and a material takes one normal map. So each winning normal
   map RRR would replace is rewritten as a blend: Asphalt's (or the base game's) surface detail reoriented onto
   RRR's wheel tracks (Reoriented Normal Mapping), same format (BC5) and mip chain as the winner's file, at RRR's
   size where that is larger (KEEP_RUT_SIZE). The rut tilt is scaled per folder (RUT_STRENGTH): Asphalt's
   universal and blkw maps are rough enough to bury the ruts at RRR's own strength.
   Both maps are sampled with the same UVs, since RRR swapped them on the same materials. Covered:
     - country road templates `material/road/road_template/<c>/*.mat` (RRR adds a normal map; the winning
       material's own normal map is blended)
     - `road_template/un/*_nrm.tobj` (RRR points the universal roads' normal maps at its own; the winning
       texture is blended), which also reaches every junction material that uses them.
   Junction materials that have no normal map in 1.61 (RRR gives them its rut maps) get the blended normal map of
   the road template with the same colour texture (JUNCTION_NMAPS), plus `.tsnmapcalc` in their effect.
2. Values. On base-game `umatlib/**` and `automat/**` materials RRR changes, only the reflection, specular and
   shininess values are carried (sidewalks, tiles, concrete, cobblestone, parking lots, junctions). Its effect
   and texture swaps are not: they drop the 1.61 reflection flavour (`.rfx`) or point at its normal maps.

Outputs: overrides/<path> for every blended .dds (git-ignored: regenerate with this tool) and edited .mat, the
manifest world/rain_reflections.tsv (output sha256 + input sha256s), and resolutions.yaml entries for the
overrides a source also ships (so `megapack check` flags an upstream change).

usage: python tools/rain_reflections.py [--check]
  --check: recompute the plan and input hashes (no encoding) and fail if the manifest, the overrides on disk or
           resolutions.yaml are out of date.
Needs Pillow (BC5 encoder) and numpy.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import pathlib
import re
import struct
import sys

import numpy as np
import yaml
from PIL import Image

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/scs-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import reference_root, repo_game, ref_path  # noqa: E402

RRR_ID, RRR_VERSION = "rain-reflections", "1.4"   # <reference root>/local/<id>/<version>/, the unzipped .scs
MANIFEST = ROOT / "world" / "rain_reflections.tsv"
OVERRIDES = ROOT / "overrides"
RESOLUTIONS = ROOT / "resolutions.yaml"
NOTE = "tools/rain_reflections.py"
# Scale of RRR's wheel-track tilt in the blend (1.0 = as RRR made it), by road-texture folder. Asphalt's universal
# (un/) and blkw maps are rough (~33-38 deg mean tilt vs RRR's 11.6), which buried the ruts at ~60% of RRR's
# large-scale tilt in 1.0.0-1.4.0; the country templates (~5 deg) kept ~90% at 1.0.
RUT_STRENGTH = {"un": 1.6, "blkw": 1.4}
RUT_STRENGTH_DEFAULT = 1.0
# Junction materials RRR gives a rut map where the base game has no normal map get the blended normal map of the
# road template that uses the same colour texture (so the junction matches the road next to it), with the effect's
# `.tsnmapcalc` flavour added before `.rfx`. RRR's own rut maps are never shipped.
JUNCTION_NMAPS = True
# Blends are written at RRR's rut-map size when the winner's map is smaller (Asphalt's are 1024, RRR's 2048), so
# RRR's fine water-surface detail is not lost to downscaling.
KEEP_RUT_SIZE = True
VALUE_KEYS = ["reflection", "reflection_secondary", "specular", "specular_secondary", "shininess",
              "shininess_secondary"]
DDS_PATH = re.compile(rb"/[\w/.\-]+\.dds")
TEX = re.compile(r'texture\s*:\s*"(\w+)"\s*\{[^}]*?source\s*:\s*"([^"]+)"', re.S)
LEGACY_TEX = re.compile(r'texture\[(\d)\]\s*:\s*"([^"]+)"')
LEGACY_NAME = re.compile(r'texture_name\[(\d)\]\s*:\s*"([^"]+)"')
VALUE_LINE = r"^(\s*{key}\s*:\s*)(.+?)\s*$"


def sha(p: pathlib.Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


# --- inputs -----------------------------------------------------------------------------------------------------

class Merge:
    """Winner lookup over the locked sources (highest layer wins, as every collision in this pack is declared)."""

    def __init__(self) -> None:
        ref = reference_root(repo_game(ROOT))
        mp = yaml.safe_load((ROOT / "megapack.yaml").read_text(encoding="utf-8"))
        self.base = ref / "base" / str(mp["base_game"]["version"])
        self.rrr = ref / "local" / RRR_ID / RRR_VERSION
        for d, how in [(self.base, "extract-reference base"), (self.rrr, "unzip the RRR .scs (extract-reference local)")]:
            if not d.is_dir():
                sys.exit(f"missing {d} — {how}")
        srcs = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
        self.holders: dict[str, list[tuple[int, str, pathlib.Path, str]]] = {}
        for s in srcs:
            d = ref / "workshop" / str(s["workshop"]) / str(s["version"])
            for row in csv.reader((ROOT / "lock" / f"{s['id']}.tsv").read_text(encoding="utf-8").splitlines(),
                                  delimiter="\t"):
                if not row or row[0].startswith("#") or row[0] == "path":
                    continue
                self.holders.setdefault(row[0].lower(), []).append((s["layer"], s["id"], d / row[0], row[2]))

    def winner(self, rel: str) -> tuple[str, pathlib.Path] | None:
        """(source id or "base", file) for a game path; None if nobody ships it."""
        h = self.holders.get(rel.lower().lstrip("/"))
        if h:
            _, sid, path, _ = max(h)
            return sid, path
        p = ref_path(self.base, rel)          # base assets are fetched on demand
        return ("base", p) if p.is_file() else None

    def inputs(self, rel: str) -> dict[str, str]:
        return {sid: digest for _, sid, _, digest in self.holders.get(rel.lower(), [])}


def tobj_dds(tobj: pathlib.Path) -> str:
    m = DDS_PATH.search(tobj.read_bytes())
    if not m:
        raise ValueError(f"{tobj}: no .dds path")
    return m.group().decode()


def resolve(rel_dir: str, ref: str) -> str:
    """A material's texture reference (absolute, or relative to the material's folder) as a game path."""
    return ref.lstrip("/") if ref.startswith("/") else f"{rel_dir}/{ref}"


def nmap_of(mat_text: str) -> str | None:
    for name, src in TEX.findall(mat_text):
        if name == "texture_nmap":
            return src
    names = dict(LEGACY_NAME.findall(mat_text))
    for i, src in LEGACY_TEX.findall(mat_text):
        if names.get(i) == "texture_nmap":
            return src
    return None


# --- plan -------------------------------------------------------------------------------------------------------

def plan(m: Merge) -> tuple[dict[str, dict], dict[str, dict], list[str]]:
    """blends {target dds: {detail, detail_src, ruts, via}}, values {mat: {base, ops, nmaps, effect}}, report lines."""
    blends: dict[str, dict] = {}
    report: list[str] = []

    def want(target_tobj: str, ruts_tobj: pathlib.Path, via: str) -> None:
        w = m.winner(target_tobj)
        if w is None:
            report.append(f"skip  {via}: winner has no {target_tobj}")
            return
        target = tobj_dds(w[1]).lstrip("/")
        dw = m.winner(target)
        if dw is None:
            report.append(f"skip  {via}: {target} missing")
            return
        ruts = tobj_dds(ruts_tobj).lstrip("/")
        prev = blends.get(target)
        if prev and prev["ruts"] != ruts:
            report.append(f"keep  {target}: first puddle map {prev['ruts']} (also wanted {ruts} by {via})")
            return
        blends.setdefault(target, {"detail_src": dw[0], "detail": dw[1], "ruts": ruts, "via": via})

    road = m.rrr / "material/road/road_template"
    for mat in sorted(road.rglob("*.mat")):
        rel = mat.relative_to(m.rrr).as_posix()
        rrr_nmap = nmap_of(mat.read_text(encoding="utf-8", errors="ignore"))
        w = m.winner(rel)
        if rrr_nmap is None or w is None:
            report.append(f"skip  {rel}: {'no RRR normal map' if rrr_nmap is None else 'not in the game (ATS)'}")
            continue
        own = nmap_of(w[1].read_text(encoding="utf-8", errors="ignore"))
        if own is None:
            report.append(f"skip  {rel}: the winning material ({w[0]}) has no normal map to blend")
            continue
        rel_dir = rel.rsplit("/", 1)[0]
        want(resolve(rel_dir, own), m.rrr / resolve(rel_dir, rrr_nmap), rel)
    for tobj in sorted((road / "un").glob("*_nrm.tobj")):
        rel = tobj.relative_to(m.rrr).as_posix()
        want(rel, tobj, rel)

    road_nmaps = road_nmap_index(m, blends) if JUNCTION_NMAPS else {}
    values: dict[str, dict] = {}
    for top in ("umatlib", "automat"):
        for mat in sorted((m.rrr / top).rglob("*.mat")):
            rel = mat.relative_to(m.rrr).as_posix()
            base = m.base / rel
            if not base.is_file():
                continue          # RRR's own copies for its junction models (not taken) and old leftovers
            if rel.lower() in m.holders:
                sys.exit(f"{rel} is shipped by {m.inputs(rel)} — carry RRR's values onto that winner first")
            theirs, ours = mat.read_text(encoding="utf-8", errors="ignore"), base.read_text(encoding="utf-8")
            ops = {}
            for key in VALUE_KEYS:
                a, b = (re.search(VALUE_LINE.format(key=key), t, re.M) for t in (theirs, ours))
                if a and b and canon(a.group(2)) != canon(b.group(2)):
                    ops[key] = a.group(2)
                elif a and not b:
                    report.append(f"skip  {rel}: {key} not in the base material")
            nmaps, effect = junction_nmaps(rel, theirs, ours, road_nmaps, report)
            if ops or nmaps:
                values[rel] = {"base": base, "ops": ops, "nmaps": nmaps, "effect": effect}
    return blends, values, report


def mat_textures(text: str) -> dict[str, str]:
    """{texture name: source} of a material, either format."""
    out = dict(TEX.findall(text))
    names = dict(LEGACY_NAME.findall(text))
    for i, src in LEGACY_TEX.findall(text):
        out.setdefault(names.get(i, ""), src)
    return out


def road_nmap_index(m: Merge, blends: dict) -> dict[str, str]:
    """{colour texture .tobj game path (lower case): normal-map .tobj game path} from every winning road-template
    material whose normal map World blends."""
    mats = {h for h in m.holders if h.startswith("material/road/road_template/") and h.endswith(".mat")}
    mats |= {p.relative_to(m.base).as_posix().lower() for p in (m.base / "material/road/road_template").rglob("*.mat")}
    index: dict[str, str] = {}
    for rel in sorted(mats):
        w = m.winner(rel)
        if w is None:
            continue
        tex, rel_dir = mat_textures(w[1].read_text(encoding="utf-8", errors="ignore")), rel.rsplit("/", 1)[0]
        if "texture_base" not in tex or "texture_nmap" not in tex:
            continue
        nmap = resolve(rel_dir, tex["texture_nmap"])
        nw = m.winner(nmap)
        if nw and tobj_dds(nw[1]).lstrip("/") in blends:
            index.setdefault(resolve(rel_dir, tex["texture_base"]).lower(), "/" + nmap)
    return index


def junction_nmaps(rel: str, theirs: str, ours: str, road_nmaps: dict[str, str],
                   report: list[str]) -> tuple[dict[str, str], str]:
    """({texture_nmap[_over]: .tobj}, new effect) for a junction material RRR gives a rut map and 1.61 none."""
    rrr_nmap = nmap_of(theirs)
    if not road_nmaps or rrr_nmap is None or "road_ntex" not in rrr_nmap or nmap_of(ours) is not None:
        return {}, ""
    tex = mat_textures(ours)
    nmaps = {}
    for layer, name in (("texture_base", "texture_nmap"), ("texture_over", "texture_nmap_over")):
        if layer not in tex:
            continue
        nmap = road_nmaps.get(tex[layer].lstrip("/").lower())
        if nmap is None:
            report.append(f"skip  {rel}: no blended road normal map for {tex[layer]}")
            return {}, ""
        nmaps[name] = nmap
    effect = re.search(r'^\s*effect\s*:\s*"([^"]+)"', ours, re.M)
    if not nmaps or effect is None or ".tsnmapcalc" in effect.group(1):
        report.append(f"skip  {rel}: unexpected effect or textures")
        return {}, ""
    e = effect.group(1)
    return nmaps, (e[: -len(".rfx")] + ".tsnmapcalc.rfx" if e.endswith(".rfx") else e + ".tsnmapcalc")


def canon(v: str) -> str:
    nums = re.findall(r"-?\d+(?:\.\d+)?", v)
    return ",".join(f"{float(x):g}" for x in nums) if nums else v.strip()


# --- normal maps ------------------------------------------------------------------------------------------------

def load_xy(path: pathlib.Path, size: tuple[int, int] | None = None) -> np.ndarray:
    data = path.read_bytes()
    im = Image.open(io.BytesIO(data)).convert("RGB")
    if size and im.size != size:
        im = im.resize(size, Image.LANCZOS)
    a = np.asarray(im, dtype=np.float32)[:, :, :2] / 255.0 * 2.0 - 1.0
    return a


def to_normal(xy: np.ndarray) -> np.ndarray:
    z = np.sqrt(np.clip(1.0 - (xy ** 2).sum(-1, keepdims=True), 0.0, 1.0))
    n = np.concatenate([xy, z], -1)
    return n / np.linalg.norm(n, axis=-1, keepdims=True)


def blend(detail: np.ndarray, ruts: np.ndarray) -> np.ndarray:
    """Reoriented Normal Mapping: detail normals carried onto the rut (base) normals."""
    t = ruts + np.array([0.0, 0.0, 1.0], np.float32)
    u = detail * np.array([-1.0, -1.0, 1.0], np.float32)
    r = t * (t * u).sum(-1, keepdims=True) / t[..., 2:3] - u
    return r / np.linalg.norm(r, axis=-1, keepdims=True)


def rut_strength(target: str) -> float:
    folder = target.split("road_template/", 1)[-1].split("/", 1)[0]
    return RUT_STRENGTH.get(folder, RUT_STRENGTH_DEFAULT)


def out_size(detail: pathlib.Path, ruts: pathlib.Path) -> tuple[int, int]:
    """(width, height) of a blend: the winner's, or RRR's rut map's where that is larger (KEEP_RUT_SIZE)."""
    dw, dh = struct.unpack("<II", detail.read_bytes()[12:20])[::-1]
    if not KEEP_RUT_SIZE:
        return dw, dh
    with Image.open(ruts) as im:
        rw, rh = im.size
    return max(dw, rw), max(dh, rh)


def full_chain(w: int, h: int) -> int:
    return max(w, h).bit_length()


def bc_size(w: int, h: int, mips: int) -> int:
    total = 0
    for _ in range(mips):
        total += max(1, (w + 3) // 4) * max(1, (h + 3) // 4) * 16
        w, h = max(1, w // 2), max(1, h // 2)
    return total


def encode_like(n: np.ndarray, template: bytes) -> bytes:
    """BC5 DDS with the template file's header (DXGI format, flags); size from `n`, mip count as the template's
    (a full chain stays a full chain at a new size); mips by box filter."""
    if template[84:88] != b"DX10" or struct.unpack("<I", template[128:132])[0] not in (83, 84):
        raise ValueError("winner normal map is not BC5 (DXGI 83/84)")
    th, tw = struct.unpack("<II", template[12:20])
    mips = max(1, struct.unpack("<I", template[28:32])[0])
    h, w = n.shape[:2]
    head = bytearray(template[:148])
    if (h, w) != (th, tw):
        if mips == full_chain(tw, th):
            mips = full_chain(w, h)
        struct.pack_into("<III", head, 12, h, w, bc_size(w, h, 1))   # height, width, linear size of the top level
        struct.pack_into("<I", head, 28, mips)
    out = [bytes(head)]
    level = n
    for i in range(mips):
        if i:
            h, w = level.shape[:2]
            level = level[: h - h % 2 or 1, : w - w % 2 or 1]
            if h > 1 and w > 1:
                level = (level[0::2, 0::2] + level[1::2, 0::2] + level[0::2, 1::2] + level[1::2, 1::2]) / 4
            elif h > 1:
                level = (level[0::2] + level[1::2]) / 2
            elif w > 1:
                level = (level[:, 0::2] + level[:, 1::2]) / 2
            level = level / np.maximum(np.linalg.norm(level, axis=-1, keepdims=True), 1e-6)
        rgb = np.zeros(level.shape[:2] + (3,), np.uint8)
        rgb[..., :2] = np.clip(np.round((level[..., :2] + 1.0) / 2.0 * 255.0), 0, 255).astype(np.uint8)
        buf = io.BytesIO()
        Image.fromarray(rgb, "RGB").save(buf, "DDS", pixel_format="BC5")
        out.append(buf.getvalue()[148:])
    data = b"".join(out)
    want = 148 + bc_size(n.shape[1], n.shape[0], mips)
    if len(data) != want:
        raise ValueError(f"encoded {len(data)} bytes, expected {want}")
    return data


# --- outputs ----------------------------------------------------------------------------------------------------

def edit_mat(text: str, ops: dict[str, str], nmaps: dict[str, str] | None = None, effect: str = "") -> str:
    for key, val in ops.items():
        text, n = re.subn(VALUE_LINE.format(key=key), lambda m: m.group(1) + val, text, count=1, flags=re.M)
        assert n == 1, key
    if nmaps:
        nl = "\r\n" if "\r\n" in text else "\n"
        text, n = re.subn(r'^(\s*effect\s*:\s*)"[^"]+"', lambda m: f'{m.group(1)}"{effect}"', text, count=1, flags=re.M)
        assert n == 1, "effect"
        blocks = "".join(f'\ttexture : "{name}" {{{nl}\t\tsource : "{src}"{nl}\t\tsampler : default{nl}\t}}{nl}'
                         for name, src in nmaps.items())
        end = text.rstrip().rfind("}")
        text = text[:end] + blocks + text[end:]
    return text


def manifest_rows(m: Merge, blends: dict, values: dict) -> list[list[str]]:
    rows = []
    for target, b in sorted(blends.items()):
        w, h = out_size(b["detail"], m.rrr / b["ruts"])
        rows.append([target, "blend", f"{b['detail_src']}:{sha(b['detail'])}", f"rrr:{sha(m.rrr / b['ruts'])}",
                     f"{rut_strength(target):g}@{w}x{h}"])
    for rel, v in sorted(values.items()):
        rows.append([rel, "values", f"base:{sha(v['base'])}",
                     ";".join([f"{k}={canon(x)}" for k, x in v["ops"].items()]
                              + [f"{k}={x}" for k, x in v["nmaps"].items()]), ""])
    return rows


def other_owned() -> set[str]:
    """overrides/ paths another tool produces (tools/base_material_fixes.py writes automat/ materials too)."""
    f = ROOT / "world" / "base_material_fixes.tsv"
    if not f.is_file():
        return set()
    return {row[0] for row in csv.reader(f.read_text(encoding="utf-8").splitlines(), delimiter="	")
            if row and row[0] != "path"}


def read_manifest() -> tuple[list[list[str]], dict[str, str]]:
    rows, outs = [], {}
    if MANIFEST.is_file():
        for row in csv.reader(MANIFEST.read_text(encoding="utf-8").splitlines(), delimiter="\t"):
            if row and not row[0].startswith("#") and row[0] != "path":
                rows.append(row[:5])
                outs[row[0]] = row[5]
    return rows, outs


def write_manifest(rows: list[list[str]], outs: dict[str, str]) -> None:
    lines = ["# GENERATED by tools/rain_reflections.py — do not edit by hand.",
             "path\tkind\tinput\tpuddles_or_values\trut_strength@size\toutput_sha256"]
    lines += ["\t".join(r + [outs[r[0]]]) for r in rows]
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def resolutions_text(m: Merge, blends: dict) -> str:
    text = RESOLUTIONS.read_text(encoding="utf-8")
    head, _, _ = text.partition("\nresolutions:")
    doc = yaml.safe_load(text) or {}
    keep = [r for r in (doc.get("resolutions") or []) if not str(r.get("note", "")).startswith(NOTE)]
    ours = [{"path": t, "merged": f"overrides/{t}", "inputs": m.inputs(t),
             "note": f"{NOTE}: {b['detail_src']}'s normal map blended with Realistic Rain Reflections' puddles"}
            for t, b in sorted(blends.items()) if m.inputs(t)]
    body = yaml.safe_dump({"resolutions": keep + ours}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + "\n" + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    m = Merge()
    blends, values, report = plan(m)
    for r in report:
        print(r)
    rows = manifest_rows(m, blends, values)
    res = resolutions_text(m, blends)
    print(f"{len(blends)} normal maps to blend, {len(values)} materials with value edits")

    if args.check:
        old_rows, outs = read_manifest()
        problems = []
        if old_rows != rows:
            problems.append(f"{MANIFEST.relative_to(ROOT)} inputs changed (sources, base or RRR)")
        for r in rows:
            f = OVERRIDES / r[0]
            if not f.is_file() or sha(f) != outs.get(r[0]):
                problems.append(f"overrides/{r[0]} missing or changed")
        if res != RESOLUTIONS.read_text(encoding="utf-8"):
            problems.append("resolutions.yaml entries out of date")
        known = {r[0] for r in rows} | other_owned()
        for f in OVERRIDES.rglob("*"):
            rel = f.relative_to(OVERRIDES).as_posix()
            if f.is_file() and rel.startswith(("material/road/", "umatlib/", "automat/")) and rel not in known:
                problems.append(f"overrides/{rel} is not produced by this tool any more")
        for p in problems[:20]:
            print("OUT OF DATE  " + p)
        print("up to date" if not problems else f"{len(problems)} problem(s) — rerun tools/rain_reflections.py")
        return 1 if problems else 0

    outs = {}
    for i, (target, b) in enumerate(sorted(blends.items()), 1):
        template = b["detail"].read_bytes()
        w, h = out_size(b["detail"], m.rrr / b["ruts"])
        detail = to_normal(load_xy(b["detail"], (w, h)))
        ruts = load_xy(m.rrr / b["ruts"], (w, h)) * rut_strength(target)
        data = encode_like(blend(detail, to_normal(ruts)), template)
        dest = OVERRIDES / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        outs[target] = hashlib.sha256(data).hexdigest()
        print(f"[{i}/{len(blends)}] blend {target} ({b['detail_src']}, {w}x{h}) + {b['ruts'].rsplit('/', 1)[1]}"
              f" x{rut_strength(target):g}")
    for rel, v in sorted(values.items()):
        text = edit_mat(v["base"].read_text(encoding="utf-8", newline=""), v["ops"], v["nmaps"], v["effect"])
        dest = OVERRIDES / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", newline="")
        outs[rel] = sha(dest)
    keep = set(outs) | other_owned()
    for f in OVERRIDES.rglob("*"):
        rel = f.relative_to(OVERRIDES).as_posix()
        if f.is_file() and rel.startswith(("material/road/", "umatlib/", "automat/")) and rel not in keep:
            f.unlink()
            print(f"removed stale overrides/{rel}")
    write_manifest(rows, outs)
    RESOLUTIONS.write_text(res, encoding="utf-8", newline="\n")
    print(f"wrote {MANIFEST.relative_to(ROOT)}, overrides/, resolutions.yaml")
    return 0


if __name__ == "__main__":
    sys.exit(main())

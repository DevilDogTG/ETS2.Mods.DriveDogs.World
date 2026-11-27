#!/usr/bin/env python3
"""
Generates World's take on Realistic Rain Reflections Standalone (Grimes, v1.5; not on the Workshop) into
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
   universal and blkw maps are rough enough to bury the ruts at RRR's own strength. RRR's constant ~4 deg
   tilt under the ruts is taken out (RUT_FLAT_MEAN), so a road is as bright as flat asphalt in dry sun.
   Both maps are sampled with the same UVs, since RRR swapped them on the same materials. Covered:
     - country road templates `material/road/road_template/<c>/*.mat` (RRR adds a normal map; the winning
       material's own normal map is blended)
     - `road_template/un/*_nrm.tobj` (RRR points the universal roads' normal maps at its own; the winning
       texture is blended), which also reaches every junction material that uses them.
   Junction, yard and parking materials with no normal map (WET_JUNCTIONS): every asphalt layer gets `reflection` 1
   where it had 0, nothing else (no normal map: JUNCTION_NMAPS is off, a mapped junction layer could draw without sun
   light). So in dry weather a junction is the game's, and in rain every asphalt layer of it looks wet. RRR's own
   junction rut maps are never shipped.
   Grain floor (GRAIN_MIN_TILT): a detail map smoother than that (the country templates, the legacy roads) has its
   fine grain (high-pass) raised until it reaches it, so wet roads sparkle like the rough universal/blkw roads
   instead of mirroring buildings in patches. Rough maps are left as they are.
   Legacy roads (LEGACY_ROADS): the pre-template roads (`def/world/road_material.sii`, ~8% of road items, most of
   the UK) take Asphalt's `material/road/*.mat`, which RRR never touched, so they had no wheel tracks. Their
   normal maps get World's own tracks: two troughs per lane strip (the legacy textures put a lane in each 0.25 of
   U, seams at 0.25/0.5/0.752 in every legacy road look; 0.752-0.944 is shoulder), at RRR's large-scale depth, and
   their shininess goes to the templates' 50 (LEGACY_SHININESS) for the templates' narrower glare.
2. Values. On base-game `umatlib/**` and `automat/**` materials RRR changes, only the reflection, specular and
   shininess values are carried (sidewalks, tiles, concrete, cobblestone, parking lots, junctions). Its effect
   and texture swaps are not: they drop the 1.61 reflection flavour (`.rfx`) or point at its normal maps.

Outputs: overrides/<path> for every blended .dds (and the junction grain map with JUNCTION_NMAPS; git-ignored:
regenerate with this tool), the grain map's .tobj (JUNCTION_NMAPS) and every edited .mat, the
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
from megapack import base_dir as base_ref_dir, reference_root, repo_game, ref_path  # noqa: E402

RRR_ID, RRR_VERSION = "rain-reflections", "1.5"   # <reference root>/local/<id>/<version>/, the unzipped .scs
MANIFEST = ROOT / "world" / "rain_reflections.tsv"
OVERRIDES = ROOT / "overrides"
RESOLUTIONS = ROOT / "resolutions.yaml"
NOTE = "tools/rain_reflections.py"
# Scale of RRR's wheel-track tilt in the blend (1.0 = as RRR made it), by road-texture folder. Asphalt's universal
# (un/) and blkw maps are rough (~33-38 deg mean tilt vs RRR's 11.6), which buried the ruts at ~60% of RRR's
# large-scale tilt in 1.0.0-1.4.0; the country templates (~5 deg) kept ~90% at 1.0.
RUT_STRENGTH = {"un": 1.6, "blkw": 1.4}
RUT_STRENGTH_DEFAULT = 1.0
# RRR's rut maps (DXT3) average R and G ~131-135 where flat is 128: a constant ~4 deg diagonal tilt on top of the
# ruts (a tiling trough averages flat). Blended in (1.0-1.7.3-dev.1), it tilted every road 3-5 deg, so in dry sun a
# road drew up to ~10% lighter or darker than flat (the junction next to it, the game's own road) by direction of
# travel. The ruts are taken minus their mean xy; their shape, and so the wet look, stays (plan
# world-rain-only-junctions, 2026-11-22).
RUT_FLAT_MEAN = True
# Blends are written at RRR's rut-map size when the winner's map is smaller (Asphalt's are 1024, RRR's 2048), so
# RRR's fine water-surface detail is not lost to downscaling.
KEEP_RUT_SIZE = True
# Minimum mean tilt (deg) of a blend's surface detail. The country templates (~5 deg detail, ~10.5 blended) and the
# legacy roads (4-6) mirrored buildings in patches when wet; the universal and blkw roads (20-29 blended) sparkle,
# the look asked for (Crete, 2026-10-31). Only the fine grain (detail minus its GRAIN_RADIUS px box blur) is raised.
GRAIN_MIN_TILT = 22.0
GRAIN_RADIUS = 16
# Legacy road materials that get wheel tracks and the shininess value: asphalt surfaces only (not cobbles, dirt
# paths or the snow road).
LEGACY_ROADS = re.compile(r"^material/road/(asphalt[\w]*|hw_\w+|gray_old_map_fr)\.mat$")
LEGACY_LANES = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.752))   # U strips, one lane each
LEGACY_TRACKS = (0.25, 0.70)      # wheel-track centres across a lane strip (a truck's ~2 m track in a 4.5 m strip)
LEGACY_TRACK_WIDTH = 0.07         # trough sigma, fraction of the strip (~0.3 m)
LEGACY_RUT_SLOPE = 0.18           # peak slope of a trough flank (~10 deg; mean over the lane ~RRR's 5 deg)
LEGACY_SHININESS = "50"
# Wet junctions (1.7.3). Every junction, yard and parking material (base automat/ and umatlib/) with no normal map and
# an ASPHALT layer gets `reflection` JUNCTION_REFLECTION where it is 0. `reflection` (how wet a layer gets) acts in
# rain only, so in dry weather a junction is drawn exactly as the game draws it (effect, maps, shininess, specular
# untouched; RRR's carried values stay, as in 1.7.1), and in rain every asphalt layer of it gets the wet dimming, gloss
# and sky reflection. JUNCTION_NMAPS (off) also gave each asphalt layer one shared map, the fine grain of the universal
# asphalt map (JUNCTION_GRAIN_SOURCE minus its GRAIN_RADIUS box blur) at JUNCTION_GRAIN_TILT mean tilt, other layers
# FLAT_NMAP and the effect `.tsnmapcalc` (only into an effect the base game uses): in 1.7.2 (22-deg grain) and
# 1.7.3-dev.1/.2 (this grain) one asphalt layer of a two-layer junction drew without sun light at all in dry weather
# (Lisbon Marina crossroads, 2026-11-23), so junctions keep the game's flat effect. Decisions: plan
# world-rain-only-junctions (option A, dev.3).
WET_JUNCTIONS = True
JUNCTION_NMAPS = False
JUNCTION_GRAIN_TILT = 9.0
JUNCTION_GRAIN_SOURCE = "material/road/road_template/un/asp_new_01_nrm.tobj"
JUNCTION_REFLECTION = "1.000000"
# Asphalt colour textures, besides the road-template colours World blends and the legacy road colours: legacy and
# prefab asphalt, dark_c* repair patches, terrain asphalt (parking lots, asphalt tiles) and the junction prefabs'
# asphalt-with-patches atlas.
ASPHALT = re.compile(r"^(material/road/(asphalt\w*|dark_c\w*|hw_\w+|rough_asphalt\w*|road_crack|gray_old_map\w*"
                     r"|road_template/fr/gray_old_map\w*|road_template/it/\d+_cors)"
                     r"|material/terrain/asphalt\w*|prefab/cross/road_decals\w*)\.tobj$")
GRAIN_DIR = "material/road/drivedog_wet"
JUNCTION_GRAIN = f"{GRAIN_DIR}/junction_grain_nrm"
FLAT_NMAP = "/system/special/flat_nrm.tobj"    # what SCS's own two-layer materials use on a layer without one
LAYERS = (("texture_base", "texture_nmap", "reflection"), ("texture_over", "texture_nmap_over", "reflection_secondary"))
TOBJ_PATH_AT = 40                              # .tobj: u32 path length at 40, the path from 48
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
        self.base = base_ref_dir(ref, mp["base_game"]["version"])
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

    road_nmaps = road_nmap_index(m, blends) if WET_JUNCTIONS else {}
    values: dict[str, dict] = {}
    legacy_nmaps: dict[str, str] = {}
    legacy = re.findall(r'^\s*path\s*:\s*"/([^"]+)"', (m.base / "def/world/road_material.sii").read_text(encoding="utf-8"),
                        re.M)
    for rel in sorted(set(p for p in legacy if LEGACY_ROADS.match(p))):
        w = m.winner(rel)
        own = nmap_of(w[1].read_text(encoding="utf-8", errors="ignore")) if w else None
        if own is None:
            report.append(f"skip  {rel}: the winning material has no normal map (legacy road)")
            continue
        nw = m.winner(resolve(rel.rsplit("/", 1)[0], own))
        target = tobj_dds(nw[1]).lstrip("/") if nw else None
        dw = m.winner(target) if target else None
        if dw is None:
            report.append(f"skip  {rel}: normal map {own} missing")
            continue
        blends.setdefault(target, {"detail_src": dw[0], "detail": dw[1], "ruts": None, "via": rel})
        text = w[1].read_text(encoding="utf-8", errors="ignore")
        colour = mat_textures(text).get("texture_base")
        if colour:
            legacy_nmaps[resolve(rel.rsplit("/", 1)[0], colour).lower()] = "/" + resolve(rel.rsplit("/", 1)[0], own)
        cur = re.search(VALUE_LINE.format(key="shininess"), text, re.M)
        if cur and canon(cur.group(2)) != canon(LEGACY_SHININESS):
            values[rel] = {"base": w[1], "src": w[0], "ops": {"shininess": LEGACY_SHININESS}, "nmaps": {}, "effect": ""}
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
            if ops:
                values[rel] = {"base": base, "ops": ops, "nmaps": {}, "effect": ""}
    if WET_JUNCTIONS:
        wet_junctions(m, set(legacy_nmaps) | set(road_nmaps), blends, values, report)
    return blends, values, report


def with_nmapcalc(effect: str) -> str | None:
    """The effect with `.tsnmapcalc` where the base game puts it (before `.tgN` and `.rfx`)."""
    t = re.search(r"(\.tg\d)*\.rfx$", effect)
    return None if t is None or ".tsnmapcalc" in effect else effect[: t.start()] + ".tsnmapcalc" + effect[t.start():]


def wet_junctions(m: Merge, road_colours: set[str], blends: dict, values: dict, report: list[str]) -> None:
    """Every asphalt layer of a junction/yard/parking material without a normal map gets `reflection`
    JUNCTION_REFLECTION where it is 0 (WET_JUNCTIONS); with JUNCTION_NMAPS also the shared junction grain map (other
    layers the flat map, the effect `.tsnmapcalc`). Merged into `values` (RRR's carried values stay)."""
    effects, cands = set(), []
    for top in ("automat", "umatlib"):
        for p in sorted((m.base / top).rglob("*.mat")):
            t = p.read_text(encoding="utf-8", errors="ignore")
            e = re.search(r'^\s*effect\s*:\s*"([^"]+)"', t, re.M)
            if e:
                effects.add(e.group(1))
            cands.append((p.relative_to(m.base).as_posix(), p, t, e.group(1) if e else ""))
    nmap = None
    for rel, p, text, effect in cands:
        tex = mat_textures(text)
        if nmap_of(text) is not None or "texture_nmap_over" in tex:
            continue
        layers = [(layer, name, key) for layer, name, key in LAYERS if layer in tex]
        asphalt = [layer for layer, _, _ in layers
                   if (c := tex[layer].lstrip("/").lower()) in road_colours or ASPHALT.match(c)]
        if not asphalt:
            continue
        if rel.lower() in m.holders:
            report.append(f"skip  {rel}: shipped by {m.inputs(rel)} (wet junction)")
            continue
        new = with_nmapcalc(effect) if JUNCTION_NMAPS else effect
        if new is None or new not in effects:
            report.append(f"skip  {rel}: no base-game effect {new or effect + ' + .tsnmapcalc'} (wet junction)")
            continue
        if JUNCTION_NMAPS:
            nmap = nmap or junction_grain(m, blends)
        ops = dict(values[rel]["ops"]) if rel in values else {}
        for layer, _, key in layers:
            if layer not in asphalt:
                continue
            cur = ops.get(key)
            if cur is None:
                found = re.search(VALUE_LINE.format(key=key), text, re.M)
                cur = found.group(2) if found else None
            if cur is None:
                report.append(f"keep  {rel}: no {key} value on asphalt layer {layer} (wet junction)")
            elif float(canon(cur)) == 0:
                ops[key] = JUNCTION_REFLECTION
        if not JUNCTION_NMAPS:
            if ops:
                values[rel] = {"base": p, "ops": ops, "nmaps": {}, "effect": ""}
            continue
        nmaps = {name: nmap if layer in asphalt else FLAT_NMAP for layer, name, _ in layers}
        values[rel] = {"base": p, "ops": ops, "nmaps": nmaps, "effect": new}


def junction_grain(m: Merge, blends: dict) -> str:
    """Game path (.tobj) of the shared junction grain map, registered in `blends` (kind grain)."""
    w = m.winner(JUNCTION_GRAIN_SOURCE)
    dw = m.winner(tobj_dds(w[1]).lstrip("/")) if w else None
    if dw is None:
        sys.exit(f"{JUNCTION_GRAIN_SOURCE} or its .dds is missing (junction grain map)")
    blends[JUNCTION_GRAIN + ".dds"] = {"detail_src": dw[0], "detail": dw[1], "ruts": None, "grain": w[1],
                                       "via": JUNCTION_GRAIN_SOURCE}
    return "/" + JUNCTION_GRAIN + ".tobj"


def tobj_for(template: bytes, dds: str) -> bytes:
    """A .tobj like `template` (same type, filters, addressing) pointing at `dds`."""
    n = struct.unpack_from("<I", template, TOBJ_PATH_AT)[0]
    if len(template) != TOBJ_PATH_AT + 8 + n:
        raise ValueError("unexpected .tobj layout")
    path = dds.encode()
    return template[:TOBJ_PATH_AT] + struct.pack("<II", len(path), 0) + path


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


def rrr_ruts(path: pathlib.Path, size: tuple[int, int], target: str) -> np.ndarray:
    """RRR's rut map as tangent-space xy at `size`, minus its mean tilt (RUT_FLAT_MEAN), scaled by RUT_STRENGTH."""
    xy = load_xy(path, size)
    if RUT_FLAT_MEAN:
        xy = xy - xy.reshape(-1, 2).mean(0)
    return xy * rut_strength(target)


def mean_tilt(xy: np.ndarray) -> float:
    return float(np.degrees(np.arccos(np.clip(to_normal(xy)[..., 2], -1.0, 1.0))).mean())


def box_blur(a: np.ndarray, r: int) -> np.ndarray:
    """Wrapping (tiling) box blur of an (h, w, c) array, radius r."""
    for axis in (0, 1):
        n = a.shape[axis]
        idx = np.arange(n)
        c = np.cumsum(np.concatenate([np.take(a, idx[-r - 1:], axis), a, np.take(a, idx[:r], axis)], axis), axis)
        a = (np.take(c, np.arange(2 * r + 1, n + 2 * r + 1), axis) - np.take(c, np.arange(n), axis)) / (2 * r + 1)
    return a


def grain_floor(xy: np.ndarray) -> tuple[np.ndarray, float]:
    """(detail xy with its high-pass raised to GRAIN_MIN_TILT mean tilt, gain); unchanged (gain 1) if rough enough."""
    if mean_tilt(xy) >= GRAIN_MIN_TILT:
        return xy, 1.0
    low = box_blur(xy, GRAIN_RADIUS)
    high = xy - low
    lo, hi = 1.0, 12.0
    for _ in range(14):
        g = (lo + hi) / 2
        lo, hi = (g, hi) if mean_tilt(low + g * high) < GRAIN_MIN_TILT else (lo, g)
    g = (lo + hi) / 2
    return low + g * high, g


def fine_grain(xy: np.ndarray, tilt: float) -> tuple[np.ndarray, float]:
    """(the detail's fine grain alone, its GRAIN_RADIUS px high-pass, scaled to `tilt` mean tilt; gain)."""
    high = xy - box_blur(xy, GRAIN_RADIUS)
    lo, hi = 0.0, 12.0
    for _ in range(20):
        g = (lo + hi) / 2
        lo, hi = (g, hi) if mean_tilt(g * high) < tilt else (lo, g)
    g = (lo + hi) / 2
    return g * high, g


def legacy_ruts(w: int, h: int) -> np.ndarray:
    """World's wheel tracks for a legacy road texture (U across the road): two Gaussian troughs per lane strip,
    constant along V, as tangent-space xy."""
    u = (np.arange(w) + 0.5) / w
    height = np.zeros(w)
    for a, b in LEGACY_LANES:
        for c in LEGACY_TRACKS:
            centre, sigma = a + c * (b - a), LEGACY_TRACK_WIDTH * (b - a)
            height -= np.exp(-((u - centre) ** 2) / (2 * sigma ** 2))
    slope = np.gradient(height)
    x = -slope / np.abs(slope).max() * LEGACY_RUT_SLOPE
    xy = np.zeros((h, w, 2), np.float32)
    xy[..., 0] = x[None, :]
    return xy


def out_size(detail: pathlib.Path, ruts: pathlib.Path | None) -> tuple[int, int]:
    """(width, height) of a blend: the winner's, or RRR's rut map's where that is larger (KEEP_RUT_SIZE)."""
    dw, dh = struct.unpack("<II", detail.read_bytes()[12:20])[::-1]
    if not KEEP_RUT_SIZE or ruts is None:
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
        if b.get("grain"):
            w, h = out_size(b["detail"], None)
            rows.append([target, "grain", f"{b['detail_src']}:{sha(b['detail'])}", "world:fine-grain",
                         f"0@{w}x{h} grain={JUNCTION_GRAIN_TILT:g}"])
            rows.append([target[: -len(".dds")] + ".tobj", "tobj", f"{b['detail_src']}:{sha(b['grain'])}",
                         "/" + target, ""])
            continue
        ruts = m.rrr / b["ruts"] if b["ruts"] else None
        w, h = out_size(b["detail"], ruts)
        puddles = f"rrr:{sha(ruts)}" if ruts else "world:legacy-lanes"
        strength = (f"{rut_strength(target):g}{' flat-mean' if RUT_FLAT_MEAN else ''}" if ruts
                    else f"{LEGACY_RUT_SLOPE:g}")
        rows.append([target, "blend", f"{b['detail_src']}:{sha(b['detail'])}", puddles,
                     f"{strength}@{w}x{h} grain>={GRAIN_MIN_TILT:g}"])
    for rel, v in sorted(values.items()):
        rows.append([rel, "values", f"{v.get('src', 'base')}:{sha(v['base'])}",
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


def resolutions_text(m: Merge, blends: dict, values: dict) -> str:
    text = RESOLUTIONS.read_text(encoding="utf-8")
    head, _, _ = text.partition("\nresolutions:")
    doc = yaml.safe_load(text) or {}
    keep = [r for r in (doc.get("resolutions") or []) if not str(r.get("note", "")).startswith(NOTE)]
    ours = [{"path": t, "merged": f"overrides/{t}", "inputs": m.inputs(t),
             "note": (f"{NOTE}: {b['detail_src']}'s normal map blended with Realistic Rain Reflections' puddles"
                      if b["ruts"] else f"{NOTE}: {b['detail_src']}'s legacy road normal map with World's wheel tracks")}
            for t, b in sorted(blends.items()) if m.inputs(t) and not b.get("grain")]
    ours += [{"path": rel, "merged": f"overrides/{rel}", "inputs": m.inputs(rel),
              "note": f"{NOTE}: {v['src']}'s legacy road material, shininess {LEGACY_SHININESS}"}
             for rel, v in sorted(values.items()) if v.get("src", "base") != "base" and m.inputs(rel)]
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
    res = resolutions_text(m, blends, values)
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
        rut_map = m.rrr / b["ruts"] if b["ruts"] else None
        w, h = out_size(b["detail"], rut_map)
        if b.get("grain"):
            grain_xy, gain = fine_grain(load_xy(b["detail"], (w, h)), JUNCTION_GRAIN_TILT)
            data = encode_like(to_normal(grain_xy), template)
            tobj_rel = target[: -len(".dds")] + ".tobj"
            for rel, blob in ((target, data), (tobj_rel, tobj_for(b["grain"].read_bytes(), "/" + target))):
                dest = OVERRIDES / rel
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(blob)
                outs[rel] = hashlib.sha256(blob).hexdigest()
            print(f"[{i}/{len(blends)}] grain {target} ({b['detail_src']} {b['via']}, {w}x{h}, fine grain x{gain:.3f})")
            continue
        detail_xy, gain = grain_floor(load_xy(b["detail"], (w, h)))
        if rut_map:
            ruts, what = rrr_ruts(rut_map, (w, h), target), f"{rut_map.name} x{rut_strength(target):g}"
        else:
            ruts, what = legacy_ruts(w, h), "World's legacy lane tracks"
        data = encode_like(blend(to_normal(detail_xy), to_normal(ruts)), template)
        dest = OVERRIDES / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        outs[target] = hashlib.sha256(data).hexdigest()
        print(f"[{i}/{len(blends)}] blend {target} ({b['detail_src']}, {w}x{h}, grain x{gain:.2f}) + {what}")
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

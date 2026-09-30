#!/usr/bin/env python3
"""
Generates world/climate.yaml: a weather mix and night rain limits on Weather_3.9's climate (juninho-weather,
def/climate/default), as edits of the merged file (megapack `base_edits`; the path's winner is Weather's copy).

1. Weather mix (bad.sii only). Weather_3.9 makes about 81% of daytime rain heavy, and at night 9 of its 10 rain
variants are heavy with strong lightning. Each variant (skybox index) gets one class, chosen from its sky (fog and
cloudy skies -> light, the darkest storm skies with lightning everywhere -> storm), and in every profile:
  rain_intensity and rain_max_wetness are clamped into the class range (Weather's day curve is kept inside it),
  lightning_intensity is 0 outside the storm class and at least STORM_LIGHTNING_MIN inside it,
  weight[i] = the class share (DAY_SHARES, or NIGHT_SHARES at night) split evenly over the class's variants,
    scaled by WEIGHT_SCALE to whole numbers (the game parses weight as an integer).
The class of a variant is the same at every sun elevation, so a rain does not change type during the day.
With thunderstorm_probability 1.0 (world/environment.yaml) the storm share is set by the weights alone.

2. Night limits. Weather_3.9 makes night rain far foggier and wetter than vanilla (fog density up to 0.047 from 6.9 m, wetness
mostly 0.95), and its fair-weather climate adds drizzle variants with fog from 6.9 m. With night fog colours near
black, the far end and the edges of the headlight beam fade out: the beam looks shorter, narrower and darker.

For every sun profile at night (low_elevation <= NIGHT_MAX_ELEVATION) and every weather variant that rains
(rain_intensity > 0), each value is only ever made less severe:
  fog_density      lowered to FOG_DENSITY_MAX
  fog_offset       (distance where fog starts) raised to FOG_OFFSET_MIN
  rain_max_wetness lowered to WETNESS_MAX
Dry variants (including pure fog weather) and daytime/twilight profiles are left as Weather made them. The
starting values are about vanilla 1.61's night rain; tune them after play tests. The limits apply after the mix.

usage: python tools/night_climate.py [--check]    (--check: fail if world/climate.yaml would change)
"""
from __future__ import annotations

import argparse
import pathlib
import re
import struct
import sys

import yaml

ROOT = pathlib.Path(__file__).resolve().parent.parent
SKILL = pathlib.Path.home() / ".agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts"
sys.path.insert(0, str(SKILL))
from megapack import host_section  # noqa: E402
from siiedit import SiiFile  # noqa: E402

OUT = ROOT / "world" / "climate.yaml"
SOURCE = "juninho-weather"
FILES = ["def/climate/default/nice.sii", "def/climate/default/bad.sii"]

NIGHT_MAX_ELEVATION = -4.0   # sun at or below 4 degrees under the horizon
FOG_DENSITY_MAX = 0.0035     # vanilla night rain: ~0.0032-0.0037 (0.005 in dev.1-3; beam a little further)
FOG_OFFSET_MIN = 30.0        # vanilla night rain: 8.6-37.5 m, mostly 27.5-33 m (25 in dev.1-3)
WETNESS_MAX = 0.6            # vanilla night rain: 0.16-1.0, weighted average 0.53
INDEXED = re.compile(r"^(\w+)\[(\d+)\]$")

MIX_FILE = "def/climate/default/bad.sii"
# class: (rain_intensity range, rain_max_wetness range, variants). Variants by Weather_3.9's skies:
# 1 fog skies, 3 cloudy/partly clear, 7 brightest (daylight 1.7x the others) -> light;
# 5, 6 cloudy with little lightning -> medium; 0, 9 dark "bad" skies -> heavy;
# 2, 4, 8 darkest skies with lightning ~1.0 at every elevation -> storm.
CLASSES = {
    "light": ((0.15, 0.30), (0.20, 0.45), [1, 3, 7]),
    "medium": ((0.35, 0.55), (0.40, 0.60), [5, 6]),
    "heavy": ((0.70, 0.85), (0.60, 0.85), [0, 9]),
    "storm": ((0.90, 0.95), (0.80, 0.95), [2, 4, 8]),
}
DAY_SHARES = {"light": 40, "medium": 35, "heavy": 18, "storm": 7}     # % of rainy periods (user, 2026-09-30)
NIGHT_SHARES = {"light": 45, "medium": 35, "heavy": 15, "storm": 5}
STORM_LIGHTNING_MIN = 0.85
WEIGHT_SCALE = 6             # weights are integers: share * 6 / variants in class (classes have 2 or 3 variants)


def num(v: str) -> float:
    v = v.strip()
    return struct.unpack(">f", bytes.fromhex(v[1:]))[0] if v.startswith("&") else float(v)


def fmt(x: float) -> str:
    return f"{x:.6g}"


def source_dir() -> pathlib.Path:
    ref_root = pathlib.Path(host_section("Extracted Reference Root")["root"])
    src = yaml.safe_load((ROOT / "sources.yaml").read_text(encoding="utf-8"))["sources"]
    s = next(s for s in src if s["id"] == SOURCE)
    d = ref_root / "workshop" / str(s["workshop"]) / str(s["version"])
    if not d.is_dir():
        sys.exit(f"missing extraction {d} — run extract-reference first")
    return d


def arrays(sii: SiiFile, unit: str) -> dict[str, dict[int, str]]:
    out: dict[str, dict[int, str]] = {}
    for _, key, val in sii.units[unit].attrs:
        m = INDEXED.match(key)
        if m:
            out.setdefault(m.group(1), {})[int(m.group(2))] = val
    return out


def limits(src: pathlib.Path) -> tuple[dict, list[str]]:
    edits: dict = {}
    report: list[str] = []
    for rel in FILES:
        sii = SiiFile.read(src / rel)
        profiles = [u for u in sii.order if sii.units[u].type == "sun_profile"]
        # elevations are stored as floats such as -3.9999986 for -4
        night = {u for u in profiles if round(num(sii.values(u, "low_elevation")[0]), 3) <= NIGHT_MAX_ELEVATION}
        changed = 0
        for unit in profiles:
            a = arrays(sii, unit)
            vals = {k: {i: num(v) for i, v in a[k].items()} for k in
                    ("rain_intensity", "rain_max_wetness", "lightning_intensity", "weight", "fog_density", "fog_offset")}
            new = {k: dict(v) for k, v in vals.items()}
            if rel == MIX_FILE:
                mix(new, unit in night)
            if unit in night:
                for i, rain in new["rain_intensity"].items():
                    if rain <= 0:
                        continue
                    new["fog_density"][i] = min(new["fog_density"][i], FOG_DENSITY_MAX)
                    new["fog_offset"][i] = max(new["fog_offset"][i], FOG_OFFSET_MIN)
                    new["rain_max_wetness"][i] = min(new["rain_max_wetness"][i], WETNESS_MAX)
            ops = {f"{k}[{i}]": fmt(x) for k in new for i, x in sorted(new[k].items())
                   if fmt(x) != fmt(vals[k][i])}
            for key, val in ops.items():
                k, i = INDEXED.match(key).groups()
                if re.fullmatch(r"-?\d+", a[k][int(i)].strip()) and not re.fullmatch(r"-?\d+", val):
                    sys.exit(f"{rel} {unit} {key}: the game file has an integer, refusing to write {val}")
            if ops:
                edits.setdefault(rel, {})[unit] = {"set": ops}
                changed += len(ops)
        report.append(f"{rel}: {len(profiles)} profiles ({len(night)} night), {len(edits.get(rel, {}))} edited, "
                      f"{changed} values")
    return edits, report


def mix(v: dict[str, dict[int, float]], at_night: bool) -> None:
    """Weather mix on one bad-weather profile's variant values, in place (see the module docstring)."""
    shares = NIGHT_SHARES if at_night else DAY_SHARES
    listed = sorted(i for _, _, idx in CLASSES.values() for i in idx)
    if listed != sorted(v["weight"]):
        sys.exit(f"variant classes {listed} do not cover the profile's variants {sorted(v['weight'])}")
    for name, ((r_lo, r_hi), (w_lo, w_hi), idx) in CLASSES.items():
        for i in idx:
            v["rain_intensity"][i] = min(max(v["rain_intensity"][i], r_lo), r_hi)
            v["rain_max_wetness"][i] = min(max(v["rain_max_wetness"][i], w_lo), w_hi)
            v["lightning_intensity"][i] = (max(v["lightning_intensity"][i], STORM_LIGHTNING_MIN)
                                           if name == "storm" else 0.0)
            # the game reads weight as an integer ("7.5" fails the whole file, and rain then crashes the game)
            w = shares[name] * WEIGHT_SCALE / len(idx)
            if w != int(w):
                sys.exit(f"{name}: share {shares[name]} * {WEIGHT_SCALE} is not divisible by {len(idx)} variants")
            v["weight"][i] = int(w)


def render(edits: dict) -> str:
    head = (
        "# GENERATED by tools/night_climate.py — do not edit by hand; change the script and rerun it.\n"
        f"# Weather mix on bad.sii (% of rainy periods, light/medium/heavy/storm): day "
        f"{'/'.join(str(x) for x in DAY_SHARES.values())}, night {'/'.join(str(x) for x in NIGHT_SHARES.values())}.\n"
        f"# Night rain limits on Weather_3.9's climate (sun <= {NIGHT_MAX_ELEVATION} deg, raining variants only):\n"
        f"# fog_density <= {FOG_DENSITY_MAX}, fog_offset >= {FOG_OFFSET_MIN} m, rain_max_wetness <= {WETNESS_MAX}.\n")
    body = yaml.safe_dump({k: edits[k] for k in sorted(edits)}, sort_keys=False, allow_unicode=True, width=10_000)
    return head + body


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()
    edits, report = limits(source_dir())
    for r in report:
        print(r)
    text = render(edits)
    if args.check:
        same = OUT.is_file() and OUT.read_text(encoding="utf-8") == text
        print(f"{OUT.relative_to(ROOT)} {'up to date' if same else 'OUT OF DATE'}")
        return 0 if same else 1
    OUT.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

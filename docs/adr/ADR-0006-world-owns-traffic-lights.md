# ADR-0006: World owns the traffic lights: its own flash timing and the "Different lenses" textures, no add-on

- Status: accepted
- Date: 2026-10-29
- Amends: [ADR-0004](ADR-0004-world-base-data-fixes.md) decision 1 (who generates the timing) and
  [ADR-0005](ADR-0005-world-flashing-green-locators.md) decisions 2-3 (the TrafficLights add-on)

## Context

- Better Flares 4.9.1 (2026-10-19) keeps `unit/hookup/tr_light_flares.sii` byte-identical to 4.8, including the
  `flare.traffic.green.trans` unit World's locators hook up to (ADR-0005).
- Since World 1.3.0 the DriveDogs Better Flares Traffic Lights add-on had two jobs left: an empty
  `unit/hookup/tr_light_flares0.sii` that cancels the duplicate flare units of "Different lenses of traffic lights"
  (Workshop 2931835197), and `tools/generate_traffic_lights.py --world-edits`, which wrote World's
  `world/traffic_lights.yaml`. The add-on is deprecated (its ADR-0003, tag `deprecated-moved-to-world`).
- The user wants World independent of every Better Flares add-on and keeps using the lenses (2026-10-28).
- Different lenses 1.1 ships 20 country lens textures (`model/traffic_light/{city,city_uk,traffic_lights_<cc>,
  traffic_lights_v2_es}`, `.dds` + `.tobj`) and `unit/hookup/tr_light_flares0.sii`, which re-registers the 68 traffic
  flare units with its own glow. Loaded next to Better Flares, those units exist twice. Its package is `154.zip` at
  the Workshop item root, which `extract-reference` could not read.
- World ships 91 `model/traffic_light/*.pmg` (ADR-0005) and no texture there: no path collides. All 20 textures are
  used by base 1.61.1.9 materials (100 `.mat`); 47 of World's 91 timed models use one.

## Decision

1. **World generates its own flash timing.** `tools/traffic_light_timing.py` is the add-on's `--world-edits` half,
   reading the base through `ref_path`/`ref_fetch` like World's other tools: `FLASH_SECONDS` 3.0, models whose `.pmg`
   has exactly the four standard flare locators and no `state_transition` yet (108 units). It checks the base
   `flare.traffic.green.trans` unit still blinks in `green_trans` instead of reading Better Flares. The add-on's
   hookup half is dropped: World ships no hookup file.
2. **World merges Different lenses as textures only** (`sources.yaml` `tl-lenses`, layer 60). Its
   `tr_light_flares0.sii` is excluded: the glow stays the base game's, or Better Flares' when that is loaded, and no
   flare unit is defined twice.
3. **The TrafficLights add-on is not used with World any more.** Players remove it and disable 2931835197; World and
   Better Flares are enough.
4. `extract-reference` 2.2 reads Workshop archive packages (`<package>.zip`/`.scs` at the item root), so the lenses
   are an ordinary Workshop source that `megapack updates` follows.

## Consequences

- World alone: country lenses, the 3 s green flash and the night yellow blink with the base flares. World + Better
  Flares: the same with Better Flares' glow. The lens mod's own glow change is not carried.
- Loading 2931835197 next to World brings its duplicate flare units back (with Better Flares); the description says to
  disable it. The deprecated add-on is harmless but redundant; the description says to remove it.
- After a game update: rerun `traffic_light_timing.py`, then `traffic_light_locators.py` (README order). A lens
  update: `megapack updates` reports it, re-extract, relock.

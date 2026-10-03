# ADR-0003: World carries Busy Bus Stations' locators onto the base bus-stop models instead of merging the mod

- Status: accepted
- Date: 2026-10-03

## Context

- Busy Bus Stations (d-luX, Workshop 2893480838, version 1.00, last updated 2022-11-26) puts people at bus stops: sitting
  and standing men and women by day, at night and in rain, a parked coach (Opalin or Tourliner) and a lamp.
- It ships whole copies of 23 base-game bus-stop models (`prefab/bus_station/base_03/*`, the French and German stop
  templates) with its attachment points (locators) added, 36 materials, 6 textures and 4 definition files.
- It still loads in 1.61, but its models are 2022 re-exports. They put back the old shared road materials where 1.61
  gives each model its own, revert some geometry SCS changed since, and drop 1.61's (unused) cutscene locators in 6
  models. Its textures are the 1.61 images in the old, non-sRGB encoding. Every later SCS change to these models
  would also be undone.
- The mod's added locators use the same coordinates as the 1.61 models (identical bounding boxes, many parts
  vertex-exact), and none of World's other sources ship these models.

## Decision

1. **Carry the locators, not the models.** `tools/bus_stop_people.py` reads each of the mod's 23 models and adds its
   locators, part by part, to the 1.61 base model of the same path (`pmg.py` `with_locators`, megapack 0.8). Base
   geometry, materials and existing locators stay. Output goes to `overrides/` (git-ignored: 6.5 MB of base-game
   models, regenerated after a clone) with a manifest `world/bus_stop_people.tsv`, and `--check` covers both.
2. **Definitions as new files.** The mod's 4 `.sii` files (mover groups, mover hookups, parked coach, lamp) are
   copied unchanged to `world/units/`, keeping their unit names. `harvest_brands.py` now owns only
   `world/units/def/vehicle/`.
3. **Never merged, always credited:** a `references:` entry (`busy-bus-stations`, 1.00) lists the mod in the
   description and makes `megapack updates` report a new version. Its textures and materials are not used.
4. **Lamp locators stay where the mod put them** (in the stop's collision part in most models). In game they
   draw and light at night.

## Consequences

- People, the parked coach and the lamp appear at the 18 places 1.61 uses these models (UK, Poland, France,
  Hungary, Czechia, Slovakia; none in the Netherlands). Seen in game on 1.1.0-dev.1 (2026-10-03): people at the
  Swansea-area stops, lamp at night, no errors in the log.
- After a game update: extract the new base and rerun the tool. A model or part the base no longer has is an error,
  and new SCS geometry is kept automatically.
- After a mod update: extract the new version, set `MOD_VERSION`, rerun. The tool exits if the mod starts shipping a
  base or source definition file (those would need edits, not copies).
- Other bus-stop prefabs (e.g. city bus terminals) get nothing: the mod only covers these 23 models.

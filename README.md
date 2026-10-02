# DriveDogs: World

ETS2 mod for the world around the road, built as a local **megapack** with the `megapack` skill of the
`ets2-mod-developer` agent profile. This repo holds only configuration and tools. The mod is built from the
extracted base game, subscribed Workshop items and one local archive. It is never redistributed.

Current content (v1.1.0, ETS2 1.61):

- **Graphics** from Juninho944 (Weather_3.9, Asphalt_improved, grass_4.0_lite, tree_improved_4k), DIOX (Beautiful
  Nature) and Darkcaptain (Realistic Rain), in the maintainer's load order.
- **Water, lightning and thunder** from Kass (Realistic Rain & Water & Thunder Sounds).
- **Wet roads**: Grimes' Realistic Rain Reflections puddles blended into the winning road normal maps, and its
  wet reflections on sidewalks, tiles, concrete and junctions.
- **Road signs and markings** from DBM Road Signs & Markings 4K; **real company and gas station brands** from Real
  companies & gas stations (MLH82, 4of25).
- **Weather and time**: a rain mix of mostly light and medium rain, lighter fog at night and at dawn/dusk so
  headlights reach, and a fixed date (27 September) for natural day and night.
- **People at bus stops** from d-luX's Busy Bus Stations: its people, parked bus and lamp placed on the 1.61
  bus-stop models (not its 2022 copies of them).
- **Trains**: Realistic Train Lengths and Cip's Real Train Sounds, rebuilt on the 1.61 game files.

Every game setting these mods change is carried as an edit of the current game files, never as an old whole copy,
so what a game update adds keeps working. Decisions: [ADR-0001](docs/adr/ADR-0001-world-megapack.md) (megapack,
trains), [ADR-0002](docs/adr/ADR-0002-world-graphics.md) (graphics, weather, brands).

## Install

1. Copy `output/local/drivedog_world_v<version>.scs` (one archive, ~7 GB) to `Documents/Euro Truck Simulator 2/mod/`.
2. In the mod manager, place it **above** Sound Fixes Pack (optional) and any other train sound or length mod.
3. Disable the mods it contains (Workshop subscriptions included): Weather_3.9, Asphalt_improved, grass_4.0_lite,
   tree_improved_4k, Beautiful Nature, Beautiful Water, Realistic Rain, Realistic Rain Reflections, Realistic Rain &
   Water & Thunder Sounds, DBM Road Signs & Markings 4K, Real companies & gas stations, Busy Bus Stations,
   Realistic Train Lengths, Real Train Sounds ETS2, and any day/night or date mod (e.g. Workshop 1061306287).

Sound Fixes Pack and Better Flares stay separate mods and work with World.

## Build

Requires Python 3.10+ with the megapack skill's `scripts/requirements.txt`, Pillow and numpy, `scs_packer` on
`PATH`, the base game extracted at the version in `megapack.yaml`, every Workshop source in `sources.yaml` extracted
(`extract-reference`, category `workshop`, at the listed version), and Realistic Rain Reflections Standalone v1.4
(Grimes, not on the Workshop) unzipped to `<extracted root>/local/rain-reflections/1.4/`.

```bash
python tools/harvest_edits.py        # trains -> world/edits.yaml
python tools/harvest_graphics.py     # graphics sources' game config -> world/graphics.yaml
python tools/harvest_brands.py       # Real companies & gas stations' names/paint jobs -> world/brands.yaml, world/units/
python tools/night_climate.py        # rain mix + night and dawn/dusk rain limits -> world/climate.yaml
python tools/rain_reflections.py     # puddle normal maps + reflection values -> overrides/ (after a clone too)
python tools/bus_stop_people.py      # bus-stop models with Workshop 2893480838's people -> overrides/ (after a clone too)
python tools/generate_cover.py
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py lock
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py check --strict
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py build
```

Each tool's `--check` fails when its output no longer matches its inputs. `world/environment.yaml` (date, storm
chance) is hand-written. The blended road normal maps and the bus-stop models in `overrides/` are git-ignored:
`rain_reflections.py` and `bus_stop_people.py` regenerate them.

## Updating

| Event | What to do |
|---|---|
| Game update | Extract the new base, set `base_game.version`, rerun every tool, bump the version, rebuild. Tools and `megapack check` fail loudly on units, files or looks that moved. |
| Source update (Steam re-sync) | `megapack updates` reports it. Re-extract it at the new version, set the version in `sources.yaml`, `megapack lock` (stale `resolutions.yaml` entries need review), rerun the tools, rebuild. |
| Rain Reflections update | Unzip it to a new `local/rain-reflections/<version>/`, set `RRR_VERSION` in `tools/rain_reflections.py`, rerun it, rebuild. |
| Bus-stop people (2893480838) update | Extract it with `extract-reference` to `workshop/2893480838/<version>/`, set `MOD_VERSION` in `tools/bus_stop_people.py`, rerun it, compare its definitions with `world/units/`, rebuild. |
| Sound Fixes Pack / Better Flares update | Nothing. World does not use their files. |

## Layout

| Path | Purpose |
|---|---|
| `megapack.yaml` | package identity, base game version, base-edit files, `references:` (Realistic Train Lengths, Busy Bus Stations), one-archive cap |
| `sources.yaml` | the 10 merged sources: layers, overrides, excludes |
| `resolutions.yaml` | per-path collision decisions (partly written by `rain_reflections.py`) |
| `world/*.yaml` | base-game edits: generated by the tools, except `environment.yaml` |
| `world/units/` | new game definition files (`harvest_brands.py`) |
| `overrides/` | World's own files: rain streak material, edited materials and blended road normal maps (`rain_reflections.py`), bus-stop models (`bus_stop_people.py`) |
| `tools/` | the generators above and `generate_cover.py` |
| `src/` | manifest and description templates, cover |
| `lock/` | generated source hashes and collision report |
| `docs/adr/` | decision records |

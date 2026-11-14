# DriveDogs: World

ETS2 mod for the world around the road, built as a local **megapack** with the `megapack` skill of the
`scs-mod-developer` agent profile. This repo holds only configuration and tools. The mod is built from the
extracted base game, subscribed Workshop items and one local archive. It is never redistributed.

Current content (v1.6.0, ETS2 1.62.1.0, checked on 1.62.3.3):

- **Graphics** from Juninho944 (Weather_3.9, Asphalt_improved, grass_4.0_lite, tree_improved_4k), DIOX (Beautiful
  Nature), Darkcaptain (Realistic Rain) and DBM (Vegetation, Terrain Textures, Road Textures, Guard Rails 4K, World &
  Buildings HD; above Juninho944's and DIOX's where they overlap), in the maintainer's load order. DBM's scanned road
  colours sit on Asphalt_improved's crack and joint relief.
- **Water** from DBM Water (lake waves, foam, shores, beaches) and Kass (rivers, distant water); **lightning and
  thunder** from Kass (Realistic Rain & Water & Thunder Sounds).
- **Wet roads**: Grimes' Realistic Rain Reflections wheel tracks blended into the winning road normal maps and
  junctions (World's own on the older roads, UK junctions and yards), a rough wet grain on every asphalt, its wet
  reflections on sidewalks, tiles and concrete, and a softer sky mirror so the asphalt shows through. Needs the game's rain reflections and reflection quality set high.
- **Road signs and markings** from DBM Road Signs & Markings 4K; **real company and gas station brands** from Real
  companies & gas stations (MLH82, 4of25), its pre-1.62 gas-station models given 1.62's looks and price boards.
- **Weather and time**: a rain mix of mostly light and medium rain, lighter rain fog at night so headlights reach and
  by day and at dawn/dusk so the road ahead stays in sight, a brighter view in dawn and dusk rain so the headlights
  show, and a fixed date (27 September) for natural day and night.
- **People at bus stops** from d-luX's Busy Bus Stations: its people, parked bus and lamp placed on the 1.62
  bus-stop models (not its 2022 copies of them).
- **Trains**: Realistic Train Lengths and Cip's Real Train Sounds, rebuilt on the 1.62 game files.
- **Flashing green**: the last 3 s of green on 108 standard traffic-light models become the engine's `green_trans`
  state, and their 91 models get a `flare.traffic.green.trans` locator on every green lens, built like the base game's
  own flashing-green models. World owns this timing because the engine looks semaphore models up by unit id, so it
  needs whole copies of `semaphore_model*.sii`, which World already ships. Night sleep mode keeps its blinking yellow.
- **Traffic-light lenses** from sasha19990309's Different lenses of traffic lights: country lens textures (their
  textures only; the glow stays the game's or Better Flares').

Every game setting these mods change is carried as an edit of the current game files, never as an old whole copy,
so what a game update adds keeps working. Decisions: [ADR-0001](docs/adr/ADR-0001-world-megapack.md) (megapack,
trains), [ADR-0002](docs/adr/ADR-0002-world-graphics.md) (graphics, weather, brands),
[ADR-0003](docs/adr/ADR-0003-world-bus-stop-people.md) (bus-stop people),
[ADR-0004](docs/adr/ADR-0004-world-base-data-fixes.md) (flashing-green timing, sign definitions, base-game data fixes),
[ADR-0005](docs/adr/ADR-0005-world-flashing-green-locators.md) (flashing-green locators, night yellow blink),
[ADR-0006](docs/adr/ADR-0006-world-owns-traffic-lights.md) (flash timing and lenses in World, no add-on).

## Install

1. Copy `output/local/drivedog_world_v<version>.scs` (one archive, ~16 GB) to `Documents/Euro Truck Simulator 2/mod/`.
2. In the mod manager, place it **above** Sound Fixes Pack (optional) and any other train sound or length mod.
3. Disable the mods it contains (Workshop subscriptions included): Weather_3.9, Asphalt_improved, grass_4.0_lite,
   tree_improved_4k, Beautiful Nature, Beautiful Water, Realistic Rain, Realistic Rain Reflections, Realistic Rain &
   Water & Thunder Sounds, DBM Road Signs & Markings 4K, DBM Vegetation, DBM Terrain Textures, DBM Guard Rails 4K,
   DBM World & Buildings HD, DBM Water, DBM Road Textures, Real companies & gas stations, Busy Bus Stations, Realistic Train Lengths,
   Real Train Sounds ETS2, Different lenses of traffic lights (2931835197), and any day/night or date mod (e.g.
   Workshop 1061306287).
4. Remove the DriveDogs Better Flares Traffic Lights add-on (`BetterFlaresAddOns/TrafficLights`, deprecated): World
   carries everything it did.

Sound Fixes Pack and Better Flares stay separate mods and work with World.

The lenses, the flash and the night yellow blink work on their own and take Better Flares' glow when it is loaded.

## Build

Requires Python 3.10+ with the megapack skill's `scripts/requirements.txt`, Pillow and numpy, `scs_packer` on
`PATH`, the base game extracted at the version in `megapack.yaml`, every Workshop source in `sources.yaml` extracted
(`extract-reference`, category `workshop`, at the listed version), and Realistic Rain Reflections Standalone v1.4
(Grimes, not on the Workshop) unzipped to `<extracted root>/local/rain-reflections/1.4/`. Build with megapack 0.14
or later: older versions leave out of the archive every image whose texture definition (`.tobj`) is the base game's,
among them four of the blended road normal maps (`megapack check` reports `base-game .tobj added` for them).

```bash
python tools/harvest_edits.py        # trains -> world/edits.yaml
python tools/harvest_graphics.py     # graphics sources' game config -> world/graphics.yaml
python tools/harvest_brands.py       # Real companies & gas stations' names/paint jobs -> world/brands.yaml, world/units/
python tools/night_climate.py        # rain mix + night and dawn/dusk rain limits -> world/climate.yaml
python tools/rain_reflections.py     # puddle normal maps + reflection values -> overrides/ (after a clone too)
python tools/bus_stop_people.py      # bus-stop models with Workshop 2893480838's people -> overrides/ (after a clone too)
python tools/traffic_light_timing.py    # flashing-green timing on the standard traffic lights -> world/traffic_lights.yaml
python tools/traffic_light_locators.py  # flashing-green locators on the timed traffic-light models -> overrides/ (after a clone too; after traffic_lights.yaml)
python tools/sign_lods.py            # instanced base signs without their unused LODs -> world/signs.yaml
python tools/base_material_fixes.py  # base materials with moved texture paths corrected -> overrides/automat/ (after rain_reflections.py)
python tools/generate_cover.py
python ~/.agent-brains/profiles/scs-mod-developer/skills/megapack/scripts/megapack.py lock
python tools/sign_frames.py          # base sign frames scaled to the winning texture -> world/sign_frames.yaml (after lock)
python tools/model_variants.py      # source models older than the base: missing looks/variants added -> overrides/ (after lock; after a clone too)
python tools/check_sign_defs.py      # sign atlas/frame pixel coords match the textures that win (after lock)
python tools/check_model_pairs.py    # every shipped .pmd fits the .pmg that wins (materials, parts) (after lock)
python ~/.agent-brains/profiles/scs-mod-developer/skills/megapack/scripts/megapack.py check --strict
python ~/.agent-brains/profiles/scs-mod-developer/skills/megapack/scripts/megapack.py build
```

Each tool's `--check` fails when its output no longer matches its inputs. `world/environment.yaml` (date, storm
chance) is hand-written. The blended road normal maps, the bus-stop models, the traffic-light models and the
patched source models in `overrides/` are git-ignored: `rain_reflections.py`, `bus_stop_people.py`,
`traffic_light_locators.py` and `model_variants.py` regenerate them.

## Updating

| Event | What to do |
|---|---|
| Game update | Extract the new base, set `base_game.version`, rerun every tool in the order above, bump the version, rebuild. Tools and `megapack check` fail loudly on units, files or looks that moved (`base_material_fixes.py` also when SCS fixed a path itself: drop that entry). `check_model_pairs.py` fails on a source .pmd left over from the old game over the new game's .pmg (it crashes the game where that model is drawn): exclude that file, or take the source's update. |
| Source update (Steam re-sync) | `megapack updates` reports it. Re-extract it at the new version, set the version in `sources.yaml`, `megapack lock` (stale `resolutions.yaml` entries need review), rerun the tools, `check_sign_defs.py` and `check_model_pairs.py`, rebuild. For Real companies, `model_variants.py` then reports patches the update made unnecessary (`no longer needed`: remove them from `world/model_variants.yaml`) and fails on new mismatches; revisit its look choices. |
| Rain Reflections update | Unzip it to a new `local/rain-reflections/<version>/`, set `RRR_VERSION` in `tools/rain_reflections.py`, rerun it, rebuild. |
| Bus-stop people (2893480838) update | Extract it with `extract-reference` to `workshop/2893480838/<version>/`, set `MOD_VERSION` in `tools/bus_stop_people.py`, rerun it, compare its definitions with `world/units/`, rebuild. |
| Sound Fixes Pack / Better Flares update | Nothing. World does not use their files. |
| Flash length or targets change | Set `FLASH_SECONDS` (or the model rules) in `tools/traffic_light_timing.py`, rerun it, then `tools/traffic_light_locators.py`, rebuild. |

## Layout

| Path | Purpose |
|---|---|
| `megapack.yaml` | package identity, base game version, base-edit files, `references:` (Realistic Train Lengths, Busy Bus Stations), one-archive cap |
| `sources.yaml` | the 17 merged sources: layers, overrides, excludes (DBM's sign atlas/frame definitions must match the textures that win, see its comment) |
| `resolutions.yaml` | per-path collision decisions (partly written by `rain_reflections.py` and `model_variants.py`) |
| `world/*.yaml` | base-game edits: generated by the tools, except `environment.yaml` |
| `world/units/` | new game definition files (`harvest_brands.py`) |
| `overrides/` | World's own files: rain streak material, edited materials and blended road normal maps (`rain_reflections.py`), bus-stop models (`bus_stop_people.py`), traffic-light models (`traffic_light_locators.py`), source models given the base game's newer looks/variants (`model_variants.py`, `world/model_variants.yaml`) |
| `tools/` | the generators above, `check_sign_defs.py` and `check_model_pairs.py` (read-only) and `generate_cover.py`; `overrides/automat/` is shared by `rain_reflections.py` and `base_material_fixes.py` (manifests `world/*.tsv`) |
| `src/` | manifest and description templates, cover |
| `lock/` | generated source hashes and collision report |
| `docs/adr/` | decision records |

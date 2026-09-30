# DriveDogs: World

ETS2 mod for the world around the road, built as a local **megapack** with the `megapack` skill of the
`ets2-mod-developer` agent profile. This repo holds only configuration and tools. The mod is built from the
extracted base game and from subscribed Workshop items.

Current content (v0.1.0, ETS2 1.61):

- **Train lengths** from *Realistic Train Lengths* (Workshop 3209674677): longer `trailer_chains` per country and
  locomotive, longer `lod_dist`, and the train speeds, power and weights it carries (from Sound Fixes Pack 26.66).
- **Train and crossing sounds** from *Real Train Sounds ETS2* by Cip (Workshop 2439106226): its FMOD banks and
  generic train soundrefs, its per-train engine, wheel and horn sounds, lower speeds for M62, CC47E, Class 334
  and CME3, and per-country level-crossing sounds.

Both mods ship whole copies of game files made for older game versions. Realistic Train Lengths' copies lack
the trains 1.61 added, which causes `dangling pointer (to 'traffic.frt.nl')`. World carries their changes as
edits onto the current game files instead (see [ADR-0001](docs/adr/ADR-0001-world-megapack.md)).

## Install

1. Copy `output/local/drivedog_world_v<version>.scs` to `Documents/Euro Truck Simulator 2/mod/`.
2. In the mod manager, place it **above** Sound Fixes Pack (optional) and any other train sound or length mod.
3. Remove *Realistic Train Lengths* and *Real Train Sounds ETS2* from the load order: both are built in.

World replaces Sound Fixes Pack's train sound settings (train `.sui` files, generic train soundrefs,
`semaphore_model.sii` and `.dlc_balkan_e.sii`). The rest of Sound Fixes Pack is unaffected.

## Build

Requires Python 3.10+ with the megapack skill's `scripts/requirements.txt`, Pillow and numpy, `scs_packer` on
`PATH`, the base game extracted at the version in `megapack.yaml`, every Workshop source in `sources.yaml` extracted
(`extract-reference`, category `workshop`, at the listed version), and Realistic Rain Reflections Standalone v1.4
(Grimes, not on the Workshop) unzipped to `<extracted root>/local/rain-reflections/1.4/`.

```bash
python tools/harvest_edits.py        # trains -> world/edits.yaml
python tools/harvest_graphics.py     # graphics sources' game config -> world/graphics.yaml
python tools/night_climate.py        # weather mix + night rain limits -> world/climate.yaml
python tools/rain_reflections.py     # puddle normal maps + reflection values -> overrides/ (after a clone too)
python tools/whole_files.py          # records the base files that whole copies (Realistic Rain spray) replace
python tools/generate_cover.py
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py lock
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py check --strict
python ~/.agent-brains/profiles/ets2-mod-developer/skills/megapack/scripts/megapack.py build
```

Each tool's `--check` fails when its output no longer matches its inputs. `world/environment.yaml` (date, storm
chance) is hand-written. The blended road normal maps in `overrides/` are git-ignored: `rain_reflections.py`
regenerates them.

## Updating

| Event | What to do |
|---|---|
| Game update | Extract the new base, set `base_game.version`, rerun the harvest, bump the version, rebuild. The harvest fails loudly if a train unit or trailer it uses is gone. |
| Cip update | `megapack updates` reports it. Extract the new version, set its version in `sources.yaml`, then harvest, lock and build. Optional: nothing breaks if you skip it. |
| Sound Fixes Pack update | Nothing. World does not use its files. |

## Layout

| Path | Purpose |
|---|---|
| `megapack.yaml` | package identity, base game version, `references:` (Realistic Train Lengths) |
| `sources.yaml` | merged sources: Cip's `sound/` only |
| `world/edits.yaml` | generated base-game edits (do not edit by hand) |
| `tools/harvest_edits.py` | generates `world/edits.yaml` from the two Workshop mods and validates it |
| `tools/generate_cover.py` | renders `src/cover.jpg` with the version badge |
| `src/` | manifest and description templates, cover |
| `overrides/` | own files laid over the merge: `tools/rain_reflections.py` output (edited materials, blended road normal maps) |
| `lock/` | generated source hashes and collision report |

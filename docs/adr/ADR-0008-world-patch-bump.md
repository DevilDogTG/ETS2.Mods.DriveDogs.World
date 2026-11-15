# ADR-0008: World carries Daniel's asphalt-patch bump, lowered, on the base game's patch models

- Status: accepted
- Date: 2026-11-15

## Context

- **The feature.** Daniel's Random Events Mod 1.6.3 (Daniel, https://forum.scssoft.com/viewtopic.php?t=265242)
  ships the base game's three asphalt-patch decal models (`model2/props/street/newapsh_decal`, `_1`, `_2`) with
  collision parts named `startcol`, `centercol` and `endcol`. The wheels feel the patch: a step on and a drop off.
  The game's own patches are flat decals with no collision.
- **Where it was.** The DriveDogs AiTraffic megapack carried those six files with Daniel's events. The maintainer
  decided (2026-11-15) that the bump is a road-surface feature: it belongs in World and works without the traffic
  pack. AiTraffic 1.7.2 stops shipping them once World does. Without the models, Daniel's patch events still spawn
  and look the same, just flat.
- **Too strong.** Daniel's collision plates sit at the decal's own height: 20 mm (`newapsh_decal`, `_2`) and 13.4 mm
  (`_1`). That feels a little too strong on modern trucks; `drivedog_physics` also lowers force-feedback bump
  thresholds. For scale: the base motorway edge rumble strip is 5 mm. In a playtest of two lowered test packages
  (`half`: 10 / 6.5 mm, `third`: 6.5 / 4.5 mm) the maintainer picked `half`.
- **Daniel's files.** They are a 2024 re-export of the base models: the same triangles (within 1e-4 m), but not the
  same bytes, with his own two materials (`automat/35/355ab1aa102fd352.mat`, `automat/01/019b8ecdd57d9562.mat`:
  brighter, a decal effect). Each collision part is a visible copy of the patch, using the visible material, so the
  patch is drawn twice. No material sets a substance.

## Decision

1. **Built from the base game.** `tools/patch_bump.py` reads the current base game's three models and keeps every
   base part, piece and vertex byte for byte. It appends one collision part per visible part, named as Daniel named
   them (`<part>col`), holding that part's triangles flat at the chosen height. Outputs go to
   `overrides/model2/props/street/` (git-ignored, regenerated after a clone), with manifest `world/patch_bump.tsv`
   and `--check`. It fails if a game update changes the patch models' parts or makes them non-flat.
2. **Heights from the playtest.** 10 mm on `newapsh_decal` and `_2`, 6.5 mm on `_1`. The visible patch stays at
   the base game's height.
3. **The collision copy is invisible.** The collision pieces use SCS's own road collision material
   `/automat/04/045631c4dd16cdaf.mat` (`eut2.none`, substance `road`, the material of every road template's `coll`
   part), in the base game's collision vertex format (position, normal, colour; no uv). The patch is drawn once,
   and the wheels meet the road's own surface on top of the step.
4. **Daniel's materials are not carried.** The visible patches keep the base game's materials, so they look like
   the game's own. World ships no material file for this feature.
5. **Credit.** Daniel's Random Events Mod is credited in the README and the mod description, with the forum link.

## Consequences

- The bump works with or without the AiTraffic megapack or Daniel's mod. Daniel's patch events spawn the same
  models, so his events get World's lower bump too.
- Load order: World must sit above Daniel's Random Events when that mod is loaded on its own (it ships the 20 / 13
  mm copies). The AiTraffic megapack drops its copies in 1.7.2.
- Changes against the tested `half` package: the collision copy is no longer drawn, and its substance is `road`
  (Daniel's had none). The plate shapes and heights are the same. The playtest of 1.7.0-dev.1 (2026-11-15, ETS2
  1.62.3.3, with AiTraffic 1.7.2-dev.1 and no test package) confirmed that the invisible plates collide and feel
  like `half`, with no log line from the patch models or their materials.
- If the bump still feels too sharp, the next lever is a slope at the plate's edges instead of a step.

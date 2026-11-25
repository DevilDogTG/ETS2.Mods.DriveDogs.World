# ADR-0001: World is a megapack; train content is edits on the base game

- Status: accepted
- Date: 2026-09-28
- Amended: 2026-11-25 (1.8.0: decision 6 makes SFP a required companion below World; it supersedes "SFP is
  optional" in decision 2)

## Context

- DriveDogs World is the family's world/environment mod. Its first content replaces two Workshop mods:
  - *Realistic Train Lengths* (3209674677)
  - *Real Train Sounds ETS2* by Cip (2439106226)
- **Realistic Train Lengths** is 55 whole-file copies of an older Sound Fixes Pack (SFP, 648591060) version of
  the train `.sui` files, with longer `trailer_chains` and `lod_dist`. The copies predate 1.61:
  - They lack `traffic.frt.nl`, `train_car.frt.nl.*` and `train_car.regiode.{be,lu}_*`.
  - The game logs `dangling pointer (to 'traffic.frt.nl')` from `def/country/netherlands/traffic.sii`.
  - It also `@include`s SFP files, so it only works with SFP loaded.
- **Cip's mod** ships FMOD banks and soundrefs, plus whole copies of 13 train `.sui` files and
  `semaphore_model.sii`:
  - The Class 334 copy lacks vanilla `lod_dist`.
  - Two of its files use pre-1.61 names that the game never loads.
- A same-path file replaces the whole file, so any mod that changes a train `.sui` has to ship all of it. It
  therefore goes stale whenever the copy it was built on changes.

## Decision

1. **World is a `megapack` repo** (the AiTrafficPack pattern). It is local only, and third-party mods are
   credited in its description.
2. **Train content is built on the current base game, not on SFP.**
   - Considered: building on SFP's current train files, which keeps SFP's per-train sounds.
   - Rejected because SFP updates often. Every SFP change to those files would need a World rebuild, and it
     needed megapack changes (reading `.scs` Workshop packages, an `only:` filter, dropping `@include`
     lines).
   - Result: World rebuilds only on game updates. SFP is optional and loads below World, so its train sound
     settings are replaced and the rest of SFP is untouched.
3. **Cip is a source for `sound/` only.**
   - Its banks and generic soundrefs are merged, and win over SFP's when SFP loads below World.
   - Its `.sui`/`.sii` changes are carried as `base_edits`: `sound_move`, `sound_horn`, `max_speed` and the
     crossing `sounds[]`.
   - Its DV12 and E.405 files are carried onto their current 1.61 names.
   - Where it repeats a scalar `sound_move`, the last line is kept, as the game would do.
4. **Realistic Train Lengths is a `reference`.**
   - Carried: its `trailer_chains[]` and `lod_dist[]`, plus the physics values it contains (`max_speed`,
     `engine_power`, `vehicle_mass`, `cargo_mass`, all equal to SFP 26.66's). These are the values players had
     with that mod.
   - Not carried: its SFP sound lines and includes; removals of vanilla attributes (stale); a spawn condition
     whose unit only SFP defines.
   - On units both mods change, Cip's `max_speed` wins.
   - SFP is credited in the description for the physics values.
5. **Edits are generated, never hand-typed.**
   - `tools/harvest_edits.py` reads both mods and the base game and writes `world/edits.yaml`.
   - It fails if a chain token names no base-game trailer or trailer type, or if a sound event is not in the
     Cip bank it names.
   - Only units that exist in the base game are edited. Units the game adds later keep vanilla values.
6. **SFP is required below World, and World takes picked SFP lines (1.8.0).**
   - Why: World ships whole copies of 56 train/crossing definition files, so SFP's copies of them never load.
     The maintainer reviewed what that hides (brains report `2026-11-24-sfp-conflicts`) and picks what World
     takes, one item at a time. Train and crossing sounds stay Cip's (a build that switched them to SFP's,
     1.8.0-dev.1, was dropped before playtesting).
   - Picks today: the garage-door `sounds[]` on `tr_sem_mdl.garage_sc`, `g_exp_door`, `g_mid_door` and
     `g_poor_door` in `semaphore_model.sii` (World ships that file for its traffic lights and crossings).
   - How: `harvest_edits.py` `SFP_PICKS` lists (file, unit pattern, keys). The harvest applies SFP's values with
     its `@include`s inlined, after Lengths' and Cip's. A key SFP drops is unset. It fails on a pick that matches
     no unit, on a unit another `base_edits` file edits, and on a sound that does not resolve
     (soundref -> bank -> event) in SFP or the base game.
   - World ships none of SFP's files: the picked lines point at SFP's own sound files, so SFP must load below
     World. SFP is a `megapack.yaml` reference (`package: sound`, its 1.62 archive) so `megapack updates`
     reports new versions.
   - Considered: shipping SFP's banks in World so SFP stays optional. Rejected for now: World's copy would go
     stale and override SFP's newer one when SFP updates.

## Consequences

- A game update means extracting the new base, harvesting and rebuilding. Removed or renamed units fail the
  harvest or the build loudly instead of being dropped silently.
- SFP users hear Cip's train sounds instead of SFP's.
- Since 1.8.0 (decision 6) SFP is needed below World: without it the picked sounds (garage doors) are silent. An
  SFP update needs a re-harvest only when it renames or drops a picked sound; the harvest fails loudly then.
- Switching to an SFP-based build later only adds SFP as a source and changes the harvest base. The repo
  layout stays the same.
- Units only in newer game versions (e.g. 1.61's NL Flirt) get vanilla lengths until the harvest rules give
  them lengths of their own.

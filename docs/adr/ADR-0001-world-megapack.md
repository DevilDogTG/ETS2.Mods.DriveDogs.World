# ADR-0001: World is a megapack; train content is edits on the base game

- Status: accepted
- Date: 2026-09-28

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

## Consequences

- A game update means extracting the new base, harvesting and rebuilding. Removed or renamed units fail the
  harvest or the build loudly instead of being dropped silently.
- SFP updates never require a World rebuild. SFP users hear Cip's train sounds instead of SFP's.
- Switching to an SFP-based build later only adds SFP as a source and changes the harvest base. The repo
  layout stays the same.
- Units only in newer game versions (e.g. 1.61's NL Flirt) get vanilla lengths until the harvest rules give
  them lengths of their own.

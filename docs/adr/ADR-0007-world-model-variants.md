# ADR-0007: World adds the base game's newer looks and variants to source models older than the game

- Status: accepted
- Date: 2026-11-07

## Context

- **The error.** On ETS2 1.62.1.0, World 1.5.0-dev.5 logged `Unknown variant name 'price2' on model
  '/model2/gas_station/gas_price_primel_01_gr.pmd'`. It also logged it for the lod1 `.pmd` and the `.pmc` (playtest
  2026-11-07, Greece). For a name the winning model lacks, the game draws the model's first variant or look and
  logs an error.
- **Why.** Real companies & gas stations 2.04.13 (Workshop 2933731468) supports ETS2 1.48 to 1.61, and it is the
  latest release. It ships its own Primel and Pegi price signs, and its own Greek modern gas-station prefabs. For
  these, ETS2 1.62 added:
  - the Primel variants `price2` and `price3`
  - a `bi` look (Bosnia and Herzegovina)
  - the prefab looks `primel_bi` and `pegi_bi`
- **Why not just exclude them.** Letting 1.62's models win would replace Real companies' real brands on those signs
  with SCS's Primel and Pegi.
- **The `.pmc` files.** Real companies' collision files for these signs are byte copies of the older base-game
  collision. 1.62's copies have the same shape plus the new names.

## Decision

1. **Patch the source's models, keep everything else.** `tools/model_variants.py` writes a copy of each listed
   source `.pmd` (PMD v4) to `overrides/`, with the missing names added:
   - a variant copies the part attribute values (visibility) of a named source variant
   - a look copies the material row of a named source look
   
   Geometry (`.pmg`), materials and the source's other names stay byte for byte. Every model World ships parses and
   re-serializes to identical bytes.
2. **Collision: the base game's copy, only when the shape is the same.** A listed `.pmc` is written as 1.62's own
   file, and only after its vertex and index data are checked to be identical to the source's. Otherwise the tool
   fails.
3. **Every mismatch is listed.** `world/model_variants.yaml` names, for every locked `.pmd`/`.pmc` that lacks a name
   the base copy has, either what each missing name copies or `ignore: <reason>`. `--check` fails on an unlisted
   mismatch, on a changed source or base copy (manifest `world/model_variants.tsv`), and on a stale override.
   Each patched model gets a `resolutions.yaml` entry (`merged: overrides/...`), stamped with the locked hashes.
   It sits after the hand-written entries and before `rain_reflections.py`'s, so the two tools agree on the file.
4. **Choices made for 1.62:**
   - **Looks.**
     - Primel `bi` copies `bg`.
     - Pegi `bi` copies `blkw_rs`, Real companies' West Balkans look.
     - Prefab `primel_bi` copies `primel_bg`.
     - Prefab `pegi_bi` copies `pegi_gr`; Real companies has no Balkan Pegi look.
   - **Variants.**
     - Primel `price2` and `price3` copy `default`: Real companies' sign has one price board.
     - The pizza-house lod1 `default` copies `var1`: Real companies' lod1 lacks the name its own lod0 has.
5. **Left as they are (ignored):**
   - **Austrian gas-station and Gazgamel roof lod1 models.** 1.62's own lod1 names differ from its lod0. Real
     companies' copies match lod0, which is what the prefab asks for.
   - **Real companies' own logo sign designs** (IKA Bohag, VRM oil).
   - **DBM Vegetation's single-look petunias.**
   
   None of these show in a log.

## Consequences

- The Primel/Pegi errors go away, and those signs keep Real companies' brands. In Bosnia, the signs show the
  chosen nearest look.
- **When Real companies ships a 1.62 update:** the tool reports entries the update made unnecessary
  (`no longer needed`) and fails on new mismatches. Remove the unnecessary entries and revisit the look choices.
  `sources.yaml` carries the same reminder.
- **After a game update:** rerun the tool after `megapack lock`. New base names on a source model fail `--check`
  until they are listed.
- The outputs (11 small files) are git-ignored and regenerated after a clone, like the other generated models.

# ADR-0009: World gives lane lines a light feel, separate from the edge rumble

- Status: accepted
- Date: 2026-11-25

## Context

- **The wish.** In the base game, only the solid motorway edge line can be felt: it gives a hard rumble. Lane
  dividers and centre lines give nothing. The maintainer wants a lighter feel on lane lines, so that drifting into
  the next lane and running off the road feel different.
- **How the edge works.** The edge rumble comes from invisible collision parts (`colprkfh*`) in the road template
  models. They use a material with the `rumble_stripe` substance and sit 5 mm above the road. The painted lines
  are decals at 20 mm with no substance, and the game does not use decals as wheel surfaces. A test package that
  gave the line materials a substance was not felt (outcome (c), 2026-11-14).
- **What the wheels use.** Road wheel contact comes only from parts whose names start with `coll`. In-game
  canaries showed this on 2026-11-23:
  - a lifted copy of the road collision in a new part `colcanary0` was not felt;
  - the same copy inside the `coll` part was felt;
  - the same copy in a new part `collcanary0` was felt.
  
  A `coll*` part also follows the per-variant `visible` attribute.
- **The choice of feel.** Lines with the edge's own setting (rumble, 5 mm) felt the same as the edge. Of three
  lighter tunings, the maintainer picked plain `road` at 4 mm: a thump on crossing, with no rumble sound
  (2026-11-25). The other two were rumble at 2.5 mm and road at 2.5 mm.
  - `road_coarse` and `concrete` were ruled out: they throw dust when driven on.
  - `road_smooth` would need a `material.db` edit.
- **Conflicts.** No merged source ships road template models (`road_template/**/*.pmg|pmd`).
- **Precedent.** World already carries a felt road feature as patched base models: Daniel's asphalt-patch bump
  (ADR-0008, `tools/patch_bump.py`, 10 / 6.5 mm). The lane strips sit lower, at 4 mm.

## Decision

1. **`tools/lane_strips.py` patches the base road templates.** It reads every base `road_template/` model except
   the far LODs. For each model, it collects the line triangles (≤ 1.1 m wide) from the visible parts: a line
   material is a decal whose texture name contains "line" and not "chevron". It drops the two outermost line
   positions across the road (the edges), then adds one invisible part `collbrkN` per source part:
   - the triangles, flat at 4 mm (`HEIGHT_MM`);
   - the `coll` piece's vertex layout;
   - the source part's visibility in every variant;
   - the material `/material/drivedogs/lane_feel.mat`.
2. **The material is World's own.** `overrides/material/drivedogs/lane_feel.mat` uses `eut2.none.rfx` with
   substance `road`. Game files are not edited.
3. **The originals stay byte for byte.** The tool checks each built model: original parts, pieces, vertex and
   index data, visibility, looks and materials are unchanged, and every strip is well formed and at the set height.
   It writes `world/lane_strips.tsv` (base and output hashes, strips and triangles per model). `--check` fails when
   the base game, the tool or the overrides change. The tool fails if a source ships one of these models, if a
   model already has a `collbrk*` part, or if a model with lines has a collision layout it does not know.
4. **1.62 result.** 124 models, 914 strips, byte-identical to the road40 test package the maintainer played.

## Consequences

- Crossing a lane line gives a light thump, and the motorway edge keeps its rumble. A road whose look has no
  painted line gets no strip.
- **Gaps.**
  - About 22 strips copy line parts that road looks switch on through `add_parts` (merge, warning, parking and
    toll lines). Those stay off, as their parts are off in every variant.
  - Prefab roads (junctions) and the far LODs are not covered.
- **World now ships 248 base road template files.** A mod that ships any of these models and loads above World
  replaces World's copy, and those roads lose the lane feel. One that loads below World loses its own model
  changes. If this becomes a problem, the strips can move to a separate optional package (asked 2026-11-25:
  "inside world for now").
- **After a game update:** rerun the tool. `--check` reports changed base models, and the tool fails on a model
  layout it does not know.
- The 248 outputs are git-ignored and regenerated after a clone, like the other generated models.

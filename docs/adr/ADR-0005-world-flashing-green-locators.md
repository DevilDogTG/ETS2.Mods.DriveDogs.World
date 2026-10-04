# ADR-0005: World adds a flashing-green locator to the timed traffic-light models, so night yellow blinks again

- Status: accepted
- Date: 2026-10-04
- Amends: [ADR-0004](ADR-0004-world-base-data-fixes.md) decision 1 (World still owns the timing)

## Context

- World 1.2.0 gives 108 standard semaphore models a `green_trans` state (the last 3 s of green, ADR-0004). The models
  behind them carry only 4 flare locators: `green`, `red`, `yellow`, `yellow.blink.sleep`. One flare unit has one blink
  pattern and one lamp slot, so 4 locators cannot do both a green flash and the night sleep-mode yellow blink.
- The TrafficLights add-on 1.0.0 solved it by turning `flare.traffic.yellow.blink.sleep` into the green blinker and
  moving sleep mode onto the steady `flare.traffic.yellow` (its decision D1). Result in game: yellow is steady at night
  everywhere (user, 2026-10-04), and World without the add-on leaves the green lens dark for 3 s.
- The base game's own flashing-green models (AT, Baltics, Balkans, GR, ES) carry a 5th locator,
  `flare.traffic.green.trans`, at exactly the green locator's position and rotation. Base and Better Flares 4.8 both
  define that hookup unit (blink 0.5/0.5 in `green_trans`; Better Flares with its `tr_green` glow, scale 5).
- No mod in the load order ships `model/traffic_light/*` (Better Flares parts, the add-on, AI Traffic, Trailers &
  Cargo, Trucks Sound, World's sources), so World's models win although World loads below them.

## Decision

1. `tools/traffic_light_locators.py` writes the 91 models behind `world/traffic_lights.yaml` to
   `overrides/model/traffic_light/` (git-ignored, manifest `world/traffic_light_locators.tsv`, `--check`): the base
   model with every `flare.traffic.green` locator copied as `flare.traffic.green.trans` (172 locators; name
   `gt_<green name>`). Geometry and existing locators are unchanged. A model that already has the locator, or that a
   source ships, stops the tool.
2. The TrafficLights add-on (1.1.0) goes back to Better Flares' own `yellow` and `yellow.blink.sleep` units (D1
   reversed in its own ADR). It no longer touches the flash.
3. The add-on is no longer required by World. World + Better Flares gives the flash and the night blink with Better
   Flares' glow; World alone gives them with the base flares.

## Consequences

- Night sleep mode (23:30-03:00) blinks yellow again; the flash lights every green lens (city_fr 4, single_fr and
  single_es 3), with a glow, instead of the lens only on the heads that had a sleep locator.
- The add-on 1.0.0 must not be combined with World 1.3.0: its old blinker would flash on the yellow lens' locator in
  green_trans next to the new one, and keep night yellow steady. The description says so.
- After a game update or a change of the add-on's target list: regenerate `world/traffic_lights.yaml`, then rerun
  `traffic_light_locators.py`. A base model that gains its own `green.trans` locator fails the tool and should leave
  the target list.

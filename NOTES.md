# BERRYBOY Mech Royale – working notes

Deadline: Sun Nov 22, 10:00 AM CST. Metric: mean of (16 - place) over 48 practice matches.

## Current best

| Score | Commit | Submitted |
|-------|--------|-----------|
| 1.15 | `b9c2787` (baseline, kit example strategy) | Fri 10:58 PM CST |

## Submission log

| # | Time (CST) | Commit | Real score | Local sim (cal-A, 40 matches) | Change |
|---|------------|--------|-----------:|------------------------------:|--------|
| 1 | Fri 10:58 PM | `b9c2787` | **1.15** | 1.10 | Baseline: kit example strategy, pinned base image |
| 2 | Fri ~11:45 PM | v2 (see below) | pending | 2.48 | Map model, zone hold spot, cover/hide, lone-hunter fights, lead aiming, pickups, hard-wrapped act() |

## What the scorer shows

Only the mean score and an answer-time figure ("wait 12 ms"). No per-match placements and no replays.
So every per-match analysis below comes from the local simulator (`tools/sim.py`).

## Local simulator (tools/sim.py)

Runs the real `bot.py` as a subprocess over the mechfight/1 protocol against 15 house bots
(4 easy, 4 medium, 4 hard, 3 expert): shared squad vision, no friendly fire, hunters assigned
weakest-first (1 at the start, +1 per house bot we kill, all of them after 300 s). It models
walls (2 m grid), terrain height, line of sight, gun bullets with lead and spread, laser charge,
lightning, mortar shells, zone phases and damage, regen, rear armor, and floor weapon loot.
Not modelled: roofs/jumping, crates, cubes, NPC drones, supply drops, sounds.

Calibration ("cal-A", the default): non-hunters never shoot, house aim noise x2. With that the kit
baseline scores 1.10 locally vs 1.15 for real, so cal-A is the reference for "better locally".
Harsher variant for robustness: `NEAR_AGGRO=45 PROVOKE=10 NOISE_MULT=1`.

## Analysis log

### #1 baseline (real 1.15)
- Walks straight to the next zone centre, fires both slots at the nearest visible mech.
- Local (cal-A) deaths: almost all to the first (easy) hunter in the open, median ~45 s.

### #2 v2 (local 2.48 vs 1.10)
- Local placement spread (40 matches): died first 1, place >= 12: 35, top 8: 0.
- Causes of death: easy hunter 27, medium hunter 11, hard hunter 2. Zone 0. Crashes 0, late answers 0.
- At death, 2+ enemies had line of sight in 27/40 matches: after each kill another hunter joins,
  so the 3rd-5th fights are against 2-3 hunters at once.
- Next fix candidate: stop fighting once 2 hunters are near, and hide/regen between kills.

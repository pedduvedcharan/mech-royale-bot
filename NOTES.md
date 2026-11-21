# BERRYBOY Mech Royale – working notes

Deadline: Sun Nov 22, 10:00 AM CST. Metric: mean of (16 - place) over 48 practice matches.

## Current best

| Score | Commit | Submitted |
|-------|--------|-----------|
| **2.00** | `79710fa` (v2) | Fri 11:26 PM CST |

## Submission log

| # | Time (CST) | Commit | Real score | Local sim (cal-A, 40 matches) | Change |
|---|------------|--------|-----------:|------------------------------:|--------|
| 1 | Fri 10:58 PM | `b9c2787` | **1.15** | 1.10 | Baseline: kit example strategy, pinned base image |
| 2 | Fri 11:26 PM | `79710fa` | **2.00** | 2.48 | v2: map model, zone hold spot, cover/hide, lone-hunter fights, lead aiming, pickups, hard-wrapped act() |
| 3 | Fri ~11:55 PM | v3 (pending) | pending | 2.93 | Only treat enemies that shot us / aim at us / are within 35 m as threats |

## What the scorer shows

Only the mean score and a queue-wait figure ("wait 117 ms" is time spent in the scoring queue, per the
status page, not our answer time). No per-match placements and no replays.
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

Real result: **2.00** (baseline 1.15). Between the cal-A prediction (2.48) and the harsh one (1.33),
so real house bots are somewhat more dangerous than cal-A.

### #3 v3: attacker filter (local cal-A 2.48 -> 2.93; medium-harsh 1.57 -> 1.60, 60 matches)
Analysis of v2's local deaths, replayed tick by tick (tools/analyze.py):
- 33/40 deaths had 2+ enemies with line of sight, but most of those were *bystander* house bots
  gathered near the zone centre, not hunters. v2 counted every visible mech as a threat, so it went
  into "hide" mode, ran from bystanders it could never all hide from, and did not fire back at the
  one hunter actually shooting it (seed 29: died 16th with 0 kills while hiding from 4 mechs, killed
  by the single easy hunter).
- Ranked causes (places lost): hiding from bystanders instead of fighting the hunter (most),
  then two hunters at once after the first kill, then caught in the open.
Change: an enemy counts as a threat only if it damaged us in the last 10 s, aims at us
(torso yaw within 0.15 rad of our bearing, or 0.3 rad while charging a laser), or is within 35 m.
Cost: one atan2 per visible enemy per tick. Must not break: zone logic, hiding from real hunters.
Proof: the 4 earliest-death seeds improved (29: 16->12, 33: 15->14, 6: 15->14, 23: 15->14);
17 seeds better, 7 worse; mean 2.48 -> 2.93. Under the harsh calibration (non-hunters shoot within
45 m) it is level (1.57 vs 1.60, 60 matches), so it should not hurt if bystanders are more aggressive.

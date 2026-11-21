# BERRYBOY Mech Royale – working notes

Deadline: Sun Nov 22, 10:00 AM CST. Metric: mean of (16 - place) over 48 practice matches.

## Current best

| Score | Commit | Submitted |
|-------|--------|-----------|
| **2.60** | `79a0edc` (v4) | Sat 1:20 AM CST |

## Submission log

| # | Time (CST) | Commit | Real score | Local sim (cal-A, 40 matches) | Change |
|---|------------|--------|-----------:|------------------------------:|--------|
| 1 | Fri 10:58 PM | `b9c2787` | **1.15** | 1.10 | Baseline: kit example strategy, pinned base image |
| 2 | Fri 11:26 PM | `79710fa` | **2.00** | 2.48 | v2: map model, zone hold spot, cover/hide, lone-hunter fights, lead aiming, pickups, hard-wrapped act() |
| 3 | Fri 11:36 PM | `0658e4d` | **2.15** | 2.93 | v3: only treat enemies that shot us / aim at us / are within 35 m as threats |
| 4 | Sat 1:20 AM | `79a0edc` | **2.60** | sim2 cal-B 2.52 | v4: farm cubes from crates and NPC drones when safe; bystanders no longer count as threats |
| 5 | Sat ~2:40 AM | v5 (pending) | pending | sim2 cal-B 2.68 -> 2.95 | Fire when one tick of torso slew closes the aim error; grab dropped cubes; remember crates/drones |

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

Real result: **2.15** (+0.15 over v2). Smaller than the local gain (+0.45), so cal-A is optimistic.

### #4 v4: safe cube farming + bystander fix
Analysis of v3 (local traces, seeds 301-312, tick by tick):
- Seed 310 (died 16th, 0 kills): the single easy hunter sat at ~45 m with 1130 HP and was never hit.
  Two passive bystanders within 35 m counted as "threats", so v3 hid instead of fighting and spent
  every shot on the bystanders (1000+ damage that they simply regenerated).
- Over 20 matches v3 dealt 4.2x the damage it took and hit 96% of shots, yet averaged ~2 kills:
  damage is spread and the targets regenerate. The bot loses fights by being weaker, not by missing.
- The simulator lacked cubes, crates, NPC drones and upgrades, so it could not value growing
  stronger. Added them (36 crates at 75% on the ground, 12 drones that shoot back, cube drops from
  kills, +4% HP and damage per cube, upgrade offers, house bots also gaining cubes over time).
  With that "sim2", v3 scores 1.87 (cal-B) - much closer to its real 2.15 than the old sim was.
- In sim2, 8-15 of 60 v3 deaths are to NPC drones it walked near, and v3 rarely has more than 1-2
  cubes when the first hunter arrives.
Change:
1. `_farm()`: in travel mode, with no attacker known within 150 m, not hit for 5 s and well inside
   the zone, shoot ground crates within 75 m (walk up to grab the cube) and NPC drones within 75 m
   when HP > 60% (keep ~30 m, lead the shot). Visible cubes are collected by the existing loot code.
   NPC damage no longer flips the bot into hide mode.
2. Bug fix from seed 310: mechs within 35 m are no longer threats just for being close; attackers
   (shot us in the last 10 s / aim at us) are shot first.
Cost: one extra pass over visible crates/drones per tick, one LOS check. p99 7.2 ms in the sandbox check.
Local proof (sim2, 60 matches each, fresh seeds):
- cal-B: v3 1.87 -> v4 2.52; deaths to drones 8 -> 3; died first 9 -> 4.
- cal-A: v3 2.28 -> v4 3.00; deaths to drones 13 -> 4.

Real result: **2.60** (+0.45). sim2 cal-B predicted 2.52, so sim2 cal-B now tracks the real
scorer closely (v3: 1.87 vs 2.15 real; v4: 2.52 vs 2.60 real). cal-B (`NOISE_MULT=1.4`) is now the
reference calibration.

### #5 v5: fire through the torso slew
Analysis of v4 (sim2 cal-B, 40 matches traced, plus 20 matches with fire-reason logging):
- Deaths: 26/40 had 2+ hunters damaging us in the last 10 s; 12/40 a single hunter; 1 zone death
  (a simulator artifact: spawned wedged against a wall, fixed in the sim); 4 to NPC drones.
- In 62% of ticks where a hunter had line of sight to us, we were *not* firing. Reasons logged:
  reloading 770 ticks (unavoidable, 12-round magazine), **aim not yet aligned 770 ticks**, no
  target 244, blocked line 52. The median yaw error when holding fire was 0.05 rad, only just over
  the 0.023 rad tolerance at 70 m: with both mechs strafing, the desired aim moves ~0.03 rad per
  decision, so the torso is always one decision behind and the bot kept waiting.
- Tried and rejected on sim2 (no gain, within noise): fighting two hunters at once (2.45-2.50 vs
  2.45), longer preferred fight range 120/170 m (2.47/2.72 vs 2.53/2.67), remembered-crate farming
  out to 170-250 m (2.45-2.50 vs 2.53; hunters arrive within ~30 s so there is little time to farm),
  grabbing dropped cubes whenever no attacker has line of sight (2.57/2.78 vs 2.50/2.80; more cubes,
  same score). The last two are kept because they are harmless and collect more cubes.
Change: the gun's fire tolerance adds half of one tick of torso slew (turn_rate x 0.05 s x 0.5 =
0.1 rad yaw, 0.075 rad pitch). The torso reaches the commanded aim within the first tick, so the
shot still lands. Half (not the full tick) in case the server fires before slewing within a tick.
Cost: none (two multiplications per tick).
Local proof (sim2 cal-B, 60 matches each):
- seeds 801-860: no slew 2.62 -> full slew 3.02 -> half slew 2.95; shots per match 122 -> 130.
- seeds 901-960: no slew 2.73 -> full slew 2.83.

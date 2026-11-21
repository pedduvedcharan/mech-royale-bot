# BERRYBOY Mech Royale – working notes

Deadline: Sun Nov 22, 10:00 AM CST. Metric: mean of (16 - place) over 48 practice matches.

## Current best

| Score | Commit | Submitted |
|-------|--------|-----------|
| **3.50** | `9feac44` (v6) | Sat 3:23 AM CST |

## Submission log

| # | Time (CST) | Commit | Real score | Local sim (cal-A, 40 matches) | Change |
|---|------------|--------|-----------:|------------------------------:|--------|
| 1 | Fri 10:58 PM | `b9c2787` | **1.15** | 1.10 | Baseline: kit example strategy, pinned base image |
| 2 | Fri 11:26 PM | `79710fa` | **2.00** | 2.48 | v2: map model, zone hold spot, cover/hide, lone-hunter fights, lead aiming, pickups, hard-wrapped act() |
| 3 | Fri 11:36 PM | `0658e4d` | **2.15** | 2.93 | v3: only treat enemies that shot us / aim at us / are within 35 m as threats |
| 4 | Sat 1:20 AM | `79a0edc` | **2.60** | sim2 cal-B 2.52 | v4: farm cubes from crates and NPC drones when safe; bystanders no longer count as threats |
| 5 | Sat 2:28 AM | `cc9ce93` | **3.21** | sim2 cal-B 2.68 -> 2.95 | v5: fire when one tick of torso slew closes the aim error; grab dropped cubes; remember crates/drones |
| 6 | Sat 3:23 AM | `9feac44` | **3.50** | 2.97 -> 3.05 (3 seed sets) | v6: sprint (boost) the strafe in fights while energy > 30 |
| 7 | Sat ~5:25 AM | v7 (pending) | pending | paired: +0.16 +- 0.07 over v6 | Regenerate in cover between fights when HP < 75% |

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

Real result: **3.21** (+0.61 over v4, larger than the sim's +0.3). Firing more often pays.

### After v5: experiments that did not beat v5 locally (not pushed)
Analysis of v5 (sim2 cal-B, 40 traced matches): when a hunter has line of sight and we don't fire,
the reason is now mostly the reload (4900 ticks) and "no target in our view" (1945), aim lag only
664. At death 36/40 matches had 2-3 hunters hitting us in the last 10 s; median death 85 s, 3 kills.
- Step into cover while the gun reloads: 3.08 vs 3.28 (same seeds). Rejected.
- Upgrade order weapon-first (gun_mag/gun_rate early): 3.23 vs 3.28. Rejected.
- Sweep the view +-90 degrees while walking, face heard sounds: 3.07 vs 3.28. Rejected (the sim
  has no sounds, so the sound half is untested).
- Full-tick slew tolerance for gun and laser (slew 1.0): 3.03/2.90 vs 3.12/2.85. No gain; keep 0.5.
- Opening 360-degree look + walking up to 180 m to a remembered laser/lightning: 2.87 vs 3.12. Rejected
  (the detour costs more than the weapon is worth before the first hunter arrives).

### #6 v6: sprint while strafing in fights
Why: at death 36/40 v5 matches had 2-3 hunters hitting us. Real house bots are accurate (the
recorded kit match shows repeated hits from 100-150 m), so getting hit less matters as much as hitting.
Change: in fight mode, boost (19.5 m/s instead of 11.7) while energy > 30. Lateral displacement
during a 0.3 s bullet flight goes from ~3.5 m to ~5.8 m, more than the 2.5 m mech radius, so a
shooter leading with our old velocity misses after each strafe flip. Energy regenerates 18/s after
0.6 s, so the bot sprints in bursts. Cost: none.
Local proof (sim2, 60 matches per cell): cal-B seeds 1101/1201/1301: 3.12/2.85/2.95 -> 3.32/2.87/2.97;
accurate house bots (NOISE 1.0) seeds 1101: 2.75 -> 2.78. Small but positive in all four.

Real result: **3.50** (+0.29 over v5; the sim only showed +0.08). Dodging is worth far more against
the real house bots than against the simulator's noisy-aim bots: real hunters lead their shots well.
Added a "precise, leading house bots" setting to the sim (`LEAD_ALL=1.0 NOISE_MULT=0.4`, "cal-D"):
there v5 -> v6 is 1.73 -> 1.95, matching the real direction.

### After v6: experiments that did not beat v6 locally (not pushed)
- Faster strafe flips (0.35-0.9 s) + boost while hiding (cal-D): 1.67 vs 1.95. Boost while hiding
  alone: 1.82 vs 1.95. Rejected.
- Longer fighting range 110/150 m (cal-D): 1.65 vs 1.95. Rejected.
- Close to 32 m when holding lightning (cal-B): 2.85 vs 2.88. Rejected.
- Walk up to 150 m to a remembered laser (cal-B): 2.78 vs 2.55 (seeds 1401) but 3.10 vs 3.12
  (seeds 1101). Inconclusive; not pushed.
- Weapon stats (sim, 40 matches): matches where we held a laser score 4.4, lightning 2.8,
  mortar 2.4, no special 1.6; the gun still does ~83% of our damage.
- Face attackers that hit us from outside our view (paired, cal-B): +0.00 (56/60 matches identical:
  it almost never triggers). Not pushed.
- Reload in any lull when the magazine is under half (paired, cal-B): -0.05 +- 0.09. Not pushed.
- Zig-zag + sprint while under fire outside fights: cal-D +0.23 +- 0.15 and -0.08 +- 0.13, cal-B
  -0.05 +- 0.17. Not pushed.
- Fight two hunters at once (paired, cal-B): -0.22 +- 0.14. Rejected.
- Supply drops (added to the sim): the bot captured 0 drops in 30 matches (it is rarely alive and
  free when they land at 95 s+), score 2.65 vs ~2.7. Not pushed.

### Measuring smaller effects: paired, deterministic simulation
60-match runs of the *same* code differed by up to 0.35 (2.52 vs 2.88), because the bot's per-tick
work budgets use the wall clock. `bot.py` now reads its budget clock through `now()`; with
`BOT_PARAMS={"det":1}` (simulator only) the budgets count calls instead, so a run is reproducible and
A/B runs on the same seeds are compared match by match (`ab.sh`: mean paired difference +- its
standard error). Real matches still use the real clock.

### #7 v7: regenerate between fights
Why: deaths come in the 2nd/3rd fight. After a kill v6 walks straight back to its hold spot or loot
with whatever HP it has left, and meets the next (now two) hunters at 40-70% HP. HP regenerates at
45/s after 5 s without damage, so 15 s in cover is worth ~650 HP.
Change: a "regen" mode: no attacker in sight, not hit in the last 2.5 s, HP < 75%, inside the zone and
no zone pressure -> use the hide logic (move out of every recently seen attacker's line of sight, then
stand still) until HP is back over 75%. Zone urgency and new attackers override it.
Cost: one more condition per tick; hide search only while regenerating.
Local proof (paired, 60 matches each, v6 vs v7):
- cal-B seeds 1501: +0.23 +- 0.18; seeds 1601: +0.00 +- 0.14.
- cal-D (precise, leading house bots) seeds 1501: +0.40 +- 0.14 (17 better, 5 worse); seeds 1601: +0.00 +- 0.12.
- Combined: +0.16 +- 0.07.

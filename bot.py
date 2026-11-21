"""BERRYBOY mech bot for mechfight/1 (Builders Buildathon, Mech Royale).
Standard library only. One file: protocol loop, static map model, and strategy."""
import array
import json
import math
import os
import queue
import random
import sys
import threading
import time
import traceback
from collections import deque

NAME = "BERRYBOY"

INF = float("inf")


class World:
    C = 2.0   # fine grid (m) for line of sight and walls
    N = 4.0   # nav grid (m) for path planning

    def __init__(self, map_dir, mech_cfg):
        wj = None
        for d in (map_dir, "/arena", os.path.join(os.path.dirname(os.path.abspath(__file__)), "arena")):
            try:
                with open(os.path.join(d, "v2", "world.json")) as f:
                    wj = json.load(f)
                self.dir = d
                break
            except Exception:
                continue
        if wj is None:
            raise RuntimeError("map not found")
        b = wj["bounds"]
        self.minx, self.maxx, self.miny, self.maxy = b["minX"], b["maxX"], b["minY"], b["maxY"]
        C = self.C
        self.gx = int(math.ceil((self.maxx - self.minx) / C)) + 1
        self.gy = int(math.ceil((self.maxy - self.miny) / C)) + 1
        self.step_up = mech_cfg.get("step_up", 1.2)
        self.body_h = mech_cfg.get("height", 9.0)
        self._terrain(wj)
        self._prisms(wj)
        self._nav()

    # ---------------------------------------------------------------- terrain
    def _terrain(self, wj):
        t = wj["terrain"]
        self.tnx, self.tny = t["nx"], t["ny"]
        self.tminx, self.tminy, self.tstep = t["minX"], t["minY"], t["step"]
        a = array.array("h")
        with open(os.path.join(self.dir, "v2", t.get("file", "terrain.i16")), "rb") as f:
            a.frombytes(f.read())
        if array.array("h", [1]).tobytes() != b"\x01\x00":
            a.byteswap()
        self.th = a
        # ground height sampled at fine-grid cell centers
        gx, gy, C = self.gx, self.gy, self.C
        g = array.array("f", bytes(4 * gx * gy))
        for j in range(gy):
            y = self.miny + (j + 0.5) * C
            tj = int(round((y - self.tminy) / self.tstep))
            tj = 0 if tj < 0 else (self.tny - 1 if tj >= self.tny else tj)
            row = tj * self.tnx
            base = j * gx
            for i in range(gx):
                x = self.minx + (i + 0.5) * C
                ti = int(round((x - self.tminx) / self.tstep))
                ti = 0 if ti < 0 else (self.tnx - 1 if ti >= self.tnx else ti)
                g[base + i] = a[row + ti] * 0.01
        self.gnd = g

    def ground(self, x, y):
        """Bilinear terrain height (m)."""
        fx = (x - self.tminx) / self.tstep
        fy = (y - self.tminy) / self.tstep
        i = int(fx)
        j = int(fy)
        if i < 0 or j < 0 or i >= self.tnx - 1 or j >= self.tny - 1:
            i = min(max(i, 0), self.tnx - 1)
            j = min(max(j, 0), self.tny - 1)
            return self.th[j * self.tnx + i] * 0.01
        u = fx - i
        v = fy - j
        k = j * self.tnx + i
        a = self.th
        return ((a[k] * (1 - u) + a[k + 1] * u) * (1 - v) + (a[k + self.tnx] * (1 - u) + a[k + self.tnx + 1] * u) * v) * 0.01

    # ---------------------------------------------------------------- buildings
    def _prisms(self, wj):
        gx, gy, C = self.gx, self.gy, self.C
        n = gx * gy
        lo = array.array("f", [1e9]) * n
        hi = array.array("f", [-1e9]) * n
        for p in wj["prisms"]:
            ring = p["ring"]
            polys = [ring] + list(p.get("holes") or [])
            edges = []
            ys = ring[1::2]
            for poly in polys:
                m = len(poly) // 2
                for k in range(m):
                    x1, y1 = poly[2 * k], poly[2 * k + 1]
                    x2, y2 = poly[(2 * k + 2) % (2 * m)], poly[(2 * k + 3) % (2 * m)]
                    if y1 != y2:
                        edges.append((x1, y1, x2, y2))
            base, top = p["base"], p["top"]
            j0 = max(0, int((min(ys) - self.miny) / C) - 1)
            j1 = min(gy - 1, int((max(ys) - self.miny) / C) + 1)
            for j in range(j0, j1 + 1):
                yc = self.miny + (j + 0.5) * C
                xs = []
                for x1, y1, x2, y2 in edges:
                    if (y1 <= yc < y2) or (y2 <= yc < y1):
                        xs.append(x1 + (yc - y1) * (x2 - x1) / (y2 - y1))
                if len(xs) < 2:
                    continue
                xs.sort()
                row = j * gx
                for k in range(0, len(xs) - 1, 2):
                    i0 = int(math.ceil((xs[k] - self.minx) / C - 0.5))
                    i1 = int(math.floor((xs[k + 1] - self.minx) / C - 0.5))
                    if i1 < i0:  # thin wall narrower than a cell: still mark it
                        i0 = i1 = int((0.5 * (xs[k] + xs[k + 1]) - self.minx) / C)
                    i0 = max(i0, 0)
                    i1 = min(i1, gx - 1)
                    for i in range(i0, i1 + 1):
                        c = row + i
                        if base < lo[c]:
                            lo[c] = base
                        if top > hi[c]:
                            hi[c] = top
        self.lo, self.hi = lo, hi
        # wall cells: a solid that blocks a mech standing on the ground there
        wall = bytearray(n)
        g = self.gnd
        su, bh = self.step_up, self.body_h
        for c in range(n):
            if hi[c] > g[c] + su and lo[c] < g[c] + bh:
                wall[c] = 1
        # terrain steps too steep to walk count as walls (between neighbours, both ways)
        lim = math.tan(math.radians(50)) * C
        for j in range(gy):
            row = j * gx
            for i in range(gx):
                c = row + i
                h = g[c]
                if i + 1 < gx and abs(g[c + 1] - h) > lim:
                    wall[c] = wall[c + 1] = 1
                if j + 1 < gy and abs(g[c + gx] - h) > lim:
                    wall[c] = wall[c + gx] = 1
        self.wall = wall

    def cell(self, x, y):
        i = int((x - self.minx) / self.C)
        j = int((y - self.miny) / self.C)
        if i < 0 or j < 0 or i >= self.gx or j >= self.gy:
            return -1
        return j * self.gx + i

    def is_wall(self, x, y):
        c = self.cell(x, y)
        return c < 0 or self.wall[c] == 1

    def los(self, ax, ay, az, bx, by, bz, step=1.5):
        """True if the segment A->B is not blocked by a building, bridge, stadium or terrain.
        Trees are ignored (they do not stop shots)."""
        dx, dy, dz = bx - ax, by - ay, bz - az
        d = math.hypot(dx, dy)
        n = int(d / step)
        if n < 1:
            return True
        lo, hi, g = self.lo, self.hi, self.gnd
        minx, miny, C, gx, gy = self.minx, self.miny, self.C, self.gx, self.gy
        inv = 1.0 / n
        # skip the first and last ~2 m (inside the shooter / target body)
        k0 = max(1, int(2.0 / step))
        for k in range(k0, n - k0 + 1):
            f = k * inv
            i = int((ax + dx * f - minx) / C)
            j = int((ay + dy * f - miny) / C)
            if i < 0 or j < 0 or i >= gx or j >= gy:
                return False
            c = j * gx + i
            z = az + dz * f
            if z < g[c] - 0.3:
                return False
            if lo[c] <= z <= hi[c]:
                return False
        return True

    def clear_path(self, ax, ay, bx, by, step=1.0):
        """True if a mech can walk straight from A to B (no wall cell on the way)."""
        dx, dy = bx - ax, by - ay
        d = math.hypot(dx, dy)
        n = max(1, int(d / step))
        wall, minx, miny, C, gx, gy = self.wall, self.minx, self.miny, self.C, self.gx, self.gy
        for k in range(1, n + 1):
            f = k / n
            i = int((ax + dx * f - minx) / C)
            j = int((ay + dy * f - miny) / C)
            if i < 0 or j < 0 or i >= gx or j >= gy or wall[j * gx + i]:
                return False
        return True

    def free_dist(self, x, y, yaw, maxd=12.0, step=1.0):
        """How far a mech can go from (x, y) along yaw before a wall (mech radius included)."""
        cy, sy = math.cos(yaw), math.sin(yaw)
        px, py = -sy * 2.2, cy * 2.2
        wall, minx, miny, C, gx, gy = self.wall, self.minx, self.miny, self.C, self.gx, self.gy
        d = step
        while d <= maxd:
            for ox, oy in ((0.0, 0.0), (px, py), (-px, -py)):
                i = int((x + cy * (d + 2.0) + ox - minx) / C)
                j = int((y + sy * (d + 2.0) + oy - miny) / C)
                if i < 0 or j < 0 or i >= gx or j >= gy or wall[j * gx + i]:
                    return d - step
            d += step
        return maxd

    # ---------------------------------------------------------------- navigation grid
    def _nav(self):
        N, C = self.N, self.C
        self.nx = int(math.ceil((self.maxx - self.minx) / N))
        self.ny = int(math.ceil((self.maxy - self.miny) / N))
        nx, ny = self.nx, self.ny
        free = bytearray(nx * ny)
        margin = 6.0
        for j in range(ny):
            y = self.miny + (j + 0.5) * N
            if y < self.miny + margin or y > self.maxy - margin:
                continue
            for i in range(nx):
                x = self.minx + (i + 0.5) * N
                if x < self.minx + margin or x > self.maxx - margin:
                    continue
                ok = True
                # keep the mech's radius (2.5 m) clear: check a 3x3 block of fine cells (6 m square)
                for oy in (-2.0, 0.0, 2.0):
                    for ox in (-2.0, 0.0, 2.0):
                        if self.is_wall(x + ox, y + oy):
                            ok = False
                            break
                    if not ok:
                        break
                if ok:
                    free[j * nx + i] = 1
        # keep only the largest walkable region: courtyards and walled pockets can't be walked into
        comp = array.array("i", [0]) * (nx * ny)
        best_id, best_n, cid = 0, 0, 0
        for s in range(nx * ny):
            if not free[s] or comp[s]:
                continue
            cid += 1
            comp[s] = cid
            dq = deque([s])
            cnt = 0
            while dq:
                c = dq.popleft()
                cnt += 1
                i, j = c % nx, c // nx
                for ii, jj in ((i + 1, j), (i - 1, j), (i, j + 1), (i, j - 1)):
                    if 0 <= ii < nx and 0 <= jj < ny:
                        cc = jj * nx + ii
                        if free[cc] and not comp[cc]:
                            comp[cc] = cid
                            dq.append(cc)
            if cnt > best_n:
                best_n, best_id = cnt, cid
        for c in range(nx * ny):
            if free[c] and comp[c] != best_id:
                free[c] = 0
        self.free = free
        # cover score: blocked neighbours within 2 nav cells (higher = more walls nearby)
        cov = bytearray(nx * ny)
        for j in range(2, ny - 2):
            for i in range(2, nx - 2):
                c = j * nx + i
                if not free[c]:
                    continue
                s = 0
                for dj in (-2, -1, 0, 1, 2):
                    r = (j + dj) * nx
                    for di in (-2, -1, 0, 1, 2):
                        if not free[r + i + di]:
                            s += 1
                cov[c] = s
        self.cover = cov

    def ncell(self, x, y):
        i = int((x - self.minx) / self.N)
        j = int((y - self.miny) / self.N)
        if i < 0 or j < 0 or i >= self.nx or j >= self.ny:
            return -1
        return j * self.nx + i

    def ncenter(self, c):
        return (self.minx + (c % self.nx + 0.5) * self.N, self.miny + (c // self.nx + 0.5) * self.N)

    def nearest_free(self, x, y, rmax=6):
        c = self.ncell(x, y)
        if c >= 0 and self.free[c]:
            return c
        i0 = int((x - self.minx) / self.N)
        j0 = int((y - self.miny) / self.N)
        for r in range(1, rmax + 1):
            best, bd = -1, 1e18
            for dj in range(-r, r + 1):
                for di in range(-r, r + 1):
                    if max(abs(di), abs(dj)) != r:
                        continue
                    i, j = i0 + di, j0 + dj
                    if 0 <= i < self.nx and 0 <= j < self.ny and self.free[j * self.nx + i]:
                        d = di * di + dj * dj
                        if d < bd:
                            bd, best = d, j * self.nx + i
            if best >= 0:
                return best
        return -1


class FlowField:
    """Breadth-first distance field to a goal over the nav grid, built a slice at a time."""

    def __init__(self, world, gx, gy):
        self.w = world
        self.goal = (gx, gy)
        n = world.nx * world.ny
        self.dist = array.array("i", [-1]) * n
        self.q = deque()
        g = world.nearest_free(gx, gy, 12)
        if g >= 0:
            self.dist[g] = 0
            self.q.append(g)
        self.done = g < 0

    def work(self, budget_cells):
        w = self.w
        nx, ny, free, dist, q = w.nx, w.ny, w.free, self.dist, self.q
        k = 0
        while q and k < budget_cells:
            c = q.popleft()
            k += 1
            d = dist[c] + 1
            i = c % nx
            j = c // nx
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    cc = jj * nx + ii
                    if dist[cc] < 0 and free[cc]:
                        if di and dj and not (free[j * nx + ii] and free[jj * nx + i]):
                            continue  # no corner cutting
                        dist[cc] = d
                        q.append(cc)
        if not q:
            self.done = True
        return k

    def waypoint(self, x, y, look=8):
        """A point to steer to: walk down the field a few cells, keep the farthest straight-line-walkable one."""
        w = self.w
        c = w.ncell(x, y)
        if c < 0 or self.dist[c] < 0:
            c = -1
            i0 = int((x - w.minx) / w.N)
            j0 = int((y - w.miny) / w.N)
            for r in range(1, 7):
                bd = 1e18
                for dj in range(-r, r + 1):
                    for di in range(-r, r + 1):
                        if max(abs(di), abs(dj)) != r:
                            continue
                        i, j = i0 + di, j0 + dj
                        if 0 <= i < w.nx and 0 <= j < w.ny:
                            cc = j * w.nx + i
                            if self.dist[cc] >= 0:
                                d = di * di + dj * dj + self.dist[cc] * 0.01
                                if d < bd:
                                    bd, c = d, cc
                if c >= 0:
                    return w.ncenter(c)
            return None
        nx, ny, dist, free = w.nx, w.ny, self.dist, w.free
        path = [c]
        cur = c
        for _ in range(look):
            if dist[cur] == 0:
                break
            i, j = cur % nx, cur // nx
            best, bd = -1, dist[cur]
            for di, dj in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (1, -1), (-1, 1), (-1, -1)):
                ii, jj = i + di, j + dj
                if 0 <= ii < nx and 0 <= jj < ny:
                    cc = jj * nx + ii
                    if 0 <= dist[cc] < bd:
                        bd, best = dist[cc], cc
            if best < 0:
                break
            cur = best
            path.append(cur)
        # farthest path point reachable in a straight line
        for cc in reversed(path[1:]):
            px, py = w.ncenter(cc)
            if w.clear_path(x, y, px, py, 1.5):
                return (px, py)
        if len(path) > 1:
            return w.ncenter(path[1])
        return w.ncenter(path[0])


# ====================================================================== protocol loop
def log(*a):
    try:
        print(*a, file=sys.stderr, flush=True)
    except Exception:
        pass


def send(msg):
    sys.stdout.write(json.dumps(msg, separators=(",", ":"), allow_nan=False) + "\n")
    sys.stdout.flush()


def run(make_bot):
    q = queue.Queue()

    def reader():
        try:
            for line in sys.stdin:
                if line.strip():
                    q.put(line)
        finally:
            q.put(None)

    threading.Thread(target=reader, daemon=True).start()
    bot, last = None, {}
    while True:
        batch = [q.get()]
        while True:  # only the newest observation matters
            try:
                batch.append(q.get_nowait())
            except queue.Empty:
                break
        latest = None
        for raw in batch:
            if raw is None:
                return
            try:
                msg = json.loads(raw)
            except ValueError:
                continue
            if not isinstance(msg, dict):
                continue
            kind = msg.get("type")
            if kind == "hello":
                try:
                    bot = make_bot(msg)
                except Exception:
                    log(traceback.format_exc())
                    bot = None
                send({"type": "ready", "name": NAME})
            elif kind == "obs":
                latest = msg
            elif kind == "end":
                return
        if latest is None:
            continue
        action = {}
        if bot is not None:
            try:
                action = dict(bot.act(latest) or {})
                last = {k: action[k] for k in ("move", "aim", "boost") if k in action}
            except Exception:
                log(traceback.format_exc())
                action = dict(last)
        action["tick"] = latest.get("tick", 0)
        try:
            send(action)
        except (TypeError, ValueError):
            try:
                send({"tick": latest.get("tick", 0), **last})
            except (TypeError, ValueError):
                send({"tick": latest.get("tick", 0)})


# ====================================================================== helpers
def wrap(a):
    while a > math.pi:
        a -= 2 * math.pi
    while a < -math.pi:
        a += 2 * math.pi
    return a


def fin(v, d=0.0):
    try:
        v = float(v)
    except Exception:
        return d
    return v if math.isfinite(v) else d


UPGRADE_ORDER = ["armor", "plating", "nanites", "servos", "laser_damage", "gun_damage", "laser_charge",
                 "gun_rate", "lightning_efficiency", "gyros", "gun_mag", "capacitor", "reactor", "jets",
                 "sensors", "gun_velocity", "lightning_range", "lightning_chain", "mortar_reload",
                 "mortar_velocity", "mortar_splash", "laser_pierce"]
WEAPON_RANK = {"laser": 3, "lightning": 2, "mortar": 1, "gun": 0}

# tunables (the local simulator can override them through BOT_PARAMS; unset in real matches)
P = {"farm": 1, "farm_r": 75.0, "npc_hp": 0.6}
try:
    P.update(json.loads(os.environ.get("BOT_PARAMS", "{}")))
except Exception:
    pass


# ====================================================================== the bot
class Bot:
    def __init__(self, hello):
        cfg = hello.get("config", {})
        self.cfg = cfg
        self.mech = cfg.get("mech", {})
        self.wcfg = cfg.get("weapons", {})
        self.rng = random.Random(int(fin(hello.get("seed", 0))) & 0xFFFFFFFF)
        self.reach = cfg.get("loot", {}).get("pickup_radius", 4.0)
        self.w = None
        t0 = time.perf_counter()
        try:
            self.w = World(hello.get("map", {}).get("dir", "/arena"), self.mech)
        except Exception:
            log("map load failed:", traceback.format_exc())
        log("init %.2fs" % (time.perf_counter() - t0))
        self.enemies = {}          # id -> last seen info
        self.flow = None
        self.flow_goal = None
        self.hold = None
        self.hold_key = None
        self.last_dmg_t = -99.0
        self.last_dmg_bearing = None
        self.last_dmg_by = None
        self.dmg_window = deque()  # (t, amount)
        self.strafe = 1
        self.strafe_until = 0.0
        self.stuck_since = None
        self.unstick_until = -1.0
        self.unstick_yaw = 0.0
        self.hide_pt = None
        self.hide_t = -99.0
        self.mode = "start"
        self.errs = 0
        self.scan = 0.0
        self.crate_target = None
        self.attack_t = {}         # enemy id -> last time it damaged us or aimed at us
        self.farm_shot = None      # aim/fire at a crate or drone while farming cubes

    # ------------------------------------------------------------ entry
    def act(self, obs):
        t0 = time.perf_counter()
        try:
            a = self._act(obs, t0)
        except Exception:
            self.errs += 1
            if self.errs <= 5 or self.errs % 200 == 0:
                log("act error", self.errs, traceback.format_exc()[-1500:])
            a = self._safe(obs)
        return self._clean(a)

    def _safe(self, obs):
        try:
            me = obs["self"]
            z = obs["zone"]
            c = z["next_center"]
            x, y = me["pos"][0], me["pos"][1]
            yaw = math.atan2(c[1] - y, c[0] - x)
            return {"move": [math.cos(yaw), math.sin(yaw)], "boost": not me.get("in_zone", True), "fire": [False, False]}
        except Exception:
            return {"move": [0.0, 0.0]}

    def _clean(self, a):
        out = {}
        try:
            if "move" in a:
                mx, my = fin(a["move"][0]), fin(a["move"][1])
                n = math.hypot(mx, my)
                if n > 1:
                    mx, my = mx / n, my / n
                out["move"] = [round(mx, 4), round(my, 4)]
            if "aim" in a:
                out["aim"] = [round(wrap(fin(a["aim"][0])), 4), round(max(-1.5, min(1.5, fin(a["aim"][1]))), 4)]
            for k in ("boost", "jump", "reload"):
                if k in a:
                    out[k] = bool(a[k])
            if "fire" in a:
                out["fire"] = [bool(a["fire"][0]), bool(a["fire"][1])]
            for k in ("pick", "take", "drop"):
                if k in a and a[k] is not None:
                    out[k] = int(a[k])
            if "debug" in a:
                out["debug"] = a["debug"]
        except Exception:
            return {"move": [0.0, 0.0]}
        return out

    # ------------------------------------------------------------ zone
    def zone_at(self, z, t):
        """Zone circle (cx, cy, r) at match time t (linear during the shrink window)."""
        c0, r0 = z["center"], z["radius"]
        c1, r1 = z["next_center"], z["next_radius"]
        ss, se = z["shrink_start"], z["shrink_end"]
        if t <= ss or se <= ss:
            return c0[0], c0[1], r0
        f = min(1.0, (t - ss) / (se - ss))
        return c0[0] + (c1[0] - c0[0]) * f, c0[1] + (c1[1] - c0[1]) * f, r0 + (r1 - r0) * f

    def in_safe(self, x, y, margin):
        cx, cy, r = self.safe_now
        return math.hypot(x - cx, y - cy) <= r - margin

    # ------------------------------------------------------------ main
    def _act(self, obs, t0):
        me = obs["self"]
        t = fin(obs.get("t", 0))
        self.t = t
        x, y, z = me["pos"]
        self.x, self.y, self.z = x, y, z
        vx, vy = me["vel"][0], me["vel"][1]
        hp, mhp = me["hp"], max(1.0, me["max_hp"])
        stats = me.get("stats", {})
        scale = 1 + 0.05 * fin(me.get("cubes", 0))
        self.muzzle = z + fin(stats.get("muzzle_height", 7.0), 7.0)
        self.eye = z + fin(stats.get("eye_height", 8.0), 8.0)
        zone = obs["zone"]
        walk = fin(stats.get("walk_speed", 11.7), 11.7)
        act = {"fire": [False, False]}

        # --- events
        for e in obs.get("events", []) or []:
            if e.get("type") == "damaged" and e.get("weapon") not in ("zone", "npc"):
                self.last_dmg_t = t
                self.last_dmg_bearing = e.get("bearing")
                self.last_dmg_by = e.get("by")
                if e.get("by") is not None:
                    self.attack_t[e.get("by")] = t
                self.dmg_window.append((t, fin(e.get("amount", 0))))
        while self.dmg_window and self.dmg_window[0][0] < t - 3.0:
            self.dmg_window.popleft()
        dmg3 = sum(a for _, a in self.dmg_window)

        # --- upgrades
        off = obs.get("offer")
        if off and off.get("choices"):
            ids = [c.get("id") for c in off["choices"]]
            best, bi = 99, 0
            for i, cid in enumerate(ids):
                r = UPGRADE_ORDER.index(cid) if cid in UPGRADE_ORDER else 50
                if r < best:
                    best, bi = r, i
            act["pick"] = bi

        # --- enemies
        seen = {}
        for m in obs.get("mechs", []) or []:
            if m.get("kind") != "mech":
                continue
            seen[m["id"]] = m
            self.enemies[m["id"]] = {"pos": m["pos"], "vel": m.get("vel", [0, 0, 0]), "t": t, "hp": fin(m.get("hp", 1400), 1400),
                                     "weapons": m.get("weapons", []), "charging": m.get("charging", False),
                                     "aim": m.get("aim", [0, 0]), "cubes": fin(m.get("cubes", 0))}
        for k in [k for k, v in self.enemies.items() if t - v["t"] > 20]:
            del self.enemies[k]
        w = self.w

        # --- zone: where must we be?
        self.safe_now = self.zone_at(zone, t + 3.0)
        cx1, cy1 = zone["next_center"]
        r1 = zone["next_radius"]
        cxn, cyn, rn = self.zone_at(zone, t)
        dz_now = math.hypot(x - cxn, y - cyn) - rn
        in_zone = me.get("in_zone", True)
        # time we need to reach the next circle vs. time it starts to bite
        need = (math.hypot(x - cx1, y - cy1) - r1 * 0.6) / walk
        zone_urgent = (not in_zone) or dz_now > -8 or (need > 0 and t + need + 12 > zone["shrink_end"]) or not self.in_safe(x, y, 4)

        # --- threats: only enemies that are actually after us (they shot us, aim at us, or are close).
        # House bots that are not hunting walk past without shooting, so hiding from them wastes the
        # chance to fight the real hunter.
        threats = []   # attackers that can shoot us now
        known = []     # attackers seen recently
        for eid, e in self.enemies.items():
            ex, ey, ez = e["pos"]
            d = math.hypot(ex - x, ey - y)
            age = t - e["t"]
            if age > 8:
                continue
            if age < 0.6 and d < 200:
                to_me = math.atan2(y - ey, x - ex)
                if abs(wrap(fin(e["aim"][0]) - to_me)) < 0.15 or (e.get("charging") and abs(wrap(fin(e["aim"][0]) - to_me)) < 0.3):
                    self.attack_t[eid] = t
            hostile = t - self.attack_t.get(eid, -99) < 10
            if not hostile:
                continue
            known.append((d, eid, e))
            if age < 0.6 and d < 285:
                los = w.los(ex, ey, ez + 8, x, y, z + 5) if w else True
                if los:
                    threats.append((d, eid, e))
        threats.sort(key=lambda a: a[0])
        known.sort(key=lambda a: a[0])
        near_known = [k for k in known if k[0] < 170]
        low = hp < 0.42 * mhp
        hurt_recent = t - self.last_dmg_t < 2.5

        # --- choose mode
        mode = "travel"
        target = None
        if threats:
            lone = len(threats) == 1 and len(near_known) <= 1
            d0, tid, te = threats[0]
            winning = te["hp"] < hp * 1.15 or te["hp"] < 450
            if lone and (not low or te["hp"] < 350) and (winning or d0 < 60):
                mode = "fight"
                target = (tid, te)
            else:
                mode = "hide"
        elif hurt_recent and (self.last_dmg_by is not None or self.last_dmg_bearing is not None):
            mode = "hide"
        if zone_urgent and mode != "fight":
            mode = "zone" if mode != "hide" or not in_zone else "hide"
        if not in_zone and mode == "fight" and dz_now > 10:
            mode = "zone"
        self.mode = mode

        # --- movement
        move = None
        boost = False
        gx, gy = self._strategic_goal(zone, x, y, t0)
        if mode == "zone":
            move = self._nav_to(gx, gy, x, y, t0)
            boost = (not in_zone) or dz_now > -3 or me.get("energy", 0) > 60
        elif mode == "hide":
            move, boost = self._hide(x, y, z, t, known, threats, t0)
        elif mode == "fight":
            move = self._fight_move(x, y, target, t, gx, gy)
        else:
            loot = self._loot(obs, x, y, z, known, t)
            farm = None
            if loot is None and P["farm"]:
                farm = self._farm(obs, me, x, y, z, known, t, t0)
            if loot is not None:
                move = loot
            elif farm is not None:
                move, self.farm_shot = farm
            else:
                dg = math.hypot(gx - x, gy - y)
                if dg > 3.0:
                    move = self._nav_to(gx, gy, x, y, t0)
                    if dg < 10:
                        move = [move[0] * dg / 10, move[1] * dg / 10]
                else:
                    move = [0.0, 0.0]
        if move is None:
            move = [0.0, 0.0]
        move = self._avoid_walls(x, y, move)
        move, jump, b2 = self._unstick(x, y, vx, vy, move, t, me)
        boost = boost or b2

        # --- aiming and firing
        shoot = self._pick_shot(obs, me, x, y, z, seen, target, mode)
        if shoot is None and self.farm_shot is not None:
            shoot = self.farm_shot
        self.farm_shot = None
        if shoot is not None:
            act.update(shoot)
        else:
            act["aim"] = self._idle_aim(x, y, move, known, t)
            if self.crate_target is not None:
                pass
            # top up the gun when nothing is around
            g0 = me["weapons"][0] if me.get("weapons") else None
            if g0 and g0.get("kind") == "gun" and not threats and g0.get("ammo", 99) < g0.get("stats", {}).get("mag", 12) * 0.5 and not g0.get("reload", 0):
                act["reload"] = True
        # laser: keep holding while charging toward a target, else let go
        # (handled inside _pick_shot)

        # --- pickups within reach
        tk = self._take(obs, me, x, y)
        if tk:
            act.update(tk)

        act["move"] = move
        act["boost"] = bool(boost) and me.get("energy", 0) > 8
        act["debug"] = {"label": mode}
        if jump:
            act["jump"] = True
        return act

    # ------------------------------------------------------------ strategy goal
    def _strategic_goal(self, zone, x, y, t0):
        cx, cy = zone["next_center"]
        r = zone["next_radius"]
        key = (round(cx, 1), round(cy, 1), round(r, 1))
        if self.hold is None or key != self.hold_key:
            if time.perf_counter() - t0 < 0.010 or self.hold is None:
                self.hold = self._pick_hold(cx, cy, r, x, y)
                self.hold_key = key
        return self.hold

    def _pick_hold(self, cx, cy, r, x, y):
        w = self.w
        if w is None:
            return (cx, cy)
        rad = max(6.0, min(r * 0.45, r - 12.0))
        best, bs = None, -1e18
        N = w.N
        step = 1 if rad < 60 else 2
        i0 = int((cx - rad - w.minx) / N)
        i1 = int((cx + rad - w.minx) / N)
        j0 = int((cy - rad - w.miny) / N)
        j1 = int((cy + rad - w.miny) / N)
        for j in range(max(2, j0), min(w.ny - 2, j1 + 1), step):
            for i in range(max(2, i0), min(w.nx - 2, i1 + 1), step):
                c = j * w.nx + i
                if not w.free[c]:
                    continue
                px, py = w.ncenter(c)
                dc = math.hypot(px - cx, py - cy)
                if dc > rad:
                    continue
                s = w.cover[c] * 4.0 - dc * (0.25 if r < 100 else 0.08) - math.hypot(px - x, py - y) * 0.01
                if s > bs:
                    bs, best = s, (px, py)
        return best if best else (cx, cy)

    # ------------------------------------------------------------ navigation
    def _nav_to(self, gx, gy, x, y, t0):
        w = self.w
        yaw = math.atan2(gy - y, gx - x)
        direct = [math.cos(yaw), math.sin(yaw)]
        if w is None:
            return direct
        if math.hypot(gx - x, gy - y) < 30 and w.clear_path(x, y, gx, gy, 1.5):
            return direct
        if self.flow is None or self.flow_goal is None or math.hypot(self.flow_goal[0] - gx, self.flow_goal[1] - gy) > 8:
            self.flow = FlowField(w, gx, gy)
            self.flow_goal = (gx, gy)
        f = self.flow
        if not f.done:
            # build the field in slices to stay inside the tick budget
            while not f.done and time.perf_counter() - t0 < 0.005:
                f.work(1500)
        wp = f.waypoint(x, y) if f.done or f.dist[max(0, w.ncell(x, y))] >= 0 else None
        if wp is None:
            return direct
        yaw = math.atan2(wp[1] - y, wp[0] - x)
        return [math.cos(yaw), math.sin(yaw)]

    def _avoid_walls(self, x, y, move):
        w = self.w
        n = math.hypot(move[0], move[1])
        if w is None or n < 0.05:
            return move
        yaw = math.atan2(move[1], move[0])
        if w.free_dist(x, y, yaw, 5.0, 1.0) >= 4.0:
            return move
        for k in (1, -1, 2, -2, 3, -3, 4, -4):
            a = yaw + k * 0.35
            if w.free_dist(x, y, a, 5.0, 1.0) >= 4.0:
                return [math.cos(a) * n, math.sin(a) * n]
        return move

    def _unstick(self, x, y, vx, vy, move, t, me):
        n = math.hypot(move[0], move[1])
        sp = math.hypot(vx, vy)
        jump = boost = False
        if t < self.unstick_until:
            a = self.unstick_yaw
            return [math.cos(a), math.sin(a)], me.get("grounded", True), True
        if n > 0.5 and sp < 1.5:
            if self.stuck_since is None:
                self.stuck_since = t
            elif t - self.stuck_since > 0.8:
                self.stuck_since = None
                self.unstick_until = t + 0.9
                self.unstick_yaw = math.atan2(move[1], move[0]) + self.rng.choice((1.3, -1.3, 2.4, -2.4))
                return move, True, True
        else:
            self.stuck_since = None
        return move, jump, boost

    # ------------------------------------------------------------ hiding
    def _hide(self, x, y, z, t, known, threats, t0):
        w = self.w
        srcs = [(e["pos"][0], e["pos"][1], e["pos"][2] + 8) for d, _, e in known if d < 300]
        if not srcs and self.last_dmg_bearing is not None:
            b = self.last_dmg_bearing
            srcs = [(x + math.cos(b) * 80, y + math.sin(b) * 80, z + 8)]
        boost = bool(threats) and t - self.last_dmg_t < 3
        if w is None or not srcs:
            return [0.0, 0.0], False

        def exposed(px, py, pz):
            n = 0
            for sx, sy, sz in srcs:
                if w.los(sx, sy, sz, px, py, pz + 6, 2.0):
                    n += 1
            return n

        # already covered? hold here and let HP regenerate
        if exposed(x, y, z) == 0:
            self.hide_pt = (x, y)
            self.hide_t = t
            return [0.0, 0.0], False
        # keep a recent good hiding point
        if self.hide_pt and t - self.hide_t < 1.5:
            hx, hy = self.hide_pt
            if math.hypot(hx - x, hy - y) > 1.5 and self.in_safe(hx, hy, 2):
                yaw = math.atan2(hy - y, hx - x)
                return [math.cos(yaw), math.sin(yaw)], boost
        # search a ring of candidates
        mx = sum(s[0] for s in srcs) / len(srcs)
        my = sum(s[1] for s in srcs) / len(srcs)
        away = math.atan2(y - my, x - mx)
        best, bs = None, 1e18
        for r in (7.0, 14.0, 22.0, 32.0, 45.0):
            for k in range(16):
                if time.perf_counter() - t0 > 0.008:
                    break
                a = away + (k - 8) * (math.pi / 8)
                px, py = x + math.cos(a) * r, y + math.sin(a) * r
                c = w.ncell(px, py)
                if c < 0 or not w.free[c]:
                    continue
                if not self.in_safe(px, py, 5):
                    continue
                if not w.clear_path(x, y, px, py, 1.5):
                    continue
                pz = w.ground(px, py)
                e = exposed(px, py, pz)
                s = e * 200 + r - math.cos(a - away) * 6
                if s < bs:
                    bs, best = s, (px, py)
            if best is not None and bs < 100:
                break
        if best is None:
            yaw = away
            return [math.cos(yaw), math.sin(yaw)], boost
        self.hide_pt = best
        self.hide_t = t
        yaw = math.atan2(best[1] - y, best[0] - x)
        return [math.cos(yaw), math.sin(yaw)], boost

    # ------------------------------------------------------------ fighting
    def _fight_move(self, x, y, target, t, gx, gy):
        tid, te = target
        ex, ey = te["pos"][0], te["pos"][1]
        d = math.hypot(ex - x, ey - y)
        to = math.atan2(ey - y, ex - x)
        if t > self.strafe_until:
            self.strafe = -self.strafe if self.rng.random() < 0.7 else self.strafe
            self.strafe_until = t + 0.6 + self.rng.random() * 0.9
        side = to + self.strafe * math.pi / 2
        mx, my = math.cos(side), math.sin(side)
        theirs = te.get("weapons") or []
        want = 70.0
        if "lightning" in theirs:
            want = 90.0
        if d < want * 0.6:
            mx -= math.cos(to) * 0.7
            my -= math.sin(to) * 0.7
        elif d > want * 2.2:
            mx += math.cos(to) * 0.4
            my += math.sin(to) * 0.4
        # stay in the zone
        if not self.in_safe(x + mx * 8, y + my * 8, 4):
            a = math.atan2(gy - y, gx - x)
            mx, my = mx * 0.3 + math.cos(a), my * 0.3 + math.sin(a)
        return [mx, my]

    # ------------------------------------------------------------ loot (only when safe)
    def _loot(self, obs, x, y, z, known, t):
        self.crate_target = None
        if any(d < 160 for d, _, _ in known) or t - self.last_dmg_t < 6:
            return None
        me = obs["self"]
        best, bd = None, 55.0
        for c in obs.get("cubes", []) or []:
            px, py, pz = c["pos"]
            d = math.hypot(px - x, py - y)
            if d < bd and abs(pz - z) < 3.5 and self.in_safe(px, py, 8):
                bd, best = d, (px, py)
        wsl = me.get("weapons") or [None, None]
        cur1 = wsl[1]["kind"] if len(wsl) > 1 and wsl[1] else None
        for p in obs.get("pickups", []) or []:
            k = p.get("kind")
            if k == "gun" or k == cur1:
                continue
            if cur1 and WEAPON_RANK.get(k, 0) <= WEAPON_RANK.get(cur1, 0):
                continue
            px, py, pz = p["pos"]
            d = math.hypot(px - x, py - y)
            if d < bd + 15 and abs(pz - z) < 3.5 and self.in_safe(px, py, 8):
                bd, best = d, (px, py)
        if best is None:
            return None
        if self.w is not None and bd > 6 and not self.w.clear_path(x, y, best[0], best[1], 1.5):
            return None
        yaw = math.atan2(best[1] - y, best[0] - x)
        s = 1.0 if bd > 4 else 0.5
        return [math.cos(yaw) * s, math.sin(yaw) * s]

    # ------------------------------------------------------------ farming cubes (only when safe)
    def _farm(self, obs, me, x, y, z, known, t, t0):
        """Break crates and kill NPC drones for power cubes when no attacker is around.
        Returns (move, shot) or None."""
        if any(d < 150 for d, _, _ in known) or t - self.last_dmg_t < 5 or not self.in_safe(x, y, 15):
            return None
        w = self.w
        wsl = me.get("weapons") or []
        gun = wsl[0] if wsl and wsl[0] and wsl[0].get("kind") == "gun" else None
        if gun is None:
            return None
        hp_ok = me["hp"] > P["npc_hp"] * max(1.0, me["max_hp"])
        best, bs = None, 1e9
        for c in obs.get("crates", []) or []:
            px, py, pz = c["pos"]
            if abs(pz - z) > 3.0:
                continue
            d = math.hypot(px - x, py - y)
            if d > P["farm_r"] or not self.in_safe(px, py, 12):
                continue
            if d < bs:
                bs, best = d, ("crate", c, d)
        if hp_ok:
            for m in obs.get("mechs", []) or []:
                if m.get("kind") != "npc":
                    continue
                px, py, pz = m["pos"]
                d = math.hypot(px - x, py - y)
                if d > P["farm_r"] or not self.in_safe(px, py, 12):
                    continue
                sc = d + 20 + fin(m.get("hp", 350)) * 0.05
                if sc < bs:
                    bs, best = sc, ("npc", m, d)
        if best is None:
            return None
        kind, o, d = best
        px, py, pz = o["pos"]
        tz = pz + (1.2 if kind == "crate" else 1.8)
        if kind == "npc":
            v = o.get("vel", [0, 0, 0])
            px, py, tz, _ = self._lead(x, y, self.muzzle, px, py, tz, v[0], v[1], 0.0, fin(gun.get("stats", {}).get("speed", 252), 252))
        clear = w is None or w.los(x, y, self.muzzle, px, py, tz, 1.5)
        yaw = math.atan2(py - y, px - x)
        pit = math.atan2(tz - self.muzzle, max(0.5, math.hypot(px - x, py - y)))
        aim = me.get("aim", [0, 0])
        fire = False
        if clear and gun.get("reload", 0) <= 0 and abs(wrap(aim[0] - yaw)) < max(0.01, math.atan2(0.9, d)) and abs(aim[1] - pit) < max(0.02, math.atan2(1.2, d)):
            fire = True
        # walk to a shooting spot: close in on crates (to grab the cube), keep 30 m from drones
        want = 6.0 if kind == "crate" else 30.0
        if not clear or d > want + 4:
            move = self._nav_to(o["pos"][0], o["pos"][1], x, y, t0)
        elif kind == "npc" and d < want - 8:
            move = [-math.cos(yaw), -math.sin(yaw)]
        else:
            move = [0.0, 0.0]
        return move, {"aim": [yaw, pit], "fire": [fire, False]}

    def _take(self, obs, me, x, y):
        wsl = me.get("weapons") or [None, None]
        cur1 = wsl[1]["kind"] if len(wsl) > 1 and wsl[1] else None
        if cur1 == "laser" and wsl[1].get("charge", 0) > 0:
            return None
        best, br = None, -1
        for p in obs.get("pickups", []) or []:
            k = p.get("kind")
            if k == "gun" or k == cur1:
                continue
            if math.hypot(p["pos"][0] - x, p["pos"][1] - y) > self.reach - 0.3 or abs(p["pos"][2] - self.z) > 3.8:
                continue
            r = WEAPON_RANK.get(k, 0)
            if r > br:
                br, best = r, p
        if best is None:
            return None
        if cur1 is None:
            return {"take": best["id"]}
        if br > WEAPON_RANK.get(cur1, 0):
            return {"take": best["id"], "drop": 1}
        return None

    # ------------------------------------------------------------ aiming
    def _idle_aim(self, x, y, move, known, t):
        if known:
            d, _, e = known[0]
            return [math.atan2(e["pos"][1] - y, e["pos"][0] - x), 0.0]
        if self.last_dmg_bearing is not None and t - self.last_dmg_t < 8:
            return [self.last_dmg_bearing, 0.0]
        if math.hypot(move[0], move[1]) > 0.3:
            return [math.atan2(move[1], move[0]), 0.0]
        self.scan += 0.25
        return [self.scan, 0.0]

    def _lead(self, mx, my, mz, tx, ty, tz, vx, vy, vz, s):
        dx, dy, dz = tx - mx, ty - my, tz - mz
        a = vx * vx + vy * vy + vz * vz - s * s
        b = 2 * (dx * vx + dy * vy + dz * vz)
        c = dx * dx + dy * dy + dz * dz
        tt = None
        if abs(a) < 1e-6:
            if abs(b) > 1e-6:
                tt = -c / b
        else:
            disc = b * b - 4 * a * c
            if disc >= 0:
                sq = math.sqrt(disc)
                cands = [r for r in ((-b - sq) / (2 * a), (-b + sq) / (2 * a)) if r > 0]
                if cands:
                    tt = min(cands)
        if tt is None or tt <= 0:
            tt = math.sqrt(c) / s
        return tx + vx * tt, ty + vy * tt, tz + vz * tt, tt

    def _pick_shot(self, obs, me, x, y, z, seen, target, mode):
        w = self.w
        wsl = me.get("weapons") or []
        aim = me.get("aim", [0, 0])
        # candidate targets: visible mechs with a clear line from our muzzle
        cands = []
        for eid, m in seen.items():
            ex, ey, ez = m["pos"]
            d = math.hypot(ex - x, ey - y)
            if d > 285:
                continue
            sc = 1 + 0.05 * fin(m.get("cubes", 0))
            cz = ez + 4.5 * sc
            if w is not None and not w.los(x, y, self.muzzle, ex, ey, cz, 1.5):
                continue
            pri = d + (0 if target and eid == target[0] else 60) + fin(m.get("hp", 1400)) * 0.03
            if self.t - self.attack_t.get(eid, -99) < 10:
                pri -= 300   # the mechs actually shooting at us come first
            cands.append((pri, eid, m, d, cz))
        if not cands:
            # release a charging laser rather than walk at half speed
            return None
        cands.sort(key=lambda c: c[0])
        _, eid, m, d, cz = cands[0]
        ex, ey, ez = m["pos"]
        v = m.get("vel", [0, 0, 0])
        vz = v[2] if abs(v[2]) < 15 else 0.0
        fire = [False, False]
        out_aim = None
        ayaw, apit = aim[0], aim[1]
        for slot, wo in enumerate(wsl[:2]):
            if not wo:
                continue
            k = wo.get("kind")
            st = wo.get("stats", {})
            if k == "gun":
                rng = fin(st.get("range", 230), 230)
                if d > rng * 0.97:
                    continue
                spd = fin(st.get("speed", 252), 252)
                px, py, pz, tt = self._lead(x, y, self.muzzle, ex, ey, cz, v[0], v[1], vz * 0.5, spd)
                dyaw = math.atan2(py - y, px - x)
                dpit = math.atan2(pz - self.muzzle, math.hypot(px - x, py - y))
                if out_aim is None:
                    out_aim = [dyaw, dpit]
                tol = max(0.006, math.atan2(1.6, d))
                if abs(wrap(ayaw - dyaw)) < tol and abs(apit - dpit) < max(0.012, math.atan2(2.6, d)) and wo.get("reload", 0) <= 0:
                    if w is None or w.los(x, y, self.muzzle, px, py, pz, 1.5):
                        fire[slot] = True
            elif k == "laser":
                rng = fin(st.get("range", 280), 280)
                full = fin(st.get("charge", 0.75), 0.75)
                ch = fin(wo.get("charge", 0))
                dyaw = math.atan2(ey - y, ex - x)
                dpit = math.atan2(cz - self.muzzle, d)
                if out_aim is None:
                    out_aim = [dyaw, dpit]
                if d > rng * 0.97:
                    continue
                if wo.get("cooldown", 0) > 0.25 and ch <= 0:
                    continue
                aimed = abs(wrap(ayaw - dyaw)) < max(0.006, math.atan2(1.5, d)) and abs(apit - dpit) < max(0.012, math.atan2(2.5, d))
                if ch < full - 0.02:
                    fire[slot] = True        # keep charging
                elif not aimed:
                    fire[slot] = True        # hold until on target
                else:
                    fire[slot] = False       # let go: fire
            elif k == "lightning":
                rng = fin(st.get("range", 45), 45)
                cone = math.radians(fin(st.get("cone_deg", 30), 30)) * 0.5
                dyaw = math.atan2(ey - y, ex - x)
                if out_aim is None:
                    out_aim = [dyaw, math.atan2(cz - self.muzzle, d)]
                if d < rng * 0.95 and abs(wrap(ayaw - dyaw)) < cone * 0.8 and me.get("energy", 0) > fin(st.get("energy", 3), 3) + 12:
                    fire[slot] = True
            elif k == "mortar":
                if d < 28 or d > 225:
                    continue
                sol = self._mortar(x, y, z, ex, ey, ez, v, st, me)
                if sol is None:
                    continue
                dyaw, dpit = sol
                if out_aim is None or (mode != "fight" and fire == [False, False]):
                    pass
                if abs(wrap(ayaw - dyaw)) < 0.03 and abs(apit - dpit) < 0.03 and wo.get("cooldown", 0) <= 0:
                    fire[slot] = True
                if out_aim is None:
                    out_aim = [dyaw, dpit]
        if out_aim is None:
            return None
        return {"aim": out_aim, "fire": fire}

    def _mortar(self, x, y, z, ex, ey, ez, v, st, me):
        spd = fin(st.get("speed", 72), 72)
        g = fin(st.get("gravity", 22), 22)
        h0 = z + fin(me.get("stats", {}).get("height", 9.0), 9.0) + 0.5
        tx, ty, tz = ex, ey, ez + 1.0
        th = None
        for _ in range(2):
            dx, dy = tx - x, ty - y
            d = math.hypot(dx, dy)
            h = tz - h0
            disc = spd ** 4 - g * (g * d * d + 2 * h * spd * spd)
            if disc < 0 or d < 1:
                return None
            th = math.atan2(spd * spd - math.sqrt(disc), g * d)
            tt = d / max(1e-3, spd * math.cos(th))
            tx, ty = ex + v[0] * tt * 0.8, ey + v[1] * tt * 0.8
        return math.atan2(ty - y, tx - x), th


if __name__ == "__main__":
    run(Bot)

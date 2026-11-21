"""BERRYBOY mech bot (mechfight/1). Baseline: the kit's example strategy in one file."""
import json
import math
import queue
import sys
import threading
import traceback

NAME = "BERRYBOY"


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def send(msg):
    sys.stdout.write(json.dumps(msg, separators=(",", ":"), allow_nan=False) + "\n")
    sys.stdout.flush()


def run(make_bot):
    q = queue.Queue()

    def reader():
        for line in sys.stdin:
            if line.strip():
                q.put(line)
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
            kind = msg.get("type")
            if kind == "hello":
                try:
                    bot = make_bot(msg)
                except Exception:
                    log(traceback.format_exc())
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
        action["tick"] = latest["tick"]
        try:
            send(action)
        except (TypeError, ValueError):
            send({"tick": latest["tick"], **last})


class Bot:
    def __init__(self, hello):
        self.reach = hello["config"]["loot"]["pickup_radius"]

    def act(self, obs):
        me = obs["self"]
        x, y, z = me["pos"]
        goal = obs["zone"]["next_center"]
        act = {}
        if obs["offer"]:
            act["pick"] = 0
        near = [p for p in obs["pickups"] if math.dist(p["pos"][:2], (x, y)) < self.reach]
        if me["weapons"][1] is None and near and near[0]["kind"] != "gun":
            act["take"] = near[0]["id"]
        enemies = sorted((m for m in obs["mechs"] if m["kind"] == "mech"), key=lambda m: math.dist(m["pos"], me["pos"]))
        yaw = math.atan2(goal[1] - y, goal[0] - x)
        act.update(move=[math.cos(yaw), math.sin(yaw)], aim=[yaw, 0.0], boost=not me["in_zone"], jump=obs["tick"] % 40 == 0)
        if enemies:
            t = enemies[0]["pos"]
            aim = [math.atan2(t[1] - y, t[0] - x), math.atan2(t[2] - z - 2.5, math.dist(t[:2], (x, y)))]
            act.update(aim=aim, fire=[True, True])
        return act


if __name__ == "__main__":
    run(Bot)

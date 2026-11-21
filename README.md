# mech-royale-bot (Team BERRYBOY)

Bot for the Builders Buildathon Mech Royale track: `mechfight/1` protocol, Python 3.13, standard library only.

- `Dockerfile`: the image the scorer builds. The base image is pinned by exact version and digest; there are no pip dependencies.
- `bot.py`: the bot (protocol loop and strategy in one file).
- `SUBMISSIONS.md`: score log for each submission.

Check it with the kit's conformance test, run from the kit folder:

```sh
docker build -t my-bot /path/to/mech-royale-bot
python3 check/check.py --map-dir /arena -- docker run --rm -i --network none --cpus 1 --memory 512m --read-only --tmpfs /tmp:rw,size=64m --user 65534:65534 -v "$PWD/arena:/arena:ro" my-bot
```

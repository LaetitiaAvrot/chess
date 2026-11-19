#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://api.chess.com/pub/player/{user}"
UA = os.environ.get("CHESS_COM_UA", "chess-stat/1.0 (github.com/chess-stat)")
DRAW_CODES = {"agreed", "repetition", "stalemate", "insufficient", "fiftymove", "timevsinsufficient"}


def get_json(url, retries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode())
        except Exception as e:
            if attempt == retries - 1:
                raise
            time.sleep(2 * (attempt + 1))


def eco_name(eco_url):
    if not eco_url:
        return None
    return eco_url.rstrip("/").split("/")[-1].replace("-", " ")


def termination(pgn):
    m = re.search(r'\[Termination "([^"]+)"\]', pgn)
    return m.group(1) if m else None


def outcome(my_result):
    if my_result == "win":
        return "win"
    if my_result in DRAW_CODES:
        return "draw"
    return "loss"


def parse_record(g):
    w, b = g["white"], g["black"]
    pgn = g.get("pgn", "")
    return {
        "uuid": g.get("uuid"),
        "url": g.get("url"),
        "end_time": g.get("end_time"),
        "end_time_iso": datetime.fromtimestamp(g["end_time"], tz=timezone.utc).isoformat() if g.get("end_time") else None,
        "time_class": g.get("time_class"),
        "time_control": g.get("time_control"),
        "rated": g.get("rated"),
        "rules": g.get("rules"),
        "eco": g.get("eco"),
        "opening": eco_name(g.get("eco")),
        "termination": termination(pgn),
        "white": {"username": w["username"], "rating": w["rating"], "result": w["result"]},
        "black": {"username": b["username"], "rating": b["rating"], "result": b["result"]},
        "accuracies": g.get("accuracies"),
        "outcome_white": outcome(w["result"]),
        "outcome_black": outcome(b["result"]),
        "pgn": pgn,
    }


def month_url(u):
    m = re.search(r"/games/(\d{4})/(\d{2})$", u)
    return (int(m.group(1)), int(m.group(2))) if m else (0, 0)


def main():
    ap = argparse.ArgumentParser(description="Fetch Chess.com archives into a cached JSONL dataset.")
    ap.add_argument("user")
    ap.add_argument("--since", default="2010-01", help="YYYY-MM lower bound (default: all)")
    ap.add_argument("--datadir", default=None)
    args = ap.parse_args()

    user = args.user.lower()
    datadir = Path(args.datadir) if args.datadir else Path(__file__).resolve().parent.parent / "data"
    cache = datadir / "cache" / user
    cache.mkdir(parents=True, exist_ok=True)
    outfile = datadir / f"games-{user}.jsonl"

    now = datetime.now(timezone.utc)
    since_y, since_m = (int(x) for x in args.since.split("-"))
    # Incremental refetch window: every month from the latest game we already
    # have to now (falls back to --since for a brand-new user).
    latest = None
    if outfile.exists():
        for l in outfile.read_text().splitlines():
            if not l.strip():
                continue
            et = json.loads(l).get("end_time")
            if et and (latest is None or et > latest):
                latest = et
    if latest:
        ld = datetime.fromtimestamp(latest, tz=timezone.utc)
        refetch_from = (ld.year, ld.month)
    else:
        refetch_from = (since_y, since_m)

    archives = get_json(BASE.format(user=user) + "/games/archives")["archives"]
    archives = [u for u in archives if month_url(u) >= (since_y, since_m)]
    fetched = skipped = 0
    for url in archives:
        y, m = month_url(url)
        f = cache / f"{y}-{m:02d}.json"
        if f.exists() and (y, m) < refetch_from:
            skipped += 1
            continue
        try:
            data = get_json(url)
        except Exception as e:
            print(f"warn: {url}: {e}", file=sys.stderr)
            continue
        f.write_text(json.dumps(data, ensure_ascii=False))
        fetched += 1
        time.sleep(0.15)

    total = 0
    with outfile.open("w", encoding="utf-8") as out:
        for f in sorted(cache.glob("*.json")):
            for g in json.loads(f.read_text())["games"]:
                out.write(json.dumps(parse_record(g), ensure_ascii=False) + "\n")
                total += 1
    print(f"user={user} refetch_from={refetch_from[0]}-{refetch_from[1]:02d} archives_fetched={fetched} archives_cached={skipped} games_written={total} -> {outfile}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Review every game of a user with Stockfish, resumable, losses first.

Usage: python3 scripts/review_all.py <user> [--depth 12] [--color white|black]
Skips games that already have a moves-<user>.jsonl record at the requested
depth, so the run can be interrupted and relaunched safely.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--depth", type=int, default=12)
    args = ap.parse_args()
    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = [g for g in games if g.get("rules") == "chess"]
    have = set()
    moves_path = datadir / f"moves-{me}.jsonl"
    if moves_path.exists():
        for l in moves_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                if r["depth"] == args.depth:
                    have.add(r["uuid"])
    losses, others = [], []
    for g in sorted(games, key=lambda x: -x["end_time"]):
        mine = "white" if g["white"]["username"].lower() == me else "black"
        tgt = losses if g[f"outcome_{mine}"] == "loss" else others
        tgt.append(g["uuid"])
    todo = [u for u in losses + others if u not in have]
    print(f"{len(todo)} games to review (depth {args.depth}), {len(have)} already done", flush=True)
    for i, uuid in enumerate(todo, 1):
        r = subprocess.run([sys.executable, str(Path(__file__).parent / "review_moves.py"), me,
                            "--uuid", uuid, "--depth", str(args.depth)],
                           capture_output=True, text=True)
        if r.returncode != 0:
            print(f"FAIL {uuid}: {r.stderr.strip()[:200]}", flush=True)
        if i % 25 == 0 or i == len(todo):
            print(f"{i}/{len(todo)}", flush=True)
    print("done", flush=True)


if __name__ == "__main__":
    main()

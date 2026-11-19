#!/usr/bin/env python3
import argparse
import json
import math
import re
import shutil
import statistics
import sys
from collections import defaultdict
from io import StringIO
from pathlib import Path

import chess
import chess.engine
import chess.pgn

WP_K = 0.00368208


def find_engine():
    p = shutil.which("stockfish") or str(Path.home() / ".local/bin/stockfish")
    if not Path(p).exists():
        sys.exit("stockfish binary not found (looked in PATH and ~/.local/bin)")
    return p


def win_pct(score, pov):
    s = score.pov(pov)
    if s.is_mate():
        return 100.0 if s.mate() > 0 else 0.0
    return 100.0 / (1.0 + math.exp(-WP_K * max(-1000, min(1000, s.score()))))


def move_accuracy(dwp):
    return max(0.0, min(100.0, 103.1668 * math.exp(-0.04354 * dwp) - 3.1669))


def analyze_opening_phase(g, engine, depth, plies):
    game = chess.pgn.read_game(StringIO(g["pgn"]))
    if game is None:
        return None
    board = game.board()
    info = engine.analyse(board, chess.engine.Limit(depth=depth))
    accs = {"white": [], "black": []}
    worst = {"white": (0, None), "black": (0, None)}
    for node in list(game.mainline())[:plies]:
        if node.move is None:
            break
        mover = board.turn
        color = "white" if mover == chess.WHITE else "black"
        best = info.get("pv", [None])[0]
        best_san = board.san(best) if best else None
        played_san = node.san()
        wp_before = win_pct(info["score"], mover)
        board.push(node.move)
        info = engine.analyse(board, chess.engine.Limit(depth=depth))
        wp_after = win_pct(info["score"], mover)
        d = max(0.0, wp_before - wp_after)
        a = move_accuracy(d)
        accs[color].append(a)
        if d > worst[color][0]:
            worst[color] = (d, f"{played_san} (best {best_san}, -{d:.0f}% win)")
    out = {}
    for c in ("white", "black"):
        out[c] = round(statistics.mean(accs[c]), 2) if accs[c] else None
        out[f"worst_{c}"] = worst[color][1] if worst[color][0] >= 10 else None
    return out


def main():
    ap = argparse.ArgumentParser(description="Opening-phase accuracy (first N plies) per game and per opening, cached locally.")
    ap.add_argument("user")
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--plies", type=int, default=24, help="opening phase length in plies (default 24 = 12 moves)")
    ap.add_argument("--refresh", action="store_true", help="re-analyze games already cached")
    ap.add_argument("--limit", type=int, default=None, help="analyze at most N games (testing)")
    ap.add_argument("--min-games", type=int, default=2)
    args = ap.parse_args()

    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = [g for g in games if g.get("rules") == "chess"]
    games.sort(key=lambda g: g["end_time"])
    eco_re = re.compile(r'\[ECO "([A-Z]\d{2})"\]')
    for g in games:
        m = eco_re.search(g.get("pgn") or "")
        g["eco_code"] = m.group(1) if m else None

    cache_path = datadir / f"opening-phase-{me}.jsonl"
    cache = {}
    if cache_path.exists():
        for line in cache_path.read_text().splitlines():
            if line.strip():
                r = json.loads(line)
                cache[r["uuid"]] = r

    todo = [g for g in games if args.refresh or g["uuid"] not in cache]
    if args.limit:
        todo = todo[: args.limit]
    if todo:
        engine = chess.engine.SimpleEngine.popen_uci(find_engine())
        engine.configure({"Threads": 2, "Hash": 256})
        try:
            for i, g in enumerate(todo):
                try:
                    res = analyze_opening_phase(g, engine, args.depth, args.plies)
                except Exception as e:
                    print(f"warn: {g['uuid']}: {e}", file=sys.stderr)
                    continue
                if res is None:
                    continue
                cache[g["uuid"]] = {"uuid": g["uuid"], "end_time": g["end_time"], "plies": args.plies, "depth": args.depth, **res}
                if (i + 1) % 25 == 0:
                    print(f"analyzed {i + 1}/{len(todo)}", file=sys.stderr)
                    with cache_path.open("w") as f:
                        for r in cache.values():
                            f.write(json.dumps(r, ensure_ascii=False) + "\n")
        finally:
            engine.quit()
        with cache_path.open("w") as f:
            for r in cache.values():
                f.write(json.dumps(r, ensure_ascii=False) + "\n")

    by_opening = defaultdict(lambda: {"me": [], "opp": []})
    overall = {"me": [], "opp": []}
    for g in games:
        r = cache.get(g["uuid"])
        if not r:
            continue
        me_white = g["white"]["username"].lower() == me
        my_color, opp_color = ("white", "black") if me_white else ("black", "white")
        key = (my_color, g["eco_code"] or "???")
        if r[my_color] is not None:
            by_opening[key]["me"].append(r[my_color])
            by_opening[key]["opp"].append(r[opp_color])
            overall["me"].append(r[my_color])
            overall["opp"].append(r[opp_color])

    print(f"# Opening-phase accuracy (first {args.plies} plies, local Stockfish depth {args.depth}) — {me}")
    print(f"_games analyzed: {len(overall['me'])} of {len(games)}_")
    print(f"- overall: mine {statistics.mean(overall['me']):.1f} vs opponents {statistics.mean(overall['opp']):.1f}")
    for color in ("white", "black"):
        print(f"\n## As {color}")
        print("| ECO | games | acc-open (me) | acc-open (opp) |")
        print("|---|---|---|---|")
        keys = [k for k in by_opening if k[0] == color and len(by_opening[k]["me"]) >= args.min_games]
        keys.sort(key=lambda k: -len(by_opening[k]["me"]))
        for key in keys:
            s = by_opening[key]
            print(f"| {key[1]} | {len(s['me'])} | {statistics.mean(s['me']):.1f} | {statistics.mean(s['opp']):.1f} |")


if __name__ == "__main__":
    main()

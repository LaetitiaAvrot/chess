#!/usr/bin/env python3
import argparse
import json
import math
import shutil
import statistics
import sys
from collections import Counter
from io import StringIO
from pathlib import Path

import chess
import chess.engine
import chess.pgn

WP_K = 0.00368208
CLASSES = ["Forced", "Best", "Excellent", "Good", "Inaccuracy", "Mistake", "Blunder"]


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


def classify(d, played_is_best):
    if played_is_best:
        return "Best"
    if d <= 2:
        return "Excellent"
    if d <= 5:
        return "Good"
    if d <= 10:
        return "Inaccuracy"
    if d <= 20:
        return "Mistake"
    return "Blunder"


def analyze_game(g, engine, depth):
    game = chess.pgn.read_game(StringIO(g["pgn"]))
    if game is None:
        return None
    board = game.board()
    rows = []
    for node in game.mainline():
        move = node.move
        if move is None:
            continue
        mover = board.turn
        mv_number = board.fullmove_number
        mv_ply = board.ply()
        legal = list(board.legal_moves)
        pre = engine.analyse(board, chess.engine.Limit(depth=depth))
        wp_before = win_pct(pre["score"], mover)
        best = pre.get("pv", [None])[0]
        best_san = board.san(best) if best else None
        board.push(move)
        post = engine.analyse(board, chess.engine.Limit(depth=depth))
        wp_after = win_pct(post["score"], mover)
        d = max(0.0, wp_before - wp_after)
        cls = "Forced" if len(legal) <= 1 else classify(d, move == best)
        rows.append({
            "ply": mv_ply,
            "move_san": node.san() if hasattr(node, "san") else str(move),
            "move_number": mv_number,
            "color": "white" if mover == chess.WHITE else "black",
            "played": move.uci(),
            "best": best.uci() if best else None,
            "best_san": best_san,
            "wp_before": round(wp_before, 1),
            "wp_after": round(wp_after, 1),
            "loss": round(d, 1),
            "class": cls,
            "acc": round(move_accuracy(d), 1),
        })
    return rows


def summarize(rows, color):
    sel = [r for r in rows if r["color"] == color]
    if not sel:
        return None
    counts = Counter(r["class"] for r in sel)
    blunders = [
        {k: r[k] for k in ("move_number", "color", "move_san", "best_san", "wp_before", "wp_after", "loss", "class")}
        for r in sel if r["class"] in ("Blunder", "Mistake", "Inaccuracy")
    ]
    return {
        "accuracy": round(statistics.mean(r["acc"] for r in sel), 2),
        "acpl": round(statistics.mean(min(r["loss"] * 10, 1000) for r in sel)),
        "moves": len(sel),
        "counts": {c: counts.get(c, 0) for c in CLASSES},
        "worst": sorted(blunders, key=lambda x: -x["loss"]),
    }


def main():
    ap = argparse.ArgumentParser(description="Local Diamond-style move review with Stockfish.")
    ap.add_argument("user")
    ap.add_argument("--uuid", help="review one game by uuid")
    ap.add_argument("--last", type=int, default=1, help="review the N most recent games")
    ap.add_argument("--list", action="store_true", help="list games and exit")
    ap.add_argument("--pgn", help="review a raw PGN file (e.g. FIDE OTB game) instead of a chess.com game")
    ap.add_argument("--color", choices=["white", "black"], help="your side when using --pgn")
    ap.add_argument("--depth", type=int, default=12)
    ap.add_argument("--show-worst", type=int, default=5)
    args = ap.parse_args()

    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"

    if args.pgn:
        pgn_path = Path(args.pgn)
        raw = pgn_path.read_text()
        parsed = chess.pgn.read_game(StringIO(raw))
        if parsed is None:
            sys.exit(f"unparseable pgn: {pgn_path}")
        hdr = parsed.headers
        end_time = None
        if "UTCDate" in hdr and "UTCTime" in hdr:
            from datetime import datetime, timezone
            try:
                end_time = datetime.strptime(hdr["UTCDate"] + " " + hdr["UTCTime"], "%Y.%m.%d %H:%M:%S").replace(tzinfo=timezone.utc).timestamp()
            except ValueError:
                pass
        eco_url = hdr.get("ECOUrl")
        sel = [{
            "uuid": pgn_path.stem,
            "url": None,
            "end_time": end_time,
            "end_time_iso": datetime.fromtimestamp(end_time, tz=timezone.utc).isoformat() if end_time else "—",
            "time_class": "classical" if "TimeControl" not in hdr else hdr["TimeControl"],
            "time_control": hdr.get("TimeControl", "?"),
            "rated": None,
            "rules": "chess",
            "eco": hdr.get("ECO"),
            "opening": eco_url.rstrip("/").split("/")[-1].replace("-", " ") if eco_url else None,
            "termination": hdr.get("Termination", "?"),
            "white": {"username": hdr.get("White", "White"), "rating": int(hdr.get("WhiteElo", 0) or 0), "result": {"1-0": "win", "0-1": "loss"}.get(hdr.get("Result"), "draw")},
            "black": {"username": hdr.get("Black", "Black"), "rating": int(hdr.get("BlackElo", 0) or 0), "result": {"0-1": "win", "1-0": "loss"}.get(hdr.get("Result"), "draw")},
            "accuracies": None,
            "outcome_white": {"1-0": "win", "0-1": "loss"}.get(hdr.get("Result"), "draw"),
            "outcome_black": {"0-1": "win", "1-0": "loss"}.get(hdr.get("Result"), "draw"),
            "pgn": raw,
        }]
        games = []
    else:
        games_path = datadir / f"games-{me}.jsonl"
        if not games_path.exists():
            sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
        games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
        games = [g for g in games if g.get("rules") == "chess"]
        games.sort(key=lambda g: g["end_time"])

    if args.list:
        for i, g in enumerate(games):
            print(f"{i}: {g['end_time_iso'][:16]} {g['time_class']} {g['white']['username']} ({g['white']['rating']}) vs {g['black']['username']} ({g['black']['rating']}) uuid={g['uuid']}")
        return

    if args.pgn:
        pass
    elif args.uuid:
        sel = [g for g in games if g["uuid"] == args.uuid]
        if not sel:
            sys.exit(f"uuid {args.uuid} not found")
    else:
        sel = games[-args.last:]
    if not sel:
        sys.exit("no game selected")

    engine = chess.engine.SimpleEngine.popen_uci(find_engine())
    engine.configure({"Threads": 2, "Hash": 256})
    try:
        reviews_path = datadir / f"reviews-{me}.jsonl"
        previous = []
        if reviews_path.exists():
            previous = [json.loads(l) for l in reviews_path.read_text().splitlines() if l.strip()]
        uuids = {g["uuid"] for g in sel}
        previous = [r for r in previous if not (r["uuid"] in uuids and r["depth"] == args.depth)]
        new_records = []
        moves_path = datadir / f"moves-{me}.jsonl"
        prev_moves = []
        if moves_path.exists():
            prev_moves = [json.loads(l) for l in moves_path.read_text().splitlines() if l.strip()]
        prev_moves = [r for r in prev_moves if not (r["uuid"] in uuids and r["depth"] == args.depth)]
        for g in sel:
            w, b = g["white"], g["black"]
            rows = analyze_game(g, engine, args.depth)
            if rows is None:
                print(f"skip {g['uuid']}: unparseable pgn")
                continue
            prev_moves.append({"uuid": g["uuid"], "end_time": g["end_time"], "depth": args.depth, "moves": rows})
            rw, rb = summarize(rows, "white"), summarize(rows, "black")
            if args.color:
                me_white = args.color == "white"
            else:
                me_white = w["username"].lower() == me
            mine, theirs = (rw, rb) if me_white else (rb, rw)
            print(f"\n## {w['username']} ({w['rating']}) vs {b['username']} ({b['rating']}) — {g['end_time_iso'][:16]} — {g.get('termination')}")
            print(f"opening: {g.get('opening')}")
            print(f"- chess.com accuracy: {g['accuracies'] if g.get('accuracies') else 'not reviewed'}")
            print(f"- local accuracy: white {rw['accuracy']} / black {rb['accuracy']} (depth {args.depth})")
            print(f"- ACPL: white {rw['acpl']} / black {rb['acpl']}")
            for who, s in (("me", mine), ("opp", theirs)):
                if s:
                    print(f"- {who}: " + " | ".join(f"{c} {s['counts'][c]}" for c in CLASSES if s["counts"][c]))
            if mine:
                print(f"- my worst moves:")
                for mv in mine["worst"][: args.show_worst]:
                    print(f"  - {mv['move_number']}{'.' if mv['color'] == 'white' else '...'} {mv['move_san']} ({mv['class']}, -{mv['loss']} win%) — best {mv['best_san']}")
            rec = {"uuid": g["uuid"], "end_time": g["end_time"], "depth": args.depth,
                   "local_accuracy": {"white": rw["accuracy"], "black": rb["accuracy"]},
                   "acpl": {"white": rw["acpl"], "black": rb["acpl"]},
                   "counts": {"white": rw["counts"], "black": rb["counts"]},
                   "worst_moves": {"white": rw["worst"], "black": rb["worst"]}}
            new_records.append(rec)
    finally:
        engine.quit()
    if new_records or prev_moves:
        with reviews_path.open("w") as f:
            for r in previous:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
            for r in new_records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        with moves_path.open("w") as f:
            for r in prev_moves:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()

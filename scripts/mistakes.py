#!/usr/bin/env python3
"""ChessVibes lesson-2 style mistake spreadsheet from local game reviews.

Usage:
  python3 scripts/mistakes.py <user> [--all] [--out data/mistakes-<user>.csv]

Reads data/games-<user>.jsonl + data/reviews-<user>.jsonl, keeps the user's
losses (or every game with --all), and emits one row per game: the biggest
eval drop ("the mistake that lost the game"), its mechanical category, and
the other Blunder/Mistake moves of the same game.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from io import StringIO
from pathlib import Path

import chess
import chess.pgn

TACTIC_KEYS = ("fork", "pin", "discovered", "removes-defender", "trapped", "other", "sacrifice")

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}


def least_valuable_attacker(board, sq, color):
    attackers = list(board.attackers(color, sq))
    if not attackers:
        return None
    non_king = [s for s in attackers if board.piece_type_at(s) != chess.KING]
    pool = non_king or attackers
    return min(pool, key=lambda s: VAL[board.piece_type_at(s)])


def see(board, move):
    frm, to = move.from_square, move.to_square
    target = board.piece_type_at(to)
    if target is None:
        return 0
    b = board.copy(stack=False)
    chain = [VAL[target]]
    p = b.piece_at(frm)
    b.remove_piece_at(frm)
    b.set_piece_at(to, p)
    b.turn = not b.turn
    while True:
        atk = least_valuable_attacker(b, to, b.turn)
        if atk is None:
            break
        chain.append(VAL[b.piece_type_at(to)])
        q = b.piece_at(atk)
        b.remove_piece_at(atk)
        b.set_piece_at(to, q)
        b.turn = not b.turn
    d = len(chain) - 1
    Ss = [chain[0]]
    for k in range(1, d + 1):
        Ss.append(Ss[-1] + (-1) ** k * chain[k])
    V = Ss[d]
    for k in range(d - 1, -1, -1):
        V = min(Ss[k], V) if k % 2 == 0 else max(Ss[k], V)
    return V


def board_before_move(game, mv):
    board = game.board()
    for node in game.mainline():
        move = node.move
        if move is None:
            continue
        color = "white" if board.turn == chess.WHITE else "black"
        if (board.fullmove_number, color, node.san()) == (mv["move_number"], mv["color"], mv["move_san"]):
            return board, move
        board.push(move)
    return None, None


def mate_in_one(board):
    for m in board.legal_moves:
        board.push(m)
        mate = board.is_checkmate()
        board.pop()
        if mate:
            return True
    return False


def opp_promotion_threat(board_after, mover):
    """After her move: does the opponent have a passed pawn 1-2 squares from
    promotion, with a clear path and the push already available?"""
    enemy = not mover
    for sq, p in list(board_after.piece_map().items()):
        if p.color != enemy or p.piece_type != chess.PAWN:
            continue
        rank = chess.square_rank(sq)
        dist = 7 - rank if enemy == chess.WHITE else rank
        if dist not in (1, 2):
            continue
        step = 8 if enemy == chess.WHITE else -8
        path_ok = True
        passed = True
        path_sqs = []
        s = sq
        for _ in range(dist):
            s = s + step
            path_sqs.append(s)
            if board_after.piece_at(s):
                path_ok = False
                break
        if not path_ok:
            continue
        f = chess.square_file(sq)
        for df in (-1, 0, 1):
            if not 0 <= f + df <= 7:
                continue
            for rr in range(rank + (1 if enemy == chess.WHITE else -1),
                            (8 if enemy == chess.WHITE else -1),
                            (1 if enemy == chess.WHITE else -1)):
                blocker = board_after.piece_at(chess.square(f + df, rr))
                if blocker and blocker.piece_type == chess.PAWN and blocker.color != enemy:
                    passed = False
                    break
            if not passed:
                break
        if passed and chess.Move(sq, sq + step) in board_after.legal_moves:
            return True
    return False


def categorize(game, mv, last_wp=None, my_result=None, allowed=None, forced_mate=False):
    game_allowed = allowed or {}
    board, move = board_before_move(game, mv)
    if board is None:
        return "unparsed", "?"
    phase = phase_of(board, mv)
    if mv.get("best_san") and mv["best_san"].endswith("#"):
        return "missed mate", phase
    board_after = board.copy(stack=False)
    board_after.push(move)
    if opp_promotion_threat(board_after, board.turn):
        return "promotion oversight", phase
    if my_result == "timeout" and last_wp is not None and last_wp >= 32:
        return "time management", phase
    if my_result == "resigned" and last_wp is not None and last_wp >= 50:
        return "quitting too early", phase
    board_after = board.copy(stack=False)
    board_after.push(move)
    if mate_in_one(board_after):
        return "allowed-mate-in-1", phase
    if mv["move_number"] <= 6:
        return "opening mistake", phase
    if board.is_capture(move) and see(board, move) < 0:
        return "bad-capture", phase
    best_hang = 0
    for m in board_after.legal_moves:
        if board_after.is_capture(m):
            board_before_cap = board_after.copy(stack=False)
            best_hang = max(best_hang, see(board_before_cap, m))
    if best_hang >= 1:
        return "hung-piece", phase
    if forced_mate or my_result == "checkmated":
        return "missed mate", phase
    if any(game_allowed.get(k, 0) > 0 for k in TACTIC_KEYS):
        return "missed tactic", phase
    return "eval-drop", phase


def phase_of(board, mv):
    pieces = sum(1 for pt in board.piece_map().values() if pt.piece_type not in (chess.PAWN, chess.KING))
    if pieces <= 6:
        return "endgame"
    if mv["move_number"] <= 12:
        return "opening"
    return "middlegame"


def fmt_move(mv):
    dot = "." if mv["color"] == "white" else "..."
    return f"{mv['move_number']}{dot}{mv['move_san']}"


def main():
    ap = argparse.ArgumentParser(description="ChessVibes-style mistake spreadsheet from local reviews")
    ap.add_argument("user")
    ap.add_argument("--all", action="store_true", help="include wins and draws, not just losses")
    ap.add_argument("--out", default=None, help="output CSV path (default data/mistakes-<user>.csv)")
    args = ap.parse_args()
    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = {g["uuid"]: g for g in games if g.get("rules") == "chess"}
    reviews = {}
    reviews_path = datadir / f"reviews-{me}.jsonl"
    if not reviews_path.exists():
        sys.exit(f"no reviews for user '{me}' yet - run: make review USER={me}")
    for l in reviews_path.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["uuid"] not in reviews or r["depth"] > reviews[r["uuid"]]["depth"]:
            reviews[r["uuid"]] = r
    moves = {}
    moves_path = datadir / f"moves-{me}.jsonl"
    if moves_path.exists():
        for l in moves_path.read_text().splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r["uuid"] not in moves or r["depth"] > moves[r["uuid"]]["depth"]:
                moves[r["uuid"]] = r
    advanced = {}
    adv_path = datadir / f"advanced-{me}.jsonl"
    if adv_path.exists():
        for l in adv_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                advanced[r["uuid"]] = r.get("allowed", {})
    overrides = {}
    overrides_path = datadir / "category-overrides.json"
    if overrides_path.exists():
        overrides = json.loads(overrides_path.read_text())
    rows = []
    skipped_no_review = 0
    for uuid, g in sorted(games.items(), key=lambda kv: kv[1]["end_time"]):
        me_white = g["white"]["username"].lower() == me
        mine, theirs = ("white", "black") if me_white else ("black", "white")
        outcome = g[f"outcome_{mine}"]
        if not args.all and outcome == "win":
            continue
        rev = reviews.get(uuid)
        if rev is None:
            skipped_no_review += 1
            continue
        worst = rev["worst_moves"][mine]
        if not worst:
            rows.append({
                "game_id": uuid, "date": g["end_time_iso"][:10], "time_class": g["time_class"],
                "color": mine, "opponent": g[theirs]["username"], "opp_elo": g[theirs]["rating"],
                "opening": g.get("opening"), "result": outcome, "losing_move": "", "move_number": "",
                "phase": "", "category": "clean-scoreheet", "wp_before": "", "wp_after": "",
                "winpct_loss": "", "best_move": "", "other_mistakes": "", "url": g["url"],
            })
            continue
        losing = worst[0]
        parsed = chess.pgn.read_game(StringIO(g["pgn"]))
        last_wp = None
        mrows = moves.get(uuid, {}).get("moves", [])
        if mrows:
            last = mrows[-1]
            last_mover_is_me = last["color"] == mine
            last_wp = last["wp_after"] if last_mover_is_me else 100 - last["wp_after"]
        forced_mate = any(m["color"] == mine and m["wp_after"] == 0.0 for m in mrows)
        my_result = g[mine]["result"]
        category, phase = categorize(parsed, losing, last_wp, my_result, advanced.get(uuid), forced_mate) if parsed else ("unparsed", "?")
        live_id = (g["url"] or "").rstrip("/").split("/")[-1]
        if live_id in overrides:
            category = overrides[live_id]
        if category == "eval-drop" and parsed:
            board2 = parsed.board()
            seen_losing = False
            for node in parsed.mainline():
                mv2 = node.move
                if mv2 is None:
                    continue
                mover2 = board2.turn
                is_me = (mover2 == chess.WHITE) == me_white
                if is_me and seen_losing:
                    after = board2.copy(stack=False)
                    after.push(mv2)
                    if opp_promotion_threat(after, mover2):
                        category = "promotion oversight"
                        break
                if (board2.fullmove_number, "white" if mover2 == chess.WHITE else "black", node.san()) \
                        == (losing["move_number"], losing["color"], losing["move_san"]):
                    seen_losing = True
                board2.push(mv2)
        others = [m for m in worst[1:] if m["class"] in ("Blunder", "Mistake")]
        rows.append({
            "game_id": uuid, "date": g["end_time_iso"][:10], "time_class": g["time_class"],
            "color": mine, "opponent": g[theirs]["username"], "opp_elo": g[theirs]["rating"],
            "opening": g.get("opening"), "result": outcome,
            "losing_move": fmt_move(losing), "move_number": losing["move_number"],
            "phase": phase, "category": category,
            "wp_before": losing["wp_before"], "wp_after": losing["wp_after"],
            "winpct_loss": losing["loss"], "best_move": losing["best_san"],
            "other_mistakes": "; ".join(f"{fmt_move(m)} ({m['class']}, -{m['loss']})" for m in others[:3]),
            "url": g["url"],
        })
    out = Path(args.out) if args.out else datadir / f"mistakes-{me}.csv"
    with out.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()) if rows else [])
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {out} ({len(rows)} games)")
    if skipped_no_review:
        print(f"skipped {skipped_no_review} games without a local review (run scripts/review_moves.py on them first)")
    cats = Counter(r["category"] for r in rows)
    print("\ncategory counts:")
    for c, n in cats.most_common():
        print(f"  {n:3d}  {c}")
    phases = Counter(r["phase"] for r in rows if r["phase"])
    print("phase counts:")
    for c, n in phases.most_common():
        print(f"  {n:3d}  {c}")


if __name__ == "__main__":
    main()

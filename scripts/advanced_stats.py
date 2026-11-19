#!/usr/bin/env python3
"""Advanced per-game statistics (tactic motifs, strategy proxies, endgame stats).

Usage: python3 scripts/advanced_stats.py <user>
Reads games-<user>.jsonl + moves-<user>.jsonl (written by review_moves.py) and
appends data/advanced-<user>.jsonl with one record per game:

  tactics   — motifs found (played by the user) and allowed (played against her):
              fork, pin, discovered, removes-defender, trapped, free-piece,
              mate, sacrifice, other (skewer/x-ray)
  strategy  — local accuracy on move subsets (attack, defend, pawn, space, quiet)
  endgame   — reached?, type (kp/queen/rook/other), eval bucket at entry
              (better/equal/worse), outcome, accuracy overall and by theme
  game_type — open (1.e4 e5) / semi-open (1.e4) / closed

Definitions are journal-local approximations of chess.com Game Review buckets.
"""
import argparse
import json
import sys
from collections import Counter
from io import StringIO
from pathlib import Path

import chess
import chess.pgn

VAL = {chess.PAWN: 1, chess.KNIGHT: 3, chess.BISHOP: 3, chess.ROOK: 5, chess.QUEEN: 9, chess.KING: 100}
TACTICS = ("fork", "pin", "discovered", "removes-defender", "trapped", "free-piece", "mate", "sacrifice", "other")
STEPS = {8: (0, 1), -8: (0, -1), 1: (1, 0), -1: (-1, 0), 9: (1, 1), 7: (-1, 1), -9: (-1, -1), -7: (1, -1)}


def step_from(sq, step):
    f = chess.square_file(sq) + STEPS[step][0]
    r = chess.square_rank(sq) + STEPS[step][1]
    return chess.square(f, r) if 0 <= f <= 7 and 0 <= r <= 7 else None


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
        atks = [s for s in b.attackers(b.turn, to) if b.piece_type_at(s) != chess.KING]
        if not atks:
            break
        chain.append(VAL[b.piece_type_at(to)])
        src = min(atks, key=lambda s: VAL[b.piece_type_at(s)])
        q = b.piece_at(src)
        b.remove_piece_at(src)
        b.remove_piece_at(to)
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


def see_for(board, move, by_color):
    b = board.copy(stack=False)
    b.turn = by_color
    return see(b, move)


def attacks_higher(board, sq, by_color):
    p = board.piece_at(sq)
    n = 0
    for t in board.attacks(sq):
        tp = board.piece_at(t)
        if tp and tp.color != by_color and (tp.piece_type == chess.KING or VAL[tp.piece_type] > VAL[p.piece_type]):
            n += 1
    return n


def slider_behind(board, sq, color):
    """Friendly sliders aligned with sq (the moved piece's origin): the discoverers."""
    found = []
    for step in STEPS:
        s, dist = sq, 0
        while True:
            s = step_from(s, step)
            if s is None:
                break
            dist += 1
            p = board.piece_at(s)
            if not p:
                continue
            if p.color == color:
                diag = STEPS[step][0] != 0 and STEPS[step][1] != 0
                ok = (p.piece_type == chess.QUEEN
                      or (p.piece_type == chess.ROOK and not diag)
                      or (p.piece_type == chess.BISHOP and diag))
                if ok:
                    found.append((s, step))
            break
    return found


def attacks_higher_ignoring(board, from_sq, by_color, ignored_sq):
    """Does any slider of by_color attack high-value targets along rays through ignored_sq?"""
    for step in STEPS:
        s, blocked = from_sq, False
        while True:
            s = step_from(s, step)
            if s is None:
                break
            p = board.piece_at(s)
            if not p:
                continue
            if not blocked and s == ignored_sq:
                blocked = True
                continue
            if blocked and p.color != by_color:
                diag = STEPS[step][0] != 0 and STEPS[step][1] != 0
                slider = board.piece_at(from_sq)
                ok = slider.piece_type == chess.QUEEN or (slider.piece_type == chess.ROOK and not diag) or (slider.piece_type == chess.BISHOP and diag)
                if ok and (p.piece_type == chess.KING or VAL[p.piece_type] >= 3):
                    return True
                break
            break
    return False


def hanging_squares(board, by_color, min_gain=3):
    """Squares of by_color's pieces that the side to move can win with SEE >= min_gain."""
    out = set()
    for m in board.legal_moves:
        if not board.is_capture(m):
            continue
        v = board.piece_type_at(m.to_square)
        if v and VAL[v] >= 3 and see(board, m) >= min_gain:
            out.add(m.to_square)
    return out


def detect_tactics(board, move, best_uci, wp_after):
    """Motifs for the mover playing `move` in `board` (position before the move).

    Returns (found, allowed): tactics the mover created vs tactics the mover allowed.
    """
    mover = board.turn
    enemy = not mover
    frm, to = move.from_square, move.to_square
    piece = board.piece_at(frm)
    found, allowed = Counter(), Counter()
    b2 = board.copy(stack=False)
    is_cap = board.is_capture(move)
    captured = board.piece_type_at(to)
    b2.push(move)

    if b2.is_checkmate():
        found["mate"] += 1

    if attacks_higher(b2, to, mover) >= 2:
        found["fork"] += 1

    newly_pinned = 0
    for s, p in list(b2.piece_map().items()):
        if p.color == enemy and p.piece_type != chess.KING:
            if not board.is_pinned(enemy, s) and b2.is_pinned(enemy, s):
                newly_pinned += 1
    found["pin"] += min(newly_pinned, 2)

    for slider_sq, step in slider_behind(board, frm, mover):
        t = step_from(frm, -step)
        target = None
        while t is not None:
            if board.piece_at(t):
                target = t
                break
            t = step_from(t, -step)
        if target is not None:
            tp = board.piece_at(target)
            if tp.color == enemy and (tp.piece_type == chess.KING or VAL[tp.piece_type] >= 5):
                found["discovered"] += 1
                break

    if is_cap and captured:
        for t_def in board.attacks(to):
            p_def = board.piece_at(t_def)
            if not p_def or p_def.color != enemy or p_def.piece_type == chess.KING:
                continue
            guard_before = set(board.attackers(enemy, t_def))
            if guard_before - {to}:
                continue
            for a in b2.attackers(mover, t_def):
                m = chess.Move(a, t_def)
                if see_for(b2, m, mover) >= 1:
                    found["removes-defender"] += 1
                    break
            else:
                continue
            break

    for t_v in b2.attacks(to):
        p_v = b2.piece_at(t_v)
        if not p_v or p_v.color != enemy or p_v.piece_type in (chess.KING, chess.PAWN):
            continue
        if VAL[p_v.piece_type] < 3:
            continue
        atks_now = [a for a in b2.attackers(mover, t_v) if b2.piece_type_at(a) != chess.KING
                    and VAL[b2.piece_type_at(a)] < VAL[p_v.piece_type]]
        if not atks_now or max(see_for(b2, chess.Move(a, t_v), mover) for a in atks_now) < 1:
            continue
        safe = False
        for esc in b2.legal_moves:
            if esc.from_square != t_v:
                continue
            if b2.is_capture(esc):
                if see(b2, esc) >= 0:
                    safe = True
                    break
            else:
                b3 = b2.copy(stack=False)
                b3.push(esc)
                danger = False
                for a in b3.attackers(mover, esc.to_square):
                    if b3.piece_type_at(a) != chess.KING:
                        m = chess.Move(a, esc.to_square)
                        if m in b3.legal_moves and see_for(b3, m, mover) >= 1:
                            danger = True
                            break
                if not danger:
                    safe = True
                    break
        if not safe:
            found["trapped"] += 1
            break

    pre_hangs = hanging_squares(board, enemy)
    post_hangs = hanging_squares(b2, enemy)
    if is_cap and captured and VAL[captured] >= 3 and to in pre_hangs and see(board, move) >= 3:
        found["free-piece"] += 1
    if post_hangs - pre_hangs:
        allowed["free-piece"] += 1

    if is_cap and captured:
        if see(board, move) < 0 and wp_after is not None and wp_after >= 40 and (best_uci is None or move.uci() == best_uci):
            found["sacrifice"] += 1

    if piece.piece_type in (chess.ROOK, chess.BISHOP, chess.QUEEN):
        for step in STEPS:
            t = step_from(to, step)
            t1 = None
            while t is not None:
                if board.piece_at(t):
                    t1 = t
                    break
                t = step_from(t, step)
            if t1 and t1 != frm:
                p1 = board.piece_at(t1)
                if p1 and p1.color == enemy and VAL[p1.piece_type] >= 9:
                    t2 = step_from(t1, step)
                    t2 = t2 if t2 is not None else None
                    while t2 is not None and board.piece_at(t2) is None:
                        t2 = step_from(t2, step)
                    if t2 is not None:
                        p2 = board.piece_at(t2)
                        if p2 and p2.color == enemy and VAL[p2.piece_type] < VAL[p1.piece_type]:
                            found["other"] += 1
                            break
    return found, allowed


def endgame_theme(board):
    counts = Counter(p.piece_type for p in board.piece_map().values())
    if counts[chess.QUEEN]:
        return "queen"
    if counts[chess.ROOK]:
        return "rook"
    if counts[chess.KNIGHT] + counts[chess.BISHOP]:
        return "other"
    return "kp"


def game_type(parsed):
    sans = [node.san() for node in list(parsed.mainline())[:2]]
    if not sans:
        return "closed"
    if sans[0] == "e4":
        return "open" if len(sans) > 1 and sans[1] == "e5" else "semi-open"
    return "closed"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    args = ap.parse_args()
    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = {g["uuid"]: g for g in games if g.get("rules") == "chess"}
    moves = {}
    moves_path = datadir / f"moves-{me}.jsonl"
    if not moves_path.exists():
        sys.exit(f"no move reviews for user '{me}' yet - run: make review USER={me}")
    for l in moves_path.read_text().splitlines():
        if not l.strip():
            continue
        r = json.loads(l)
        if r["uuid"] not in moves or r["depth"] > moves[r["uuid"]]["depth"]:
            moves[r["uuid"]] = r
    out_path = datadir / f"advanced-{me}.jsonl"
    done = set()
    if out_path.exists():
        for l in out_path.read_text().splitlines():
            if l.strip():
                done.add(json.loads(l)["uuid"])
    n = 0
    with out_path.open("a") as out:
        for uuid, g in sorted(games.items(), key=lambda kv: kv[1]["end_time"]):
            if uuid in done or uuid not in moves:
                continue
            rows = moves[uuid]["moves"]
            parsed = chess.pgn.read_game(StringIO(g["pgn"]))
            if parsed is None:
                continue
            me_white = g["white"]["username"].lower() == me
            my_color = "white" if me_white else "black"
            my_chess_color = chess.WHITE if me_white else chess.BLACK
            outcome = g[f"outcome_{my_color}"]
            found, allowed = Counter(), Counter()
            board = parsed.board()
            my_move_acc = {"attack": [], "defend": [], "pawn": [], "space": [], "quiet": []}
            endgame = {"reached": False}
            eg_plies = []
            eg_types = {}
            for i, node in enumerate(parsed.mainline()):
                move = node.move
                if move is None:
                    continue
                mover_is_me = board.turn == my_chess_color
                row = rows[i] if i < len(rows) else None
                my_wp = None
                if row:
                    my_wp = row["wp_before"] if mover_is_me else 100 - row["wp_before"]

                pieces = sum(1 for p in board.piece_map().values()
                             if p.piece_type not in (chess.PAWN, chess.KING))
                if not endgame["reached"] and pieces <= 6:
                    endgame["reached"] = True
                    endgame["eval"] = my_wp
                in_eg = endgame["reached"]
                if in_eg and mover_is_me and row:
                    eg_plies.append(row["acc"])
                    eg_types.setdefault(endgame_theme(board), []).append(row["acc"])

                if mover_is_me and row:
                    attackers_near_king = sum(
                        1 for s in chess.SQUARES
                        if chess.square_distance(s, board.king(not board.turn)) == 1 and board.is_attacked_by(board.turn, s))
                    in_check = board.is_check()
                    opp_capture = max((see(board, m) for m in board.legal_moves if board.is_capture(m)), default=0)
                    her_captures = max((see(board, m) for m in board.legal_moves
                                        if board.is_capture(m) and m.from_square == move.from_square), default=0)
                    if attackers_near_king >= 3 or board.gives_check(move):
                        my_move_acc["attack"].append(row["acc"])
                    if in_check or opp_capture >= 1:
                        my_move_acc["defend"].append(row["acc"])
                    if board.piece_type_at(move.from_square) == chess.PAWN:
                        my_move_acc["pawn"].append(row["acc"])
                    space = sum(1 for s in chess.SQUARES
                                if chess.square_rank(s) >= 4 and board.is_attacked_by(board.turn, s))
                    opp_space = sum(1 for s in chess.SQUARES
                                    if chess.square_rank(s) <= 3 and board.is_attacked_by(not board.turn, s))
                    if space - opp_space >= 4:
                        my_move_acc["space"].append(row["acc"])
                    if not board.is_capture(move) and not in_check and not board.gives_check(move) \
                            and her_captures < 1 and opp_capture < 1:
                        my_move_acc["quiet"].append(row["acc"])

                mot_f, mot_a = detect_tactics(board, move, row["best"] if row else None, row["wp_after"] if row else None)
                mine_f, mine_a = (mot_f, mot_a) if mover_is_me else (mot_a, mot_f)
                for k, v in mine_f.items():
                    found[k] += v
                for k, v in mine_a.items():
                    allowed[k] += v

                board.push(move)

            if endgame["reached"]:
                ev = endgame.get("eval") or 0
                endgame["bucket"] = "better" if ev >= 55 else ("equal" if ev >= 45 else "worse")
                endgame["outcome"] = outcome
                endgame["acc"] = round(sum(eg_plies) / len(eg_plies), 1) if eg_plies else None
                for t, accs in eg_types.items():
                    endgame[f"acc_{t}"] = round(sum(accs) / len(accs), 1) if accs else None

            rec = {
                "uuid": uuid, "date": g["end_time_iso"][:10], "color": my_color, "outcome": outcome,
                "game_type": game_type(parsed),
                "found": {k: found.get(k, 0) for k in TACTICS},
                "allowed": {k: allowed.get(k, 0) for k in TACTICS},
                "strategy": {k: (round(sum(v) / len(v), 1) if v else None) for k, v in my_move_acc.items()},
                "strategy_n": {k: len(v) for k, v in my_move_acc.items()},
                "endgame": endgame,
            }
            out.write(json.dumps(rec, ensure_ascii=False) + "\n")
            n += 1
    print(f"wrote {n} new records -> {out_path}")


if __name__ == "__main__":
    main()

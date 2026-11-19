#!/usr/bin/env python3
import argparse
import json
import re
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

CLK_RE = re.compile(r"\[%clk\s+(\d+):(\d+):(\d+(?:\.\d+)?)\]")
DATE_RE = re.compile(r'\[UTCDate "(\d{4})\.(\d{2})\.(\d{2})"\]')
TIME_RE = re.compile(r'\[UTCTime "(\d{2}):(\d{2}):(\d{2})"\]')
WON_BY_RE = re.compile(r"won (?:by|on) (\w+)")


def load(path):
    games = []
    for line in Path(path).read_text().splitlines():
        if line.strip():
            games.append(json.loads(line))
    return games


def my_fields(g, me):
    if g["white"]["username"].lower() == me:
        return "white", g["white"], g["black"], g["outcome_white"]
    return "black", g["black"], g["white"], g["outcome_black"]


def my_accuracy(g, color):
    acc = g.get("accuracies")
    if not acc:
        return None
    return acc.get(color)


def base_inc(tc):
    m = re.match(r"^(\d+)\+?(\d+)?$", str(tc))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2) or 0)


def clock_stats(g, color):
    pgn = g.get("pgn", "")
    if not pgn or g.get("time_class") == "daily":
        return None
    bi = base_inc(g.get("time_control"))
    if not bi:
        return None
    base, inc = bi
    clocks = [int(h) * 3600 + int(m) * 60 + float(s) for h, m, s in CLK_RE.findall(pgn)]
    if len(clocks) < 2:
        return None
    idx = range(1, len(clocks), 2) if color == "black" else range(0, len(clocks), 2)
    times, prev = [], float(base)
    for i in idx:
        c = clocks[i]
        times.append(max(0.0, prev - c + inc))
        prev = c
    if not times:
        return None
    final_clock = clocks[list(idx)[-1]] - inc if list(idx)[-1] > 0 else clocks[-1]
    dur = None
    dm, dt = DATE_RE.search(pgn), TIME_RE.search(pgn)
    if dm and dt and g.get("end_time"):
        start = datetime(*map(int, dm.groups()), int(dt.group(1)), int(dt.group(2)), int(dt.group(3)), tzinfo=timezone.utc)
        dur = (g["end_time"] - start.timestamp()) / 60.0
    return {
        "avg_move_s": statistics.mean(times),
        "n_moves": len(times),
        "final_clock_s": max(0.0, final_clock),
        "duration_min": dur,
    }


def streaks(outcomes):
    best_w = best_l = cur = 0
    cur_type = None
    for o in outcomes:
        t = "w" if o == "win" else ("l" if o == "loss" else cur_type)
        if o not in ("win", "loss"):
            continue
        if t == cur_type:
            cur += 1
        else:
            cur = 1
            cur_type = t
        if t == "w":
            best_w = max(best_w, cur)
        else:
            best_l = max(best_l, cur)
    return best_w, best_l


def fmt_acc(a):
    return f"{a:.1f}" if a is not None else "—"


def main():
    ap = argparse.ArgumentParser(description="Insights-style stats from a fetched games JSONL.")
    ap.add_argument("user", help="chess.com username (reads data/games-<user>.jsonl)")
    ap.add_argument("--time-class", default=None, choices=["bullet", "blitz", "rapid", "daily"])
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--until", default=None)
    ap.add_argument("--top-openings", type=int, default=10)
    args = ap.parse_args()

    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games = load(datadir / f"games-{me}.jsonl")
    games = [g for g in games if g.get("rules") == "chess"]
    if args.time_class:
        games = [g for g in games if g["time_class"] == args.time_class]
    if args.since:
        y, m, d = map(int, args.since.split("-"))
        games = [g for g in games if g["end_time"] >= datetime(y, m, d, tzinfo=timezone.utc).timestamp()]
    if args.until:
        y, m, d = map(int, args.until.split("-"))
        games = [g for g in games if g["end_time"] < datetime(y, m, d, tzinfo=timezone.utc).timestamp()]
    games.sort(key=lambda g: g["end_time"])
    if not games:
        print("no games matched; run scripts/fetch_games.py first")
        return

    print(f"# Chess.com insights — {args.user} ({len(games)} games, {games[0]['end_time_iso'][:10]} → {games[-1]['end_time_iso'][:10]})")
    if not args.time_class:
        print(f"time classes: " + ", ".join(f"{k}={v}" for k, v in sorted(defaultdict(int, {c: sum(1 for g in games if g['time_class'] == c) for c in {g['time_class'] for g in games}}).items())))

    for tc in sorted({g["time_class"] for g in games}, key=lambda t: -sum(1 for g in games if g["time_class"] == t)):
        sel = [g for g in games if g["time_class"] == tc]
        rec = defaultdict(int)
        color_rec = defaultdict(lambda: defaultdict(int))
        my_ratings, opp_ratings = [], []
        for g in sel:
            color, mine, opp, oc = my_fields(g, me)
            rec[oc] += 1
            color_rec[color][oc] += 1
            my_ratings.append(mine["rating"])
            opp_ratings.append(opp["rating"])
        n = len(sel)
        w, l, d = rec["win"], rec["loss"], rec["draw"]
        bw, bl = streaks([my_fields(g, me)[3] for g in sel])
        print(f"\n## {tc} — {n} games: {w}W-{l}L-{d}D (win {100 * w / n:.1f}%)")
        print(f"- color: white {color_rec['white']['win']}W-{color_rec['white']['loss']}L-{color_rec['white']['draw']}D | black {color_rec['black']['win']}W-{color_rec['black']['loss']}L-{color_rec['black']['draw']}D")
        print(f"- rating: {min(my_ratings)} → {max(my_ratings)} (peak, pre-game obs.), latest {my_ratings[-1]}; avg opp {statistics.mean(opp_ratings):.0f}")
        print(f"- streaks: {bw} wins / {bl} losses longest")
        ends = defaultdict(int)
        for g in sel:
            color, mine, opp, oc = my_fields(g, me)
            m = WON_BY_RE.search(g.get("termination") or "")
            ends[f"{'W' if oc == 'win' else ('L' if oc == 'loss' else 'D')}: {m.group(1) if m else '?'}"] += 1
        print(f"- endings: " + ", ".join(f"{k} ×{v}" for k, v in sorted(ends.items(), key=lambda x: -x[1])))

        accs = [(g, my_accuracy(g, my_fields(g, me)[0])) for g in sel]
        with_acc = [(g, a) for g, a in accs if a is not None]
        if with_acc:
            vals = [a for _, a in with_acc]
            wins_acc = [a for g, a in with_acc if my_fields(g, me)[3] == "win"]
            losses_acc = [a for g, a in with_acc if my_fields(g, me)[3] == "loss"]
            print(f"- accuracy: {statistics.mean(vals):.1f} avg over {len(with_acc)}/{n} reviewed games | in wins {statistics.mean(wins_acc):.1f} | in losses {statistics.mean(losses_acc):.1f}" if wins_acc and losses_acc else f"- accuracy: {statistics.mean(vals):.1f} avg over {len(with_acc)}/{n} reviewed games")
            best = sorted(with_acc, key=lambda x: -x[1])[:3]
            worst = sorted(with_acc, key=lambda x: x[1])[:3]
            print(f"- best: " + " | ".join(f"{a:.1f} vs {my_fields(g, me)[2]['username']} ({g['end_time_iso'][:10]})" for g, a in best))
            print(f"- worst: " + " | ".join(f"{a:.1f} vs {my_fields(g, me)[2]['username']} ({g['end_time_iso'][:10]})" for g, a in worst))
        missing = n - len(with_acc)
        if missing:
            print(f"- not reviewed (no accuracy): {missing}")

        by_month = defaultdict(list)
        for g in sel:
            by_month[g["end_time_iso"][:7]].append(g)
        if len(by_month) > 1:
            print(f"- by month:")
            for mo in sorted(by_month):
                gs = by_month[mo]
                r = defaultdict(int)
                for g in gs:
                    r[my_fields(g, me)[3]] += 1
                accs_m = [a for g in gs if (a := my_accuracy(g, my_fields(g, me)[0])) is not None]
                acc_txt = f", acc {statistics.mean(accs_m):.1f}" if accs_m else ""
                print(f"  - {mo}: {r['win']}W-{r['loss']}L-{r['draw']}D{acc_txt}")

        op_stats = defaultdict(lambda: defaultdict(list))
        for g in sel:
            color, mine, opp, oc = my_fields(g, me)
            key = g.get("opening") or "Unknown"
            op_stats[key]["oc"].append(oc)
            a = my_accuracy(g, color)
            if a is not None:
                op_stats[key]["acc"].append(a)
        ranked = sorted(op_stats.items(), key=lambda x: -len(x[1]["oc"]))[: args.top_openings]
        print(f"- openings (top {len(ranked)} by games):")
        for name, s in ranked:
            ocs = s["oc"]
            nw, nl, nd = ocs.count("win"), ocs.count("loss"), ocs.count("draw")
            acc_txt = f", acc {statistics.mean(s['acc']):.1f}" if s["acc"] else ""
            print(f"  - {name}: {len(ocs)} games, {nw}W-{nl}L-{nd}D ({100 * nw / len(ocs):.0f}% wins){acc_txt}")

        buckets = defaultdict(lambda: defaultdict(int))
        for g in sel:
            color, mine, opp, oc = my_fields(g, me)
            diff = opp["rating"] - mine["rating"]
            b = "lower rated" if diff < 0 else ("+0..50" if diff < 50 else ("+50..100" if diff < 100 else "+100 and up"))
            buckets[b][oc] += 1
        print(f"- vs opponent strength:")
        for b in ["lower rated", "+0..50", "+50..100", "+100 and up"]:
            s = buckets.get(b)
            if not s:
                continue
            tot = sum(s.values())
            print(f"  - {b}: {tot} games, {100 * s['win'] / tot:.0f}% wins ({s['win']}W-{s['loss']}L-{s['draw']}D)")

        cstats = [(g, cs) for g in sel if (cs := clock_stats(g, my_fields(g, me)[0])) and cs["n_moves"] >= 5]
        if cstats:
            avg_mt = statistics.mean(cs["avg_move_s"] for _, cs in cstats)
            low = [(g, cs) for g, cs in cstats if cs["final_clock_s"] < 60]
            fast = sorted(((g, cs) for g, cs in cstats if cs["duration_min"] is not None), key=lambda x: x[1]["duration_min"])[:3]
            print(f"- clock: avg {avg_mt:.0f}s/move | finished under 60s: {len(low)}/{len(cstats)}")
            print(f"- fastest games: " + " | ".join(f"{cs['duration_min']:.1f} min vs {my_fields(g, me)[2]['username']} ({g['end_time_iso'][:10]})" for g, cs in fast))

    print("\nNote: accuracy/«diamond» move stats come from chess.com game review when present;")
    print("run scripts/review_moves.py for local move-quality analysis (ACPL, blunders) of any game.")


if __name__ == "__main__":
    main()

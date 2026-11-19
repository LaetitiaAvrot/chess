#!/usr/bin/env python3
import argparse
import json
import sys
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

ECO_RE = re.compile(r'\[ECO "([A-Z]\d{2})"\]')


def short_name(name):
    return (name or "Unknown").split(" 2.")[0].split(" 3.")[0]


def fmt_acc(a):
    return f"{a:.1f}" if a is not None else "—"


def main():
    ap = argparse.ArgumentParser(description="Regenerate the accuracy-per-opening table (data/accuracy-by-opening-<user>.md).")
    ap.add_argument("user")
    ap.add_argument("--since", default=None, help="YYYY-MM-DD")
    ap.add_argument("--min-games", type=int, default=2)
    args = ap.parse_args()

    me = args.user.lower()
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = [g for g in games if g.get("rules") == "chess"]
    for g in games:
        m = ECO_RE.search(g.get("pgn") or "")
        g["eco_code"] = m.group(1) if m else None
    if args.since:
        y, mth, d = map(int, args.since.split("-"))
        games = [g for g in games if g["end_time"] >= datetime(y, mth, d, tzinfo=timezone.utc).timestamp()]
    games.sort(key=lambda g: g["end_time"])

    reviews = {}
    rpath = datadir / f"reviews-{me}.jsonl"
    if rpath.exists():
        for r in (json.loads(l) for l in rpath.read_text().splitlines() if l.strip()):
            reviews[r["uuid"]] = r

    phase = {}
    ppath = datadir / f"opening-phase-{me}.jsonl"
    if ppath.exists():
        for r in (json.loads(l) for l in ppath.read_text().splitlines() if l.strip()):
            phase[r["uuid"]] = r

    buckets = defaultdict(lambda: {"g": [], "names": Counter(), "acc": [], "acpl": {}, "open": []})
    for g in games:
        if g["white"]["username"].lower() == me:
            color, oc = "white", g["outcome_white"]
        else:
            color, oc = "black", g["outcome_black"]
        key = (color, g["eco_code"] or "???")
        b = buckets[key]
        b["g"].append(oc)
        b["names"][short_name(g.get("opening"))] += 1
        acc = g.get("accuracies")
        if acc:
            b["acc"].append((g["end_time"], acc[color]))
        rv = reviews.get(g["uuid"])
        if rv and "acpl" in rv:
            b["acpl"].setdefault("v", []).append(rv["acpl"][color])
        ph = phase.get(g["uuid"])
        if ph and ph.get(color) is not None:
            b["open"].append(ph[color])

    lines = [
        f"# Accuracy per opening — {args.user}",
        "",
        f"_Regenerated {datetime.now(timezone.utc).isoformat(timespec='seconds')} — {len(games)} games. "
        "Do not edit by hand: re-run `scripts/openings.py` after fetching new games._",
        "",
        "acc = chess.com game review accuracy (avg of reviewed games only);",
        "acc-10 = same, over the last 10 games of that opening (drift check);",
        "acc-open = local Stockfish accuracy over the first 12 moves only (scripts/opening_accuracy.py);",
        "ACPL = local Stockfish reviews via `scripts/review_moves.py` (only games reviewed locally).",
        "",
    ]
    for color in ("white", "black"):
        lines.append(f"## As {color}")
        lines.append("")
        lines.append("| ECO | opening | games | W-L-D | win% | acc | acc-10 | acc-open | ACPL | last played |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        keys = [k for k in buckets if k[0] == color and len(buckets[k]["g"]) >= args.min_games]
        keys.sort(key=lambda k: -len(buckets[k]["g"]))
        for key in keys:
            b = buckets[key]
            code = key[1]
            name = b["names"].most_common(1)[0][0]
            n = len(b["g"])
            w, l, d = b["g"].count("win"), b["g"].count("loss"), b["g"].count("draw")
            acc = fmt_acc(statistics.mean(a for _, a in b["acc"])) if b["acc"] else "—"
            last10 = b["acc"][-10:]
            acc10 = fmt_acc(statistics.mean(a for _, a in last10)) if last10 else "—"
            acpls = b["acpl"].get("v", [])
            acpl = fmt_acc(statistics.mean(acpls)) if acpls else "—"
            acc_open = fmt_acc(statistics.mean(b["open"])) if b["open"] else "—"
            last_date = max((g["end_time_iso"][:10] for g in games
                             if ((g["white"]["username"].lower() == me) == (color == "white"))
                             and (g["eco_code"] or "???") == code), default="—")
            lines.append(f"| {code} | {name} | {n} | {w}-{l}-{d} | {100 * w / n:.0f}% | {acc} | {acc10} | {acc_open} | {acpl} | {last_date} |")
        lines.append("")

    out = datadir / f"accuracy-by-opening-{me}.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out}")
    print("\n".join(lines))


if __name__ == "__main__":
    main()

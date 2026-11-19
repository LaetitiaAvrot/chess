#!/usr/bin/env python3
"""Static HTML dashboard: loss stats + improvement plan from local data.

Usage: python3 scripts/dashboard.py arkhena [--out dashboard.html]
Reads games-<user>.jsonl, reviews-<user>.jsonl, mistakes-<user>.csv and
advanced-<user>.jsonl, and writes a self-contained dashboard.html —
pure HTML + CSS (bars and donut are plain divs / conic-gradient; only the two
line charts are inline SVG). No JavaScript. Second tab = advanced statistics
(tactics, strategy, endgames) computed by scripts/advanced_stats.py.
"""
import argparse
import csv
import json
import sys
from collections import Counter
from html import escape
from pathlib import Path

CAT_COLORS = {
    "hung-piece": "#e5484d",
    "eval-drop": "#f5a623",
    "bad-capture": "#d67dd8",
    "allowed-mate-in-1": "#ff5d8f",
    "clean-scoresheet": "#4cc38a",
    "missed mate": "#8e4cf0",
    "missed tactic": "#38bdf8",
    "missed-promotion": "#22d3ee",
    "promotion oversight": "#22d3ee",
    "time management": "#f472b6",
    "quitting too early": "#94a3b8",
    "opening mistake": "#fb923c",
    "unparsed": "#888888",
}
PHASE_COLORS = {"opening": "#7dd3fc", "middlegame": "#f5a623", "endgame": "#a3e635"}
GREEN = "#61d929"
BLUE = "#7dd3fc"
RED = "#e5484d"
TACTICS = ("fork", "pin", "discovered", "removes-defender", "trapped", "free-piece", "mate", "sacrifice", "other")
THEMES = ("kp", "rook", "queen", "other")
THEME_NAMES = {"kp": "King and Pawn", "rook": "Rook and Pawn", "queen": "Queen", "other": "Other Endgames"}
STRATS = ("attack", "defend", "pawn", "space", "quiet")
STRAT_NAMES = {
    "attack": "Attacking Accuracy",
    "defend": "Defending Accuracy",
    "pawn": "Pawn Structure Accuracy",
    "space": "Space Advantage Accuracy",
    "quiet": "Overall Strategic Accuracy",
}
GT_NAMES = {"all": "All", "open": "Open", "semi-open": "Semi-Open", "closed": "Closed"}


def short_opening(name):
    if not name:
        return "?"
    for cut in (" Variation", " Accepted", " Declined", " Defense:", " Gambit:"):
        name = name.split(cut)[0]
    return " ".join(name.split()[:3])


def load(me):
    datadir = Path(__file__).resolve().parent.parent / "data"
    games_path = datadir / f"games-{me}.jsonl"
    if not games_path.exists():
        sys.exit(f"no data for user '{me}' yet - run: make fetch USER={me}")
    games = [json.loads(l) for l in (datadir / f"games-{me}.jsonl").read_text().splitlines() if l.strip()]
    games = [g for g in games if g.get("rules") == "chess"]
    mistakes = {}
    mp = datadir / f"mistakes-{me}.csv"
    if mp.exists():
        for r in csv.DictReader(mp.open()):
            mistakes[r["game_id"]] = r
    records = []
    for g in games:
        me_white = g["white"]["username"].lower() == me
        mine, theirs = ("white", "black") if me_white else ("black", "white")
        acc = g.get("accuracies") or {}
        m = mistakes.get(g["uuid"], {})
        mv = m.get("move_number")
        records.append({
            "date": g["end_time_iso"][:10],
            "outcome": g[f"outcome_{mine}"],
            "color": mine,
            "myAcc": acc.get(mine),
            "myElo": (g[mine] or {}).get("rating"),
            "opening": short_opening(g.get("opening")),
            "category": m.get("category") if g[f"outcome_{mine}"] == "loss" else None,
            "phase": m.get("phase") if m.get("phase") in ("opening", "middlegame", "endgame") else None,
            "moveNum": int(mv) if mv else None,
        })
    records.sort(key=lambda r: r["date"])
    return records


def avg(xs):
    xs = [x for x in xs if x is not None]
    return sum(xs) / len(xs) if xs else None


def css_bars(items, colors=None):
    vmax = max((v for _, v in items), default=0) or 1
    rows = []
    for k, v in items:
        c = (colors or {}).get(k, GREEN)
        rows.append(
            f'<div class="hbar"><span class="hl">{escape(str(k), quote=True)}</span>'
            f'<div class="ht"><div class="hf" style="width:{100 * v / vmax:.1f}%;background:{c}"></div></div>'
            f'<span class="hv">{v}</span></div>')
    return "".join(rows)


def css_bars_pct(items, colors=None, denom=None):
    vmax = max((v for _, v in items), default=0) or 1
    rows = []
    for k, v in items:
        c = (colors or {}).get(k, GREEN)
        extra = f' <small style="color:#9a9ab0">({v})</small>' if denom else ""
        rows.append(
            f'<div class="hbar"><span class="hl">{escape(str(k), quote=True)}</span>'
            f'<div class="ht"><div class="hf" style="width:{100 * v / vmax:.1f}%;background:{c}"></div></div>'
            f'<span class="hv">{v}%{extra}</span></div>')
    return "".join(rows)


def css_donut(items):
    total = sum(v for _, v in items) or 1
    stops, acc = [], 0
    for k, v in items:
        start, acc = 100 * acc / total, acc + v
        stops.append(f"{CAT_COLORS.get(k, '#888')} {start:.1f}% {100 * acc / total:.1f}%")
    return (f'<div class="donut-wrap"><div class="donut" style="background:conic-gradient({", ".join(stops)})">'
            f'<div class="hole"><b>{total}</b><span>losses</span></div></div></div>')


def svg_line(points, color=GREEN, width=560, height=220, zero=False, fmt="{:.0f}"):
    if len(points) < 2:
        return '<p style="color:#9a9ab0">not enough data</p>'
    vs = [v for _, v in points]
    vmin = 0 if zero else min(vs) * 0.98
    vmax = max(vs) * 1.02
    pad_l, pad_r, pad_t, pad_b = 44, 10, 12, 30
    if vmax == vmin:
        vmax = vmin + 1

    def X(i):
        return pad_l + (width - pad_l - pad_r) * i / (len(points) - 1)

    def Y(v):
        return pad_t + (height - pad_t - pad_b) * (1 - (v - vmin) / (vmax - vmin))

    out = [f'<svg viewBox="0 0 {width} {height}" role="img">']
    for t in range(4):
        v = vmin + (vmax - vmin) * t / 3
        y = Y(v)
        out.append(f'<line x1="{pad_l}" y1="{y:.1f}" x2="{width - pad_r}" y2="{y:.1f}" stroke="#2c2c3d"/>')
        out.append(f'<text x="{pad_l - 6}" y="{y + 4:.1f}" text-anchor="end" font-size="10" fill="#9a9ab0">{fmt.format(v)}</text>')
    d = " ".join(f"{'M' if i == 0 else 'L'}{X(i):.1f},{Y(v):.1f}" for i, (_, v) in enumerate(points))
    out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2"/>')
    step = max(1, len(points) // 12)
    for i, (k, _) in enumerate(points):
        if i % step == 0 or i == len(points) - 1:
            out.append(f'<text x="{X(i):.1f}" y="{height - 8}" text-anchor="middle" font-size="10" fill="#9a9ab0">{escape(str(k), quote=True)}</text>')
    out.append("</svg>")
    return "".join(out)


def strategy_table(adv, buckets):
    rows = ['<table class="tbl"><tr><th></th>' + "".join(f"<th>{GT_NAMES[b]}</th>" for b in buckets) + "</tr>"]
    for s in STRATS:
        cells = []
        for b in buckets:
            sel = [a for a in adv if (b == "all" or a["game_type"] == b) and a["strategy"].get(s) is not None]
            wsum = sum(a["strategy"][s] * a["strategy_n"][s] for a in sel)
            ntot = sum(a["strategy_n"][s] for a in sel)
            cells.append(f"{wsum / ntot:.1f}" if ntot else "—")
        rows.append(f"<tr><td>{STRAT_NAMES[s]}</td>" + "".join(f"<td>{c}</td>" for c in cells) + "</tr>")
    rows.append("</table>")
    return "".join(rows)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    me = args.user.lower()
    recs = load(me)
    losses = [r for r in recs if r["outcome"] == "loss"]
    wins = [r for r in recs if r["outcome"] == "win"]
    draws = [r for r in recs if r["outcome"] == "draw"]

    acc_w, acc_l = avg([r["myAcc"] for r in wins]), avg([r["myAcc"] for r in losses])
    elos = [r["myElo"] for r in recs if r["myElo"]]
    elo_now, elo_peak, elo_min = elos[-1], max(elos), min(elos)

    cat_count = Counter(r["category"] for r in losses if r["category"])
    cat_items = cat_count.most_common()
    tactic = sum(cat_count[c] for c in ("hung-piece", "bad-capture", "allowed-mate-in-1", "missed mate"))
    phase_count = Counter(r["phase"] for r in losses if r["phase"])
    ph_total = sum(phase_count.values())

    open_count_w = Counter(r["opening"] for r in losses if r["color"] == "white")
    open_count_b = Counter(r["opening"] for r in losses if r["color"] == "black")
    buckets = {"1–10": 0, "11–20": 0, "21–30": 0, "31–40": 0, "41+": 0}
    for r in losses:
        if r["moveNum"] is None:
            continue
        if r["moveNum"] <= 10:
            buckets["1–10"] += 1
        elif r["moveNum"] <= 20:
            buckets["11–20"] += 1
        elif r["moveNum"] <= 30:
            buckets["21–30"] += 1
        elif r["moveNum"] <= 40:
            buckets["31–40"] += 1
        else:
            buckets["41+"] += 1

    months = sorted({r["date"][:7] for r in recs})
    monthly = []
    for m in months:
        ms = [r for r in recs if r["date"][:7] == m]
        w = sum(1 for r in ms if r["outcome"] == "win")
        monthly.append((m[2:], round(100 * w / len(ms))))
    elo_pts = [(r["date"][2:7], r["myElo"]) for r in recs if r["myElo"]]

    winrate_items = []
    for col in ("white", "black"):
        og = Counter(r["opening"] for r in recs if r["color"] == col)
        ow = Counter(r["opening"] for r in recs if r["outcome"] == "win" and r["color"] == col)
        items = [(f"{o} ({ow[o]}/{og[o]})", round(100 * ow[o] / og[o])) for o in og if og[o] >= 10]
        items.sort(key=lambda kv: -kv[1])
        winrate_items.append((col, items))

    legend = "".join(
        f'<span style="--c:{CAT_COLORS.get(k, "#888")}">{escape(k, quote=True)} {v} ({round(100 * v / len(losses))}%)</span>'
        for k, v in cat_items)

    cards = [
        (len(recs), f"games ({recs[0]['date']} → {recs[-1]['date']})"),
        (f"{len(wins)}–{len(losses)}–{len(draws)}", "W–L–D"),
        (f"{round(100 * len(losses) / len(recs))}%", "loss rate"),
        (f"{acc_w:.1f} → {acc_l:.1f}", "your acc: wins → losses"),
        (f"{elo_now} <small style='color:#9a9ab0'>(peak {elo_peak}, floor {elo_min})</small>", "current elo"),
    ]
    headline = "".join(
        f'<div class="card"><div class="big">{c[0]}</div><div class="lbl">{c[1]}</div></div>' for c in cards)

    ph_items = sorted(phase_count.items(), key=lambda kv: ["opening", "middlegame", "endgame"].index(kv[0]))
    advice = [
        f"<b>Blunder-check ritual — the single biggest fix.</b> {round(100 * tactic / len(losses))}% of your losses "
        f"({cat_count['hung-piece']} hung pieces, {cat_count['bad-capture']} losing captures, "
        f"{cat_count['allowed-mate-in-1']} allowed mate-in-1) end on a concrete tactic. Before <em>every</em> move: "
        f"3 seconds — what did my move stop defending? what can be captured? any checks against my king? Never pre-move.",
        f"<b>You lose by self-destruction, not by facing better players.</b> Accuracy gap {acc_w - acc_l:.1f} points "
        f"({acc_w:.1f} in wins vs {acc_l:.1f} in losses). Fixing the ritual above is worth more than any new opening.",
        f"<b>Where losses die: the middlegame.</b> {round(100 * phase_count['middlegame'] / ph_total)}% of losing mistakes "
        f"are middlegame ({phase_count['middlegame']}) vs {phase_count['opening']} opening and {phase_count['endgame']} "
        f"endgame. Your opening phase is already your strongest — study middlegame plans on your own loss list, not new theory.",
        f"<b>Endgame tail: {phase_count['endgame']} losses.</b> Drill the endings where your losses actually die — "
        f"rook and pawn endings are the usual suspects. 15 min/week of endgame drills beats 15 new opening lines.",
    ]
    if cat_count.get("missed mate"):
        advice.append(
            f"<b>Missed mates: {cat_count['missed mate']} losses had a mate on the board you didn't see — "
            f"either M# available for you, or the eval flipped to M# against you.</b> "
            f"Add “every check = run the mate scan, both ways” to the blunder-check ritual.")
    if cat_count.get("time management") or cat_count.get("quitting too early"):
        clock = cat_count.get("time management", 0) + cat_count.get("quitting too early", 0)
        advice.append(
            f"<b>Clock &amp; resignation discipline: {clock} losses.</b> {cat_count.get('time management', 0)} were lost "
            f"on time in winnable positions, {cat_count.get('quitting too early', 0)} were resigned while still at least "
            f"even. Play the position, not the score.")
    if cat_count.get("eval-drop"):
        advice.append(
            f"<b>Name your {cat_count['eval-drop']} eval-drop losses.</b> These aren't tactics — add one sentence per row in "
            f"mistakes-{me}.csv. After 20 names, the real pattern appears (the lesson-3 method).")
    advice.append(
        "<b>Watch the clock.</b> Most club losses at every rating come from either hanging pieces or burning time. "
        "Check the clock at move 10, 20 and 30; never pre-move in rapid.")
    advice_html = "".join(f"<li>{a}</li>" for a in advice)

    # advanced tab data
    datadir = Path(__file__).resolve().parent.parent / "data"
    adv_path = datadir / f"advanced-{me}.jsonl"
    if not adv_path.exists():
        sys.exit(f"no advanced stats for user '{me}' yet - run: make advanced USER={me}")
    adv = [json.loads(l) for l in adv_path.read_text().splitlines() if l.strip()]
    n = len(adv)
    tac_found = []
    tac_allowed = []
    for k in TACTICS:
        gf = sum(1 for a in adv if a["found"][k])
        ga = sum(1 for a in adv if a["allowed"][k])
        tac_found.append((k.replace("-", " ").title(), round(100 * gf / n)))
        tac_allowed.append((k.replace("-", " ").title(), round(100 * ga / n)))
    egs = [a["endgame"] for a in adv if a["endgame"]["reached"]]
    eg_cards = []
    for b, lbl in (("better", "From Better Position"), ("equal", "From Equal Position"), ("worse", "From Worse Position")):
        xs = [e for e in egs if e.get("bucket") == b]
        w = sum(1 for e in xs if e["outcome"] == "win")
        eg_cards.append((f"{round(100 * w / len(xs))}%" if xs else "—", f"{lbl} <small style='color:#9a9ab0'>({len(xs)} endgames)</small>"))
    eg_theme = []
    for t in THEMES:
        xs = [e[f"acc_{t}"] for e in egs if e.get(f"acc_{t}") is not None]
        if xs:
            eg_theme.append((THEME_NAMES[t], round(avg(xs))))
    eg_all = [e["acc"] for e in egs if e.get("acc") is not None]
    if eg_all:
        eg_theme.insert(0, ("Overall Endgame Accuracy", round(avg(eg_all))))
    strat_buckets = ("all", "open", "semi-open", "closed")
    strat_tbl = strategy_table(adv, strat_buckets)
    eg_reached_card = (f"{len(egs)} <small style='color:#9a9ab0'>/ {n}</small>", "games reached an endgame")
    allowed_colors = {"default": RED}

    adv_cards = "".join(
        f'<div class="card"><div class="big">{c[0]}</div><div class="lbl">{c[1]}</div></div>' for c in eg_cards + [eg_reached_card])

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(me)} — chess dashboard</title>
<style>
  :root {{ --bg:#16161e; --card:#1f1f2b; --line:#2c2c3d; --text:#e6e6f0; --muted:#9a9ab0; --green:{GREEN}; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:15px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1100px; margin:0 auto; padding:24px 16px 60px; }}
  h1 {{ font-size:24px; margin:8px 0 2px; }}
  h1 .dot {{ color:var(--green); }}
  .sub {{ color:var(--muted); margin:0 0 16px; font-size:14px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fit,minmax(170px,1fr)); gap:12px; margin-bottom:24px; }}
  .card {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:14px 16px; }}
  .card .big {{ font-size:24px; font-weight:700; }}
  .card .lbl {{ color:var(--muted); font-size:12.5px; }}
  .cols {{ display:grid; grid-template-columns:1fr 1fr; gap:16px; }}
  @media (max-width:800px) {{ .cols {{ grid-template-columns:1fr; }} }}
  .panel {{ background:var(--card); border:1px solid var(--line); border-radius:12px; padding:16px; margin-top:16px; }}
  .panel h2 {{ margin:0 0 12px; font-size:14px; color:var(--muted); font-weight:600; letter-spacing:.3px; text-transform:uppercase; }}
  svg {{ width:100%; height:auto; display:block; }}
  .hbar {{ display:flex; align-items:center; gap:10px; margin:7px 0; }}
  .hl {{ width:170px; flex:none; color:var(--muted); font-size:12.5px; text-align:right; }}
  .ht {{ flex:1; background:var(--line); border-radius:3px; height:16px; overflow:hidden; }}
  .hf {{ height:100%; border-radius:3px; min-width:2px; }}
  .hv {{ width:74px; flex:none; font-size:12.5px; }}
  .donut-wrap {{ display:flex; justify-content:center; }}
  .donut {{ width:190px; height:190px; border-radius:50%; position:relative; }}
  .hole {{ position:absolute; inset:28px; background:var(--card); border-radius:50%;
          display:flex; flex-direction:column; align-items:center; justify-content:center; }}
  .hole b {{ font-size:26px; }}
  .hole span {{ color:var(--muted); font-size:11px; }}
  .legend {{ display:flex; flex-wrap:wrap; gap:6px 14px; margin-top:12px; font-size:13px; justify-content:center; }}
  .legend span::before {{ content:""; display:inline-block; width:10px; height:10px; border-radius:2px; margin-right:6px; background:var(--c); }}
  ul.advice {{ margin:0; padding-left:18px; }}
  ul.advice li {{ margin-bottom:10px; }}
  footer {{ color:var(--muted); font-size:12.5px; margin-top:24px; }}
  input.tabr {{ display:none; }}
  .tabs {{ display:flex; gap:8px; margin-bottom:18px; }}
  .tabs label {{ background:var(--card); border:1px solid var(--line); color:var(--muted); border-radius:999px;
               padding:8px 18px; font-size:14px; cursor:pointer; }}
  #tab-losses:checked ~ .tabs label[for="tab-losses"],
  #tab-advanced:checked ~ .tabs label[for="tab-advanced"] {{ background:var(--green); color:#111; border-color:var(--green); font-weight:600; }}
  .tabpane {{ display:none; }}
  #tab-losses:checked ~ #pane-losses, #tab-advanced:checked ~ #pane-advanced {{ display:block; }}
  .tbl {{ width:100%; border-collapse:collapse; font-size:14px; }}
  .tbl th {{ color:var(--muted); text-align:right; font-weight:600; padding:6px 10px; border-bottom:1px solid var(--line); }}
  .tbl th:first-child {{ text-align:left; }}
  .tbl td {{ text-align:right; padding:6px 10px; border-bottom:1px solid var(--line); }}
  .tbl td:first-child {{ text-align:left; color:var(--muted); }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(me)} <span class="dot">&#9822;</span> chess dashboard</h1>
  <p class="sub">Local Stockfish reviews (depth 12–14) &middot; chess.com data &middot; no JavaScript on this page</p>

  <input class="tabr" type="radio" name="tab" id="tab-losses" checked>
  <input class="tabr" type="radio" name="tab" id="tab-advanced">
  <div class="tabs">
    <label for="tab-losses">Losses &amp; improvement</label>
    <label for="tab-advanced">Advanced statistics</label>
  </div>

  <div class="tabpane" id="pane-losses">
    <div class="grid">{headline}</div>

    <div class="cols">
      <div class="panel" style="margin-top:0"><h2>How the losses happen</h2>{css_donut(cat_items)}<div class="legend">{legend}</div></div>
      <div class="panel" style="margin-top:0"><h2>When the losing mistake lands (game phase)</h2>{css_bars(ph_items, PHASE_COLORS)}</div>
    </div>

    <div class="cols">
      <div class="panel"><h2>Rating over time <small style="color:#9a9ab0">(inline SVG — lines need it)</small></h2>{svg_line(elo_pts, color=BLUE)}</div>
      <div class="panel"><h2>Monthly win rate % <small style="color:#9a9ab0">(inline SVG)</small></h2>{svg_line(monthly, zero=True, fmt="{:.0f}%")}</div>
    </div>

    <div class="cols">
      <div class="panel"><h2>Losses by opening — as White (top 10)</h2>{css_bars(open_count_w.most_common(10))}</div>
      <div class="panel"><h2>Losses by opening — as Black (top 10)</h2>{css_bars(open_count_b.most_common(10))}</div>
    </div>

    <div class="cols">
      <div class="panel"><h2>Move number of the losing mistake</h2>{css_bars(list(buckets.items()))}</div>
      <div class="panel"><h2>How to get better — ranked by expected rating gain</h2>
        <ul class="advice">{advice_html}</ul></div>
    </div>
  </div>

  <div class="tabpane" id="pane-advanced">
    <p class="sub" style="margin-top:8px">Journal-local approximations of chess.com Game Review buckets, computed by
    scripts/advanced_stats.py over all {n} games — same spirit, not identical definitions. Percentages = share of games
    containing at least one occurrence.</p>

    <div class="grid" style="margin-bottom:16px">{adv_cards}</div>

    <div class="cols" style="margin-top:0">
      <div class="panel" style="margin-top:0"><h2>Tactics — found (in % of games)</h2>{css_bars_pct(tac_found)}</div>
      <div class="panel" style="margin-top:0"><h2>Tactics — allowed (in % of games)</h2>{css_bars_pct(tac_allowed, colors=allowed_colors)}</div>
    </div>

    <div class="panel"><h2>Strategy — accuracy by game type (move-weighted)</h2>{strat_tbl}</div>

    <div class="cols">
      <div class="panel" style="margin-top:0"><h2>Wins by opening — as White (win rate %, ≥ 10 games)</h2>{css_bars_pct(winrate_items[0][1])}</div>
      <div class="panel" style="margin-top:0"><h2>Wins by opening — as Black (win rate %, ≥ 10 games)</h2>{css_bars_pct(winrate_items[1][1])}</div>
    </div>

    <div class="panel"><h2>Endgame accuracy by theme</h2>{css_bars(eg_theme, {"Overall Endgame Accuracy": BLUE})}</div>

    <div class="panel"><p style="margin:0;color:var(--muted);font-size:13.5px">
    Reading the strategy table: attacking accuracy measures your accuracy in positions where you attack the enemy king;
    defending accuracy while checked or under a material threat; pawn-structure accuracy on your pawn moves; space
    accuracy when you control more squares in their half; overall strategic accuracy on quiet moves. Open = 1.e4 e5,
    semi-open = 1.e4, closed = everything else (your Bird's and Slav worlds).</p></div>
  </div>

  <footer>Generated {__import__("datetime").date.today().isoformat()} by scripts/dashboard.py · data: games/reviews/mistakes/advanced in data/ ·
  pure HTML + CSS, inline SVG only for the two line charts, zero JavaScript · regenerate: python3 scripts/dashboard.py {escape(me, quote=True)}</footer>
</div>
</body>
</html>
"""
    out = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "dashboard.html"
    out.write_text(html, encoding="utf-8")
    print(f"wrote {out} ({len(recs)} games, {len(losses)} losses, 2 tabs, no JS)")


if __name__ == "__main__":
    main()

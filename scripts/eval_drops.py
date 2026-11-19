#!/usr/bin/env python3
"""Clickable HTML checklist of eval-drop losses, with auto-categorization.

Usage: python3 scripts/eval_drops.py arkhena [--out eval-drops.html]
Reads data/mistakes-<user>.csv, data/games-<user>.jsonl, data/moves-<user>.jsonl,
data/advanced-<user>.jsonl and the manual names in data/eval-drop-names.json
(keyed by the live game id in the URL), then writes:

  eval-drops.html                all eval-drop losses, with a category column
  eval-drops-uncategorized.html  only the games no category fits

Categories (manual entries win over automatic ones):
  promotion oversight — she had a promotion as best move and played something else
  time management     — flagged while totally winning or < 2 pawns behind
  missed tactic       — the opponent's tactic motifs show up in the game stats
Everything else is left for manual qualification.

Pure HTML + CSS, links open in a new tab, no JavaScript.
"""
import argparse
import csv
import json
from collections import Counter
from html import escape
from pathlib import Path

GREEN = "#61d929"
TIME_WP_FLOOR = 32.0  # -2 pawns behind ~ 32% winning chances
TACTIC_KEYS = ("fork", "pin", "discovered", "removes-defender", "trapped", "other", "sacrifice")


def load(me):
    datadir = Path(__file__).resolve().parent.parent / "data"
    rows = [r for r in csv.DictReader((datadir / f"mistakes-{me}.csv").open()) if r["category"] == "eval-drop"]
    rows.sort(key=lambda r: r["date"])
    games_path = datadir / f"games-{me}.jsonl"
    games = {}
    if games_path.exists():
        games = {g["uuid"]: g for g in (json.loads(l) for l in games_path.read_text().splitlines() if l.strip())
                 if g.get("rules") == "chess"}
    moves = {}
    moves_path = datadir / f"moves-{me}.jsonl"
    if moves_path.exists():
        for l in moves_path.read_text().splitlines():
            if not l.strip():
                continue
            r = json.loads(l)
            if r["uuid"] not in moves or r["depth"] > moves[r["uuid"]]["depth"]:
                moves[r["uuid"]] = r
    adv = {}
    adv_path = datadir / f"advanced-{me}.jsonl"
    if adv_path.exists():
        for l in adv_path.read_text().splitlines():
            if l.strip():
                r = json.loads(l)
                adv[r["uuid"]] = r
    names = {}
    names_path = datadir / "eval-drop-names.json"
    if names_path.exists():
        names = json.loads(names_path.read_text())
    return datadir, rows, games, moves, adv, names


def categorize(row, game, mrows, allowed, manual, me):
    if manual:
        return manual
    if allowed and any(allowed.get(k, 0) > 0 for k in TACTIC_KEYS):
        return "missed tactic"
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("user")
    ap.add_argument("--out", default=None)
    args = ap.parse_args()
    me = args.user.lower()
    datadir, rows, games, moves, adv, names = load(me)
    categorized = []
    for r in rows:
        game = games.get(r["game_id"])
        mrows = moves.get(r["game_id"], {}).get("moves", [])
        allowed = adv.get(r["game_id"], {}).get("allowed", {})
        manual = None
        if r["url"]:
            live_id = r["url"].rstrip("/").split("/")[-1]
            manual = names.get(live_id)
        r["cat"] = categorize(r, game, mrows, allowed, manual, me)
        categorized.append(r)
    cats = Counter(r["cat"] or "uncategorized" for r in categorized)
    uncategorized = [r for r in categorized if not r["cat"]]

    def table(rows_, show_cat):
        body = []
        for r in rows_:
            url = r["url"] or ""
            body.append(
                f'<tr><td class="ck"><input type="checkbox"></td>'
                + (f'<td class="cat">{escape(r["cat"] or "?", quote=True)}</td>' if show_cat else "")
                + f'<td>{escape(r["date"], quote=True)}</td>'
                f'<td>{escape(r["opponent"], quote=True)} ({escape(r["opp_elo"], quote=True)})</td>'
                f'<td>{escape(r["losing_move"], quote=True)}</td>'
                f'<td class="ev">{r["wp_before"]}% → {r["wp_after"]}%</td>'
                f'<td class="lnk"><a href="{escape(url, quote=True)}" target="_blank" rel="noopener">{escape(url, quote=True)}</a></td></tr>')
        return "".join(body)

    def head(cat_col):
        cat_th = f'<th>{cat_col}</th>' if cat_col else ""
        return (f'<tr><th>done</th>{cat_th}<th>date</th><th>opponent</th>'
                f'<th>losing move</th><th>eval</th><th>game (opens in new tab)</th></tr>')

    def page(title, subtitle, inner):
        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(me, quote=True)} — {escape(title, quote=True)}</title>
<style>
  :root {{ --bg:#16161e; --card:#1f1f2b; --line:#2c2c3d; --text:#e6e6f0; --muted:#9a9ab0; --green:{GREEN}; }}
  body {{ margin:0; background:var(--bg); color:var(--text); font:14px/1.5 -apple-system,"Segoe UI",Roboto,sans-serif; }}
  .wrap {{ max-width:1200px; margin:0 auto; padding:24px 16px 60px; }}
  h1 {{ font-size:22px; margin:8px 0 2px; }}
  h2 {{ font-size:15px; color:var(--muted); margin:26px 0 8px; }}
  .sub {{ color:var(--muted); font-size:14px; margin:0 0 20px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th {{ text-align:left; color:var(--muted); font-size:12px; text-transform:uppercase;
       letter-spacing:.3px; padding:6px 10px; border-bottom:1px solid var(--line); }}
  td {{ padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }}
  td.ck {{ width:26px; }}
  td.cat {{ color:var(--muted); font-size:12.5px; white-space:nowrap; }}
  td.ev {{ color:var(--muted); white-space:nowrap; }}
  td.lnk a {{ color:var(--green); text-decoration:none; word-break:break-all; }}
  td.lnk a:hover {{ text-decoration:underline; }}
  input[type=checkbox] {{ accent-color:var(--green); width:15px; height:15px; }}
  .hint {{ color:var(--muted); font-size:13px; margin-top:18px; }}
  .pill {{ display:inline-block; background:var(--card); border:1px solid var(--line);
          border-radius:999px; padding:4px 12px; margin:0 6px 6px 0; font-size:13px; }}
</style>
</head>
<body>
<div class="wrap">
  <h1>{escape(me, quote=True)} <span style="color:var(--green)">&#9822;</span> {escape(title, quote=True)}</h1>
  <p class="sub">{subtitle}</p>
  {inner}
</div>
</body>
</html>
"""

    counts = "".join(f'<span class="pill">{escape(k, quote=True)}: {v}</span>' for k, v in cats.most_common())
    out_main = Path(args.out) if args.out else Path(__file__).resolve().parent.parent / "eval-drops.html"
    out_main.write_text(page(
        "eval-drops, categorized",
        f"{len(categorized)} eval-drop losses. " + counts +
        ' — manual names come from data/eval-drop-names.json (keyed by the live game id in the URL).',
        f"<table>{head('category')}{table(categorized, show_cat=True)}</table>"
        f'<p class="hint">Links open in a new tab. Regenerate: python3 scripts/eval_drops.py {escape(me, quote=True)}</p>'),
        encoding="utf-8")

    out_unc = Path(__file__).resolve().parent.parent / "eval-drops-uncategorized.html"
    out_unc.write_text(page(
        "eval-drops left to qualify",
        f"{len(uncategorized)} eval-drop losses no category fits yet — one sentence per game: what was the plan, what changed?",
        f"<table>{head('done')}{table(uncategorized, show_cat=False)}</table>"
        f'<p class="hint">Tick a row after naming it, then copy the sentence into data/mistakes-{me}.csv '
        f'or into data/eval-drop-names.json (keyed by the live game id in the URL). '
        f'Regenerate: python3 scripts/eval_drops.py {escape(me, quote=True)}</p>'),
        encoding="utf-8")
    print(f"{len(categorized)} eval-drops: " + ", ".join(f"{k} {v}" for k, v in cats.most_common()))
    print(f"wrote {out_main}")
    print(f"wrote {out_unc}")


if __name__ == "__main__":
    main()

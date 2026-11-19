# chess-stat

Fetch your chess.com games, review every move with a local Stockfish,
categorize your losses, compute tactic/strategy/endgame statistics, and render
a self-contained HTML dashboard (pure HTML + CSS, zero JavaScript).

```
chess.com API ──> fetch_games.py ──> data/games-<user>.jsonl
                        │
                        ▼
           review_moves.py (local Stockfish, per-move evals & classes)
                        │
                        ├──> data/reviews-<user>.jsonl   (per-game summary + worst moves)
                        ├──> data/moves-<user>.jsonl     (per-move rows)
                        │
                        ├──> mistakes.py ──> data/mistakes-<user>.csv
                        │        (game id, losing mistake, category, other mistakes)
                        │
                        ├──> advanced_stats.py ──> data/advanced-<user>.jsonl
                        │        (tactic motifs found/allowed, strategy accuracies,
                        │         endgame stats)
                        │
                        └──> dashboard.py ──> dashboard-<user>.html
                                 (2 tabs: losses & improvement / advanced statistics)
```

## Quickstart (Docker)

```bash
make build
make all USER=your-handle
```

Then open `dashboard-<user>.html` in a browser. Everything runs inside the
container — the host only needs Docker and GNU make; the Makefile detects
whether it is already inside the container and runs `python3` directly there.

## Make targets

| target | what it does |
|---|---|
| `make build` | build the Docker image (installs stockfish + python deps) |
| `make fetch` | fetch games from the chess.com API (cached; refetches every month since your latest game) |
| `make review` | review **all** games with Stockfish at depth 12 — resumable, losses first |
| `make review-uuid U=<uuid>` | review a single game |
| `make mistakes` | loss spreadsheet: game id, losing mistake, category, other mistakes |
| `make advanced` | tactic motifs (found/allowed), strategy accuracies, endgame stats |
| `make eval-drops` | clickable HTML checklist of the "quiet slide" losses |
| `make dashboard` | build the self-contained HTML dashboard for `$(USER)` |
| `make all` | fetch + review + mistakes + advanced + eval-drops + dashboard |
| `make stats` | headline stats (accuracy trends) |
| `make openings` | accuracy-per-opening table |
| `make opening-accuracy` | opening-phase accuracy (local Stockfish) |

Everything is parameterized by `USER` and `DEPTH` (default 12).

## Loss categories

Each loss gets one mechanical category, computed by replaying the game with
python-chess plus a small static-exchange evaluator:

- **hung-piece** — you left material en prise
- **missed tactic** — the opponent's tactic motif (pin, fork, skewer,
  discovered attack, removing the defender, trapped piece…) shows up in the game
- **missed mate** — the eval reached M# against you, or M# was available for you
- **bad-capture** — you initiated a losing capture
- **allowed-mate-in-1** — one-move mate
- **promotion oversight** — a passed pawn ran to promotion unchecked
- **time management** — flagged while winning or less than 2 pawns down
- **quitting too early** — resigned while still at least even
- **opening mistake** — the losing move came in the first 6 moves
- **eval-drop** — none of the above: the position quietly collapsed

`data/category-overrides.json` lets you hand-label games (keyed by the live
game id in the URL); manual names always win.

## Data files (in `data/`, gitignored)

| file | content |
|---|---|
| `games-<user>.jsonl` | one record per game: result, opening, ratings, accuracies, PGN |
| `reviews-<user>.jsonl` | per-game review summary: accuracy, ACPL, move classes, worst moves |
| `moves-<user>.jsonl` | per-move rows: played vs best move, win% before/after, accuracy |
| `mistakes-<user>.csv` | the loss spreadsheet (one row per loss) |
| `advanced-<user>.jsonl` | per-game tactic/strategy/endgame aggregates |
| `cache/<user>/*.json` | raw chess.com monthly archives |

## Notes

- The advanced statistics are **journal-local approximations** of chess.com's
  Game Review buckets — consistent for trend tracking, not identical numbers.
- chess.com **fragments opening names**; regroup by moves, not by label.
- chess.com accuracy on very short games (<10 moves) is noise in both directions.
- Reviews are depth-dependent; mixed depths coexist in the data (the scripts
  keep the highest depth per game).

## License

MIT — see [LICENSE](LICENSE).

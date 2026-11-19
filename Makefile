USER ?= your-handle
DEPTH ?= 12
IMAGE ?= chess-stat

# Inside the container, run python directly; from the host, wrap in docker run.
PY := $(if $(IN_CONTAINER),python3,docker run --rm --user "$$(id -u):$$(id -g)" -v "$$PWD":/app $(IMAGE) python3)

.PHONY: help build fetch review review-uuid mistakes advanced stats openings opening-accuracy all

help:
	@echo "chess-stat — pipeline for user USER (make all USER=your-handle)"
	@echo
	@echo "  make build                  build the Docker image (installs stockfish + python deps)"
	@echo "  make fetch                  fetch games from chess.com into data/games-$(USER).jsonl"
	@echo "  make review                 review all games with Stockfish (depth $(DEPTH), resumable, losses first)"
	@echo "  make review-uuid U=<uuid>   review a single game"
	@echo "  make mistakes               loss spreadsheet -> data/mistakes-$(USER).csv"
	@echo "  make advanced               tactic/strategy/endgame stats -> data/advanced-$(USER).jsonl"
	@echo "  make eval-drops             clickable HTML checklist of the quiet-slide losses"
	@echo "  make dashboard              build dashboard-$(USER).html (self-contained, no JS)"
	@echo "  make all                    fetch + review + mistakes + advanced + eval-drops + dashboard"
	@echo "  make stats                  headline stats (accuracy trends)"
	@echo "  make openings               accuracy-per-opening table"
	@echo "  make opening-accuracy       opening-phase accuracy (local Stockfish)"

build:
	docker build -t $(IMAGE) .

fetch:
	$(PY) scripts/fetch_games.py $(USER)

review:
	$(PY) scripts/review_all.py $(USER) --depth $(DEPTH)

review-uuid:
	$(PY) scripts/review_moves.py $(USER) --uuid $(U) --depth $(DEPTH)

mistakes:
	$(PY) scripts/mistakes.py $(USER)

advanced:
	$(PY) scripts/advanced_stats.py $(USER)

eval-drops:
	$(PY) scripts/eval_drops.py $(USER)

dashboard:
	$(PY) scripts/dashboard.py $(USER) --out dashboard-$(USER).html

all: fetch review mistakes advanced eval-drops dashboard

stats:
	$(PY) scripts/stats.py $(USER)

openings:
	$(PY) scripts/openings.py $(USER)

opening-accuracy:
	$(PY) scripts/opening_accuracy.py $(USER)

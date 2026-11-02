"""Reproducible greedy templates for the levels not covered by modular families."""
import itertools
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from ai.tracking_bao import GAMES, children_per_bao

def build(destination):
    plans = {}
    for game, (n, t, levels) in GAMES.items():
        plans[game] = {}
        for level in levels:
            if level < t + 2:
                continue
            started = time.monotonic()
            rng, parents, seen = random.Random(n * 1000 + level), [], set()
            per = children_per_bao(game, level)
            maximum = (324632 if t == 5 else 1000000) // per
            for attempt in range(20000):
                parent = tuple(sorted(rng.sample(range(1, n + 1), level)))
                children = []
                for child in itertools.combinations(parent, t):
                    if child in seen:
                        break
                    children.append(child)
                else:
                    parents.append(parent)
                    seen.update(children)
                if len(parents) == maximum:
                    break
            plans[game][str(level)] = {'parents': parents, 'childrenPerBao': per}
            print(game, level, len(parents), round(time.monotonic() - started, 2), flush=True)
    Path(destination).write_text(json.dumps({'version': 2, 'algorithm': 'seeded_greedy_disjoint_templates', 'candidateLimit': 20000, 'plans': plans}, separators=(',', ':')), encoding='utf-8')

if __name__ == '__main__':
    build(sys.argv[1] if len(sys.argv) > 1 else str(Path(__file__).resolve().parents[1] / 'runtime/bao-packing-rebuilt.json'))

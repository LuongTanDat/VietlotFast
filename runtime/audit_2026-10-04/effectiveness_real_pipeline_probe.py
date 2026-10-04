"""Exercise actual web inference with canonical history; lock into a temporary DB."""
import hashlib
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from ai import prediction_effectiveness as pe
from ai.configs import data_paths as dp


def hashes():
    paths = [dp.get_canonical_csv_read_path(game) for game in pe.GAMES]
    paths += [path for game in pe.GAMES for path in (dp.MODELS_DIR / game).glob('*.json')]
    return {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}


before = hashes()
results = []
with tempfile.TemporaryDirectory(prefix='effectiveness-real-inference-', dir=ROOT / 'runtime') as folder:
    database = Path(folder) / 'probe.db'
    for game in pe.GAMES:
        snapshot = pe._snapshot(game)
        pe._guard(snapshot)
        result = pe.cycle(game, db_path=database)
        report = pe.report(game, db_path=database)
        assert report['counts'] == {'locked': 1, 'scored': 0, 'total': 1}, report['counts']
        assert len(report['cycles'][0]['methods']) == 4
        assert all(m['meanHits'] is None for m in report['methods'])
        results.append({'type': game, 'result': result, 'deadline': report['cycles'][0]['deadline'],
                        'engine': report['cycles'][0]['methods']['web']['engine'],
                        'ticketCount': len(report['cycles'][0]['methods']['web']['tickets'])})
assert hashes() == before, 'Canonical/model files changed during read-only inference probe'
output = {'ok': True, 'productionFilesUnchanged': True, 'results': results}
(ROOT / 'runtime/audit_2026-10-04/effectiveness_real_pipeline_result.json').write_text(
    json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(output, ensure_ascii=False))

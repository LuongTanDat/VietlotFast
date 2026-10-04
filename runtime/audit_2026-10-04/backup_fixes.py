import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BIN = ROOT / 'Bin'
LATEST = BIN / 'session_1_latest'
PREVIOUS = BIN / 'session_2_previous'

def backup(paths, rotate=False):
    if rotate:
        for path in (LATEST, PREVIOUS):
            if path.resolve().parent != BIN.resolve():
                raise RuntimeError('Backup target outside Bin')
        if PREVIOUS.exists():
            shutil.rmtree(PREVIOUS)
        if LATEST.exists():
            shutil.move(str(LATEST), str(PREVIOUS))
    LATEST.mkdir(parents=True, exist_ok=True)
    manifest_path = LATEST / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8-sig')) if manifest_path.exists() else {
        'created_at': datetime.now(timezone.utc).isoformat(),
        'reason': 'Fix verified findings from BaoCaoRaSoat.md', 'files': []}
    for relative in paths:
        src = ROOT / relative
        dest = LATEST / 'files' / relative
        if src.exists() and not dest.exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(src, dest)
            manifest['files'].append({'path': relative, 'action': 'replace',
                'sha256': hashlib.sha256(src.read_bytes()).hexdigest()})
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding='utf-8')
    print('Backup:', len(manifest['files']), 'files')

if __name__ == '__main__':
    paths = ['backend/LottoWebServer.java', 'backend/live_results.py', 'ai/prediction_ledger.py',
             'ai/ml_pipeline.py', 'ai/predictors/ai_predict.py', 'ai/analysis/analysis.py',
             'ai/predictors/adaptive_coverage_predictor.py', 'ai/stats/stats_v2.py',
             'frontend/vietlott-web-core.js', 'frontend/vietlott-web-data.js',
             'frontend/vietlott-web-stats.js', 'frontend/vietlott-web.html',
             'docs/QuyTac.md', 'docs/NhatKyThayDoi.md', 'README.md',
             'tests/test_prediction_ledger_pipeline.py', 'tests/test_evaluation_pipeline.py']
    for game in ('loto_5_35', 'mega_6_45', 'power_6_55'):
        base = f'ai/standalone_predictors/{game}_predictor/'
        paths.extend(base + 'src/' + name + '.py' for name in
            ('deep_model', 'deep_dataset', 'backtest', 'predictor_api', 'config'))
        paths.append(base + 'README.md')
    backup(paths, rotate=True)

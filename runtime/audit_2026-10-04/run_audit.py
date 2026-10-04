"""Read-only project audit; all output is written beside this script."""
import ast
from collections import Counter
import csv
from datetime import datetime
import hashlib
import io
import json
import math
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def save(name, payload):
    (OUT / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')


def inspect_project():
    from backend import live_results as lr
    from scripts.clean_canonical_data import normalize_row
    files = []
    errors = []
    suffixes = {'.py', '.java', '.js', '.css', '.html', '.md', '.bat', '.json', '.txt'}
    for directory in ('ai', 'backend', 'frontend', 'scripts', 'tests', 'docs'):
        for path in sorted((ROOT / directory).rglob('*')):
            if not path.is_file() or path.suffix.lower() not in suffixes:
                continue
            if any(part in {'__pycache__', 'bin', 'lib', 'models', 'data', 'state', 'logs'} for part in path.relative_to(ROOT).parts):
                continue
            raw = path.read_bytes()
            text = raw.decode('utf-8-sig', errors='replace')
            entry = {'path':str(path.relative_to(ROOT)), 'bytes':len(raw), 'lines':len(text.splitlines()), 'sha256':hashlib.sha256(raw).hexdigest()}
            if path.suffix == '.py':
                try:
                    tree = ast.parse(text, filename=str(path))
                    entry['functions'] = [{'name':node.name,'line':node.lineno} for node in ast.walk(tree) if isinstance(node,(ast.FunctionDef,ast.AsyncFunctionDef))]
                    entry['classes'] = [node.name for node in ast.walk(tree) if isinstance(node,ast.ClassDef)]
                except SyntaxError as error:
                    errors.append({'path':str(path.relative_to(ROOT)), 'error':str(error)})
            files.append(entry)
    save('inventory.json', {'files':files, 'file_count':len(files), 'source_lines':sum(item['lines'] for item in files), 'syntax_errors':errors})
    print('SOURCE',len(files),'files',sum(item['lines'] for item in files),'lines; Python syntax errors',len(errors),flush=True)
    datasets = {}
    for game in lr.LIVE_TYPES:
        path = lr.get_canonical_output_paths(game)['all']
        raw = path.read_bytes()
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        ids = []
        dates = []
        issues = []
        hit_counts = Counter()
        for index,row in enumerate(reader,start=2):
            ids.append(int(str(row.get('Kỳ') or '0').lstrip('#')))
            dates.append(row.get('Ngày',''))
            if row.get('Nổ','').strip():
                hit_counts[row['Nổ'].strip()] += 1
            try:
                normalize_row(game,row)
            except Exception as error:
                if len(issues) < 20:
                    issues.append({'line':index, 'error':str(error)})
        counts = Counter(ids)
        sorted_ids = sorted(counts)
        gaps = sum(max(0,right-left-1) for left,right in zip(sorted_ids,sorted_ids[1:]))
        datasets[game] = {'rows':len(ids),'header':reader.fieldnames,'sha256':hashlib.sha256(raw).hexdigest(),'first_draw_id':min(ids,default=0),'last_draw_id':max(ids,default=0),'latest_draw_date':dates[ids.index(max(ids))] if ids else '', 'duplicate_ids':sum(count-1 for count in counts.values()),'missing_ids_between_endpoints':gaps,'schema_matches':reader.fieldnames==lr.get_csv_header(game),'first_validation_issues':issues,'hit_counts':dict(hit_counts)}
        print('DATA',game,json.dumps({key:value for key,value in datasets[game].items() if key not in ('header','sha256')},ensure_ascii=False),flush=True)
    save('datasets.json', datasets)
    database = ROOT / 'runtime/lotto_web.db'
    connection = sqlite3.connect(database.as_uri()+'?mode=ro',uri=True)
    try:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        db_report = {'quick_check':connection.execute('PRAGMA quick_check').fetchone()[0], 'table_counts':{table:connection.execute('SELECT COUNT(*) FROM "'+table.replace('"','""')+'"').fetchone()[0] for table in tables}}
        if 'model_registry' in tables:
            db_report['models'] = [dict(zip(('game_type','status','count'),row)) for row in connection.execute('SELECT game_type,status,COUNT(*) FROM model_registry GROUP BY game_type,status')]
        if 'prediction_runs' in tables:
            db_report['prediction_summary'] = [dict(zip(('game_type','status','count'),row)) for row in connection.execute('SELECT game_type,status,COUNT(*) FROM prediction_runs GROUP BY game_type,status')]
            db_report['missing_model_ids'] = connection.execute("SELECT COUNT(*) FROM prediction_runs WHERE model_id='' OR model_id IS NULL").fetchone()[0]
        save('database_summary.json',db_report)
        print('DB',json.dumps(db_report,ensure_ascii=False),flush=True)
    finally:
        connection.close()
    models = []
    for path in (ROOT / 'ai/standalone_predictors').rglob('*meta*.json'):
        if 'models' not in path.parts:
            continue
        try:
            payload = json.loads(path.read_text(encoding='utf-8-sig'))
            models.append({'path':str(path.relative_to(ROOT)),**{key:payload.get(key) for key in ('game','model_type','version','trained_at','trained_on_latest_draw_id','train_samples','val_samples','metrics')}})
        except Exception as error:
            models.append({'path':str(path.relative_to(ROOT)),'error':str(error)})
    save('deep_models.json',models)
    print('DEEP',json.dumps(models,ensure_ascii=False),flush=True)


def probes():
    from ai import ml_pipeline as ml
    from ai.prediction_ledger import lock_prediction, score_prediction_payload
    from ai.evaluation.probability import scores_to_probabilities
    results = {}
    cfg = ml.game_config('LOTO_6_45')
    for name, metrics in [('missing_probability_metrics',{'fold_count':24}),('nan_probability_metrics',{'fold_count':24,'brier_score':float('nan'),'log_loss':float('nan')}),('baseline_equal',{'fold_count':24,'brier_score':6/45*(1-6/45),'log_loss':.9})]:
        passed,reason = ml._candidate_passes({'validation_metrics':metrics,'outer_backtest_metrics':{}},None,cfg)
        results[name] = {'gate_accepts':passed,'reason':reason}
    with __import__('tempfile').TemporaryDirectory(dir=OUT) as folder:
        locked = lock_prediction({'type':'LOTO_6_45','latestKy':'101','target_draw_id':'100','tickets':[{'main':[1,2,3,4,5,6]}]},db_path=Path(folder)/'ledger.db')
        results['lock_target_before_cutoff'] = {'accepted':locked['status']=='locked','cutoff':locked['data_cutoff_draw_id'],'target':locked['target_draw_id']}
    import random
    rng = random.Random(20261004)
    uniform = {str(n):6/45 for n in range(1,46)}
    portfolios = {count:[{'main':sorted(rng.sample(range(1,46),6))} for _ in range(count)] for count in (1,10)}
    scores = {count:[] for count in portfolios}
    for _ in range(2000):
        actual = {'main':rng.sample(range(1,46),6)}
        for count,tickets in portfolios.items():
            scores[count].append(score_prediction_payload({'tickets':tickets,'probabilities':uniform},actual,45,6,6))
    results['random_portfolio_ledger_bias'] = {str(count):{'draws':len(values),'mean_best_hit':sum(row['hit_count'] for row in values)/len(values),'mean_reported_lift':sum(row['lift'] for row in values)/len(values)} for count,values in scores.items()}
    normalized = scores_to_probabilities({1:100,2:1},6,1,45)
    results['score_normalization_without_calibration'] = {'p_number_1':normalized[1],'sum':sum(normalized.values()),'uniform_p':6/45}
    from ai.analysis.analysis import row_to_draw, GAME_CONFIGS
    from ai.adaptive_coverage import GAME_SPECS
    from ai.stats.stats_v2 import draw_combo_items
    display='Đặc biệt: 001 002 || Giải nhất: 003 004 005 006 || Giải nhì: 007 008 009 010 011 012 || Giải ba: 013 014 015 016 017 018 019 020'
    draw=row_to_draw('MAX_3D',{'date':'01/10/2026','display':display})
    results['max_3d_game_definition_mismatch']={'parsed_unique_numbers':len(draw['numbers']),'analysis_main_count':GAME_CONFIGS['MAX_3D']['main_count'],'adaptive_draw_size':GAME_SPECS['MAX_3D']['drawSize']}
    combos=draw_combo_items('KENO',{'main':list(range(1,21))},'main',4)
    results['keno_combo_window_scope']={'returned_combo_count':len(combos),'all_four_number_combinations':math.comb(20,4),'non_adjacent_combo_present':('01','03','05','07') in combos}
    save('probes.json',results)
    print(json.dumps(results,ensure_ascii=False,indent=2),flush=True)


def backtests():
    from ai import ml_pipeline as ml
    summaries = {}
    for game,folder,csv_name in [('LOTO_5_35','loto_5_35_predictor','loto_5_35_all_day.csv'),('LOTO_6_45','mega_6_45_predictor','mega_6_45_all_day.csv'),('LOTO_6_55','power_6_55_predictor','power_6_55_all_day.csv')]:
        start = time.perf_counter()
        command = [sys.executable,'main.py','backtest','--csv',str(ROOT/'data/canonical'/csv_name),'--mode','fast','--window','expanding']
        result = subprocess.run(command,cwd=ROOT/'ai/standalone_predictors'/folder,capture_output=True,timeout=420)
        (OUT / (game+'_backtest.stderr.log')).write_bytes(result.stderr)
        if result.returncode:
            summaries[game] = {'exit_code':result.returncode,'error':result.stderr.decode(errors='replace')[-1000:]}
        else:
            payload = json.loads(result.stdout.decode('utf-8-sig'))
            ml._add_baseline_comparison(game,payload)
            save(game+'_backtest.json',payload)
            modes = payload.get('modes') or (payload.get('ablation_report') or {}).get('modes') or {}
            summaries[game] = {'elapsed_seconds':round(time.perf_counter()-start,2),'winner_mode':payload.get('winner_mode'),'reported_metrics_mode':(payload.get('metrics') or {}).get('blend_mode'),'baseline_comparison':payload.get('baseline_comparison'),'modes':{name:{key:value for key,value in metrics.items() if key!='folds'}|{'deep_status_counts':dict(Counter(fold.get('deep_status','') for fold in metrics.get('folds',[])))} for name,metrics in modes.items()}}
        save('backtest_summary.json',summaries)
        print(game,json.dumps(summaries[game],ensure_ascii=False),flush=True)
    keno = ml.run_keno_backtest(mode='fast')
    ml._add_baseline_comparison('KENO',keno)
    save('KENO_backtest.json',keno)
    summaries['KENO'] = {'winner_mode':keno['winner_mode'],'baseline_comparison':keno['baseline_comparison'],'metrics':{key:value for key,value in keno['metrics'].items() if key!='folds'}}
    save('backtest_summary.json',summaries)
    print('KENO',json.dumps(summaries['KENO'],ensure_ascii=False),flush=True)


if __name__ == '__main__':
    {'inspect':inspect_project,'probes':probes,'backtests':backtests}[sys.argv[1]]()

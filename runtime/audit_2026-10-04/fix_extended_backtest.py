"""Evaluate a fixed blend over more folds without persisting production state."""
from collections import Counter
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent / 'fixes_backtests'
OUT.mkdir(exist_ok=True)
game = sys.argv[1]
sys.path.insert(0,str(ROOT))
from ai import ml_pipeline as ml
start=time.perf_counter()
if game=='KENO':
    total=len(ml.chronological_actual_draws('KENO'))
    result=ml.run_keno_backtest(mode='full',min_history=total-480)
    metrics=result['metrics']
else:
    folder = {'LOTO_5_35':'loto_5_35_predictor','LOTO_6_45':'mega_6_45_predictor','LOTO_6_55':'power_6_55_predictor'}[game]
    project=ROOT/'ai/standalone_predictors'/folder
    sys.path.insert(0,str(project))
    from src import backtest
    path=ml.dp.get_canonical_csv_read_path(game)
    if game=='LOTO_5_35':
        from src import config, csv_loader
        draws=csv_loader.load_history('loto_5_35',csv_path=path)
        metrics=backtest._evaluate_mode(draws,config.load_config(),'blended',min_history=len(draws)-120,mode='full')
    else:
        from src import data_loader, predictor_api
        bundle=data_loader.load_draw_records(path,column_mapping_path=project/'config/column_mapping.json')
        draws=bundle['records']
        runtime=predictor_api.load_runtime_configuration(project)
        meta=json.loads((project/'models/model_meta.json').read_text(encoding='utf-8'))
        cutoff=int(meta['trained_on_latest_draw_id'])
        first=next(index for index,draw in enumerate(draws) if int(draw.draw_id)>cutoff)
        extra={'time_slot_usable':bool(bundle.get('time_slot_usable'))} if game=='LOTO_6_55' else {}
        metrics=backtest._evaluate_mode(draws,runtime['predictor_config'],runtime['feature_flags'],project,'blended',int(runtime['predictor_config'].get('backup_ticket_count',3)),first,mode='full',**extra)
    result={'metrics':metrics,'fold_predictions':metrics['folds']}
ml._add_baseline_comparison(game,result)
(OUT/(game+'_extended_backtest.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
summary={'game':game,'elapsed_seconds':round(time.perf_counter()-start,2),'fixed_mode':metrics['blend_mode'],'fold_count':metrics['fold_count'],'metrics':{key:value for key,value in metrics.items() if key!='folds'},'baseline_comparison':result['baseline_comparison'],'deep_status_counts':dict(Counter(fold.get('deep_status','') for fold in metrics['folds']))}
(OUT/(game+'_extended_summary.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False))

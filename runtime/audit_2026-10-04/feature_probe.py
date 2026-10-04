from pathlib import Path
import json
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
game = sys.argv[1]
project = ROOT/'ai/standalone_predictors'/(game+'_predictor')
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(project))
from src import data_loader, deep_dataset, feature_engineering, predictor_api, tracking_engine

runtime = predictor_api.load_runtime_configuration(project)
cfg = runtime['predictor_config']
csv_name = {'mega_6_45':'mega_6_45_all_day.csv','power_6_55':'power_6_55_all_day.csv'}[game]
draws = data_loader.load_draw_records(ROOT/'data/canonical'/csv_name,column_mapping_path=project/'config/column_mapping.json')['records']
modulo = {'use_mod9':True} if game=='mega_6_45' else {'use_mod11':True}
context = feature_engineering.build_prediction_context(draws,tracking_engine.clone_default_state(),cfg,target_weekday=4,time_slot_enabled=False,**modulo)
full = deep_dataset.build_inference_sample(draws,cfg)
truncated = deep_dataset.build_inference_sample(context['recent_secondary'],cfg)
names = full['feature_names']
different = np.abs(full['features']-truncated['features']) > 1e-7
report = {'game':game,'same_final_draws':True,'full_history_count':len(draws),'production_context_count':len(context['recent_secondary']),'input_shape':list(full['features'].shape),'different_feature_cells':int(different.sum()),'total_feature_cells':int(different.size),'affected_feature_names':[name for i,name in enumerate(names) if different[:,:,i].any()]}
if 'recent_window_fill' in names:
    i = names.index('recent_window_fill')
    report['full_history_recent_window_fill'] = full['features'][0,:,i].tolist()
    report['production_recent_window_fill'] = truncated['features'][0,:,i].tolist()
(OUT/(game+'_feature_probe.json')).write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
print(json.dumps(report,ensure_ascii=False))

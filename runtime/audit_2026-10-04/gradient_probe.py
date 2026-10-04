from pathlib import Path
import json
import sys
import numpy as np
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from ai.standalone_predictors.shared_deep.numpy_cnn_gru import NumpyCnnGruModel
rng=np.random.default_rng(20261004)
model=NumpyCnnGruModel(input_dim=3,main_dim=4,extra_dim=3,regime_dim=3,conv_channels=3,hidden_size=3,shared_size=4,kernel_size=2,seed=71)
model.b_conv[:]=.1
model.b_shared[:]=.1
x=rng.normal(size=(2,5,3)).astype(np.float32)
y=np.array([[1,0,1,0],[0,1,0,1]],dtype=np.float32)
extra=np.array([1,2]); regime=np.array([0,2])
output,cache=model.forward(x)
loss=model.compute_loss(output,y,extra,regime)
gradients=model.backward(cache,loss['gradients'])
samples=[]
for name,param in model.parameter_dict().items():
    for index in list(np.ndindex(param.shape))[:3]:
        original=float(param[index]); step=.001
        param[index]=original+step
        positive=model.compute_loss(model.forward(x)[0],y,extra,regime)['total_loss']
        param[index]=original-step
        negative=model.compute_loss(model.forward(x)[0],y,extra,regime)['total_loss']
        param[index]=original
        numerical=(positive-negative)/(2*step)
        analytical=float(gradients[name][index])
        samples.append({'parameter':name,'index':list(index),'analytical':analytical,'numerical':numerical,'absolute_error':abs(analytical-numerical)})
report={'sampled_gradient_cells':len(samples),'max_absolute_error':max(row['absolute_error'] for row in samples),'within_absolute_tolerance_0_002':all(row['absolute_error']<.002 for row in samples),'details':samples}
Path(__file__).with_name('gradient_probe.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
print({key:value for key,value in report.items() if key!='details'})

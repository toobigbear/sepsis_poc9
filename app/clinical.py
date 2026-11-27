import json
from datetime import datetime, timezone
from .models import Observation, Patient

SPECS={
 'map':('平均动脉压','mmHg',20,180),'lactate':('乳酸','mmol/L',0.1,30),
 'urine_output':('尿量','mL/h',0,1000),'hr':('心率','次/min',20,250),
 'spo2':('血氧饱和度','%',40,100),'rr':('呼吸频率','次/min',3,80),
 'ne_dose':('去甲肾上腺素','μg/kg/min',0,5),'sofa':('SOFA','分',0,24),
 'urine_na':('尿钠','mmol/L',1,400),'urine_k':('尿钾','mmol/L',1,300),
 'urine_creatinine':('尿肌酐','μmol/L',1,50000),'urine_ph':('尿pH','',3,10),
 'psv':('颈动脉PSV','cm/s',0,500),'edv':('颈动脉EDV','cm/s',0,300),
 'vti':('VTI','cm',0,100),'mic':('MIC','mg/L',0,1024)
}
def validate_fields(fields):
    cleaned=[]; errors=[]
    for i,f in enumerate(fields):
        d=f.model_dump() if hasattr(f,'model_dump') else dict(f)
        code=d.get('code','')
        if code not in SPECS: errors.append(f'字段{i+1}:不支持的指标 {code}'); continue
        name,unit,lo,hi=SPECS[code]; value=d.get('value')
        if value is None: errors.append(f'{name}:数值缺失'); continue
        if d.get('unit')!=unit: errors.append(f'{name}:单位应为 {unit or "无量纲"}'); continue
        if not lo<=float(value)<=hi: errors.append(f'{name}:数值超出允许范围'); continue
        d.update(name=name,value=float(value),observed_at=d.get('observed_at') or datetime.now(timezone.utc).isoformat(timespec='seconds'))
        cleaned.append(d)
    if not cleaned: errors.append('没有可入库的有效观测')
    return {'valid':not errors,'errors':errors,'fields':cleaned}
def latest_map(db,patient_id):
    rows=db.query(Observation).filter_by(patient_id=patient_id,review_status='已复核').order_by(Observation.observed_at.desc(),Observation.id.desc()).all()
    out={}
    for r in rows:
        if r.code not in out: out[r.code]=r.value
    return out
def risk_from_values(v,sofa=0):
    score=min(35,max(0,(90-v.get('map',75))*1.4))+min(25,max(0,(v.get('lactate',1.5)-1.5)*8))+min(15,max(0,(35-v.get('urine_output',50))/3))+min(15,v.get('ne_dose',0)*35)+min(10,sofa*0.7)
    score=round(max(0,min(100,score)),1)
    return score,'高' if score>=55 else '中' if score>=25 else '低'
def refresh_risk(db,patient):
    score,level=risk_from_values(latest_map(db,patient.id),patient.sofa); patient.risk_score=score; patient.risk_level=level; return score,level
def simulate(patient,obs):
    base_map=obs.get('map',65); base_lac=obs.get('lactate',3); base_uo=obs.get('urine_output',25)
    plans=[('限制性液体管理路径',0.10,0.12,0.06,'控制液体暴露，动态评估灌注与液体反应性'),('积极液体复苏路径',0.24,0.18,0.16,'以组织低灌注为依据，连续评估液体过负荷风险'),('液体与血管活性药物联合路径',0.34,0.24,0.20,'液体与血管活性药物协同，持续评估容量状态')]
    branches=[]
    for name,map_gain,lac_drop,uo_gain,assumption in plans:
        traj=[]
        for h in range(8):
            factor=h/7
            traj.append({'hour':h,'map':round(base_map*(1+map_gain*factor),1),'lactate':round(max(.4,base_lac*(1-lac_drop*factor)),2),'urine_output':round(base_uo*(1+uo_gain*factor),1)})
        risks=['推演依赖当前观测完整性','未纳入未测量生理代偿']+(['关注肺水肿及组织水肿风险'] if '积极' in name else ['关注持续低灌注风险'] if '限制性' in name else ['关注血管活性药物不良反应及液体过负荷'])
        branches.append({'name':name,'trajectory':traj,'assumptions':assumption,'uncertainty':'轨迹为确定性内部推演，非患者结局预测；实际变化需结合连续评估。','risks':risks})
    return {'branches':branches,'input':{'patient_id':patient['id'],'observation_revision':patient['observation_revision'],'observations':obs}}
def dumps(v): return json.dumps(v,ensure_ascii=False,separators=(',',':'))
def loads(v,default=None):
    try:return json.loads(v)
    except (TypeError,json.JSONDecodeError):return default

import hashlib
from datetime import datetime, timedelta, timezone
from .db import Base, engine, SessionLocal
from .models import *
from .security import password_hash
from .clinical import refresh_risk, dumps

PATIENTS=[('P001','ICU-01','张启明',67,'男','肺部感染并感染性休克',11,58,5.4,18,.32),('P002','ICU-02','李淑珍',72,'女','腹腔感染',8,67,3.1,28,.12),('P003','ICU-03','王建国',59,'男','尿路感染',6,74,2.2,42,.04),('P004','ICU-04','赵文秀',81,'女','肺部感染',9,70,2.7,35,.08),('P005','ICU-05','陈国栋',46,'男','术后腹腔感染',4,82,1.4,65,0),('P006','ICU-06','刘雅琴',63,'女','胆道感染',5,78,1.8,55,0)]
EVIDENCE=[('Recommendation 1','For patients with sepsis induced hypoperfusion or septic shock we suggest that at least 30 mL/kg of intravenous crystalloid should be given within the first 3 hr of resuscitation.'),('Recommendation 43','For patients with sepsis or septic shock, we suggest using crystalloids as first-line fluid for resuscitation.'),('Recommendation 49','For patients with septic shock, we suggest using norepinephrine as the first-line agent over other vasopressors.')]

def init_db():
    Base.metadata.create_all(engine)
    db=SessionLocal()
    if db.query(Patient).count(): db.close(); return
    db.add_all([User(id='clinician',name='王医生',role='clinician',password_hash=password_hash('clinician123')),User(id='engineer',name='陈工程师',role='engineer',password_hash=password_hash('engineer123'))])
    base=datetime.now(timezone.utc).replace(microsecond=0)
    for pid,bed,name,age,sex,diag,sofa,mapv,lac,uo,ne in PATIENTS:
        db.add(Patient(id=pid,bed=bed,name=name,age=age,sex=sex,diagnosis=diag,sofa=sofa))
        db.flush()
        db.add(Encounter(patient_id=pid,admitted_at=(base-timedelta(days=1)).isoformat(),infection_source=diag,comorbidities='高血压' if age>65 else '无特殊'))
        for h in range(8):
            t=(base-timedelta(hours=7-h)).isoformat(timespec='seconds')
            for code,label,value,unit in [('map','平均动脉压',mapv+(7-h)*.7,'mmHg'),('lactate','乳酸',max(.6,lac-(7-h)*.08),'mmol/L'),('urine_output','尿量',uo+(7-h)*1.2,'mL/h'),('hr','心率',108+(7-h)%4,'次/min'),('spo2','血氧饱和度',94+(7-h)%3,'%'),('rr','呼吸频率',24+(7-h)%3,'次/min'),('ne_dose','去甲肾上腺素',ne,'μg/kg/min')]:
                db.add(Observation(patient_id=pid,code=code,name=label,value=round(value,3),unit=unit,observed_at=t,source='中央监护',revision=1,dedup_key=f'{pid}:{code}:{t}'))
        p=db.get(Patient,pid); score,level=refresh_risk(db,p)
        if level!='低': db.add(Alert(patient_id=pid,severity='高危' if level=='高' else '关注',title='脓毒症风险预警',reason=f'当前风险评分 {score}，请结合乳酸、MAP、尿量及感染情况综合评估。'))
    doc_id='SSC2021'; raw=''.join(t for _,t in EVIDENCE).encode()
    db.add(EvidenceDocument(id=doc_id,title='Surviving Sepsis Campaign: International Guidelines for Management of Sepsis and Septic Shock 2021',version='2021',source='Evans L, et al. Intensive Care Med. 2021;47:1181–1247. DOI:10.1007/s00134-021-06506-y',file_sha256=hashlib.sha256(raw).hexdigest()))
    db.flush()
    for i,(section,text) in enumerate(EVIDENCE): db.add(EvidenceChunk(id=f'SSC2021-{i+1}',document_id=doc_id,section=section,locator=section,text=text,vector_position=i))
    db.add_all([PolicyVersion(name='脓毒症预警策略',version='2.4.1',status='当前生效',metrics_json=dumps({'灵敏度':.88,'特异度':.84,'假阳性率':.16})),PolicyVersion(name='脓毒症预警策略',version='2.3.8',status='历史版本',metrics_json=dumps({'灵敏度':.84,'特异度':.86,'假阳性率':.14}))])
    db.commit(); db.close()

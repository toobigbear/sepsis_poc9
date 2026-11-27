import asyncio, logging, sys
from mcp.server.mcpserver import MCPServer
from .db import SessionLocal
from .models import Patient, Observation, Alert, AuditEvent
from .clinical import simulate, validate_fields, refresh_risk
from .rag import search
from .lm import vision_extract
from .models import ObservationRevision
from .config import settings

ALLOWED={'patient','simulation','rag','vision','safety','review','audit'}
def patient_json(p): return {'id':p.id,'bed':p.bed,'name':p.name,'age':p.age,'sex':p.sex,'diagnosis':p.diagnosis,'sofa':p.sofa,'risk_score':p.risk_score,'risk_level':p.risk_level,'observation_revision':p.observation_revision}
def observation_json(o): return {'id':o.id,'code':o.code,'name':o.name,'value':o.value,'unit':o.unit,'observed_at':o.observed_at,'source':o.source,'review_status':o.review_status,'revision':o.revision}
def make_server(kind):
    m=MCPServer(name=f'sepsis-{kind}',version='1.0.0')
    if kind=='patient':
        @m.tool(name='patient.get',description='读取患者及最新复核观测')
        def get_patient(patient_id:str):
            db=SessionLocal(); p=db.get(Patient,patient_id)
            if not p: db.close(); raise ValueError('患者不存在')
            obs=db.query(Observation).filter_by(patient_id=patient_id).order_by(Observation.observed_at.desc()).limit(100).all()
            out={'patient':patient_json(p),'observations':[observation_json(o) for o in obs]}; db.close(); return out
        @m.tool(name='patient.timeline',description='读取患者时间轴')
        def timeline(patient_id:str):
            db=SessionLocal(); obs=db.query(Observation).filter_by(patient_id=patient_id).order_by(Observation.observed_at.desc()).limit(200).all(); alerts=db.query(Alert).filter_by(patient_id=patient_id).order_by(Alert.id.desc()).all(); db.close()
            return {'observations':[observation_json(o) for o in obs],'alerts':[{'id':a.id,'title':a.title,'status':a.status,'severity':a.severity,'created_at':a.created_at} for a in alerts]}
        @m.tool(name='observation.query',description='按指标查询已复核观测')
        def obs_query(patient_id:str,code:str=''):
            db=SessionLocal(); q=db.query(Observation).filter_by(patient_id=patient_id,review_status='已复核')
            if code: q=q.filter_by(code=code)
            rows=q.order_by(Observation.observed_at.desc()).limit(200).all(); db.close(); return {'observations':[observation_json(o) for o in rows]}
    elif kind=='simulation':
        @m.tool(name='simulation.run',description='运行无状态确定性反事实推演')
        def run_simulation(patient:dict,observations:dict): return simulate(patient,observations)
    elif kind=='rag':
        @m.tool(name='guideline.search',description='检索本地正式指南证据')
        async def guideline_search(query:str,limit:int=4): return await search(query,limit)
    elif kind=='vision':
        @m.tool(name='vision.extract',description='使用本地视觉模型提取图片字段')
        async def extract(file_id:str,file_sha256:str,normalized_path:str,document_type:str='lab_report'):
            try:
                payload=await vision_extract(normalized_path,document_type); return {'ok':True,'file_id':file_id,'file_sha256':file_sha256,'model_id':settings.vision_model,'payload':payload}
            except Exception as e: return {'ok':False,'file_id':file_id,'file_sha256':file_sha256,'model_id':settings.vision_model,'error':str(e)[:500]}
    elif kind=='safety':
        @m.tool(name='safety.validate',description='校验指标白名单、单位和数值范围')
        def validate(fields:list[dict]): return validate_fields(fields)
    elif kind=='review':
        @m.tool(name='review.commit',description='医生复核后的唯一临床观测写入口')
        def commit(patient_id:str,fields:list[dict],actor:dict,source:str,reason:str,dedup_prefix:str):
            if actor.get('role')!='clinician': raise PermissionError('仅临床医生可写入观测')
            checked=validate_fields(fields)
            if not checked['valid']: raise ValueError('；'.join(checked['errors']))
            db=SessionLocal(); inserted=0
            try:
                p=db.get(Patient,patient_id)
                if not p: raise ValueError('患者不存在')
                revision=p.observation_revision+1
                for f in checked['fields']:
                    key=f"{dedup_prefix}:{f['code']}"
                    if db.query(Observation).filter_by(dedup_key=key).first(): continue
                    db.add(Observation(patient_id=patient_id,code=f['code'],name=f['name'],value=f['value'],unit=f['unit'],observed_at=f['observed_at'],source=source,revision=revision,dedup_key=key)); inserted+=1
                if inserted:
                    p.observation_revision=revision; db.add(ObservationRevision(patient_id=patient_id,revision=revision,reason=reason,actor_id=actor['actor_id'])); refresh_risk(db,p)
                db.commit(); return {'ok':True,'inserted':inserted,'observation_revision':p.observation_revision,'risk_score':p.risk_score,'risk_level':p.risk_level}
            except Exception: db.rollback(); raise
            finally: db.close()
    elif kind=='audit':
        @m.tool(name='audit.query',description='只读查询审计事件')
        def audit_query(patient_id:str='',limit:int=100):
            db=SessionLocal(); q=db.query(AuditEvent)
            if patient_id: q=q.filter_by(patient_id=patient_id)
            rows=q.order_by(AuditEvent.id.desc()).limit(min(limit,200)).all(); db.close()
            return {'events':[{'id':a.id,'trace_id':a.trace_id,'actor_id':a.actor_id,'action':a.action,'patient_id':a.patient_id,'detail_json':a.detail_json,'created_at':a.created_at} for a in rows]}
    return m
if __name__=='__main__':
    logging.basicConfig(level=logging.INFO,stream=sys.stderr,format='%(asctime)s %(levelname)s %(name)s %(message)s')
    kind=sys.argv[1] if len(sys.argv)>1 else ''
    if kind not in ALLOWED: raise SystemExit(2)
    asyncio.run(make_server(kind).run_stdio_async())

import hashlib, io, json, uuid
from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Form, Request, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, ImageOps
from sqlalchemy.orm import Session
from .config import settings, ROOT
from .db import get_db, SessionLocal
from .models import *
from .schemas import *
from .security import current_user, optional_user, clinician, actor, login as create_login, logout as end_login, verify, COOKIE
from .seed import init_db
from .clinical import validate_fields, latest_map, simulate, dumps, loads
from .mcp_host import host
from .lm import health as lm_health, chat

@asynccontextmanager
async def lifespan(_):
    init_db(); await host.start()
    try: yield
    finally: await host.close()
app=FastAPI(title='脓毒症智能预警与多模态推演工作站',lifespan=lifespan)

def audit(db,user,action,patient_id='',detail=None):
    db.add(AuditEvent(trace_id=uuid.uuid4().hex,actor_id=user.id if hasattr(user,'id') else str(user),action=action,patient_id=patient_id,detail_json=dumps(detail or {})))
def pj(p):
    return {'id':p.id,'bed':p.bed,'name':p.name,'age':p.age,'sex':p.sex,'diagnosis':p.diagnosis,'sofa':p.sofa,'risk_score':p.risk_score,'risk_level':p.risk_level,'observation_revision':p.observation_revision}
def oj(o):
    return {'id':o.id,'code':o.code,'name':o.name,'value':o.value,'unit':o.unit,'observed_at':o.observed_at,'source':o.source,'review_status':o.review_status,'revision':o.revision}
def aj(a): return {'id':a.id,'patient_id':a.patient_id,'severity':a.severity,'title':a.title,'reason':a.reason,'status':a.status,'created_at':a.created_at}
def patient_or_404(db,pid):
    p=db.get(Patient,pid)
    if not p: raise HTTPException(404,'患者不存在')
    return p
def extraction_or_404(db,vid):
    v=db.get(VisionExtraction,vid)
    if not v: raise HTTPException(404,'识别记录不存在')
    return v
async def reviewed_commit(patient_id,fields,user,source,reason,dedup_prefix):
    safe=await host.call('safety.validate',{'fields':fields},actor(user),patient_id)
    if not safe['valid']: raise HTTPException(422,'；'.join(safe['errors']))
    return await host.call('review.commit',{'patient_id':patient_id,'fields':safe['fields'],'actor':actor(user).model_dump(),'source':source,'reason':reason,'dedup_prefix':dedup_prefix},actor(user),patient_id)

@app.post('/api/session/login')
def session_login(body:LoginIn,response:Response,db:Session=Depends(get_db)):
    user=db.get(User,body.username)
    if not user or not verify(body.password,user.password_hash): raise HTTPException(401,'用户名或密码错误')
    result=create_login(response,user,db); audit(db,user,'用户登录'); db.commit(); return {'actor':result,'name':user.name}
@app.post('/api/session/logout')
def session_logout(response:Response,request:Request,db:Session=Depends(get_db)):
    end_login(response,request,db); return {'ok':True}
@app.get('/api/session/current')
def session_current(user:User=Depends(optional_user)): return {'actor':actor(user),'name':user.name} if user else {'actor':None,'name':''}

@app.get('/api/ward/census')
def census(db:Session=Depends(get_db),_:User=Depends(current_user)):
    patients=db.query(Patient).order_by(Patient.bed).all(); return {'items':[pj(p) for p in patients],'summary':{'total':len(patients),'high':sum(p.risk_level=='高' for p in patients),'alerts':db.query(Alert).filter_by(status='未处理').count()}}
@app.get('/api/patients/{pid}')
def patient_detail(pid:str,db:Session=Depends(get_db),_:User=Depends(current_user)):
    p=patient_or_404(db,pid); e=db.query(Encounter).filter_by(patient_id=pid).first()
    return {**pj(p),'encounter':{'admitted_at':e.admitted_at,'infection_source':e.infection_source,'comorbidities':e.comorbidities} if e else None}
@app.get('/api/patients/{pid}/timeline')
def timeline(pid:str,hours:int=168,db:Session=Depends(get_db),_:User=Depends(current_user)):
    patient_or_404(db,pid)
    obs=db.query(Observation).filter_by(patient_id=pid).order_by(Observation.observed_at.desc()).limit(300).all()
    alerts=db.query(Alert).filter_by(patient_id=pid).order_by(Alert.id.desc()).all()
    docs=db.query(Document).filter_by(patient_id=pid).order_by(Document.created_at.desc()).all()
    runs=db.query(SimulationRun).filter_by(patient_id=pid).order_by(SimulationRun.created_at.desc()).limit(10).all()
    briefs=db.query(ClinicalBrief).filter_by(patient_id=pid).order_by(ClinicalBrief.id.desc()).limit(5).all()
    return {'observations':[oj(o) for o in obs],'alerts':[aj(a) for a in alerts],'documents':[{'id':d.id,'kind':d.kind,'status':d.status,'created_at':d.created_at} for d in docs],'simulations':[{'id':r.id,'created_at':r.created_at,'input_observation_revision':r.input_observation_revision} for r in runs],'briefs':[{'id':b.id,'updated_at':b.updated_at} for b in briefs]}
@app.get('/api/alerts')
def alerts(status:str='',page:int=1,page_size:int=30,db:Session=Depends(get_db),_:User=Depends(current_user)):
    q=db.query(Alert)
    if status:q=q.filter_by(status=status)
    total=q.count(); rows=q.order_by(Alert.id.desc()).offset(max(0,page-1)*page_size).limit(min(page_size,100)).all()
    return {'total':total,'items':[{**aj(a),'patient':pj(db.get(Patient,a.patient_id))} for a in rows]}
def alert_action(aid:int,action:str,note:str,db:Session,user:User):
    a=db.get(Alert,aid)
    if not a:raise HTTPException(404,'预警不存在')
    a.status='已确认' if action=='确认' else '已关闭'; db.add(AlertEvent(alert_id=aid,action=action,note=note,actor_id=user.id)); audit(db,user,f'预警{action}',a.patient_id,{'alert_id':aid,'note':note}); db.commit(); return aj(a)
@app.post('/api/alerts/{aid}/acknowledge')
def acknowledge(aid:int,body:NoteIn=NoteIn(),db:Session=Depends(get_db),user:User=Depends(clinician)): return alert_action(aid,'确认',body.note,db,user)
@app.post('/api/alerts/{aid}/close')
def close_alert(aid:int,body:NoteIn=NoteIn(),db:Session=Depends(get_db),user:User=Depends(clinician)): return alert_action(aid,'关闭',body.note,db,user)

@app.post('/api/documents')
async def upload_document(patient_id:str=Form(...),kind:str=Form(...),file:UploadFile=File(...),db:Session=Depends(get_db),user:User=Depends(clinician)):
    patient_or_404(db,patient_id)
    if kind not in ['lab_report','monitor','pmut']:raise HTTPException(422,'资料类型不支持')
    raw=await file.read(12*1024*1024+1)
    if len(raw)>12*1024*1024:raise HTTPException(413,'图片不能超过12MB')
    try:
        im=Image.open(io.BytesIO(raw)); im.load(); fmt=(im.format or 'PNG').lower(); im=ImageOps.exif_transpose(im); im.thumbnail((2048,2048))
        out=io.BytesIO(); im.convert('RGB').save(out,'PNG'); normalized=out.getvalue()
    except Exception:raise HTTPException(422,'无法读取有效图片')
    sha=hashlib.sha256(raw).hexdigest(); nsha=hashlib.sha256(normalized).hexdigest(); root=Path(settings.image_storage_dir)
    original=root/'original'/f'{sha}.{fmt}'; normal=root/'normalized'/f'{nsha}.png'; original.parent.mkdir(parents=True,exist_ok=True); normal.parent.mkdir(parents=True,exist_ok=True)
    if not original.exists():original.write_bytes(raw)
    if not normal.exists():normal.write_bytes(normalized)
    doc=Document(id=uuid.uuid4().hex,patient_id=patient_id,kind=kind,original_path=str(original),normalized_path=str(normal),file_sha256=sha,normalized_sha256=nsha,file_size=len(raw),mime=Image.MIME.get(fmt.upper(),'application/octet-stream'),uploaded_by=user.id)
    db.add(doc); audit(db,user,'上传临床图像',patient_id,{'document_id':doc.id,'sha256':sha}); db.commit(); return {'id':doc.id,'status':doc.status}
@app.get('/api/documents/{did}/image')
def document_image(did:str,variant:str='normalized',db:Session=Depends(get_db),_:User=Depends(current_user)):
    d=db.get(Document,did)
    if not d:raise HTTPException(404,'文件不存在')
    return FileResponse(d.original_path if variant=='original' else d.normalized_path)
@app.post('/api/vision/extract')
async def extract(body:ExtractIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    d=db.get(Document,body.document_id)
    if not d:raise HTTPException(404,'图像资料不存在')
    existing=db.query(VisionExtraction).filter_by(document_id=d.id).order_by(VisionExtraction.created_at.desc()).first()
    if existing and existing.status in ['pending_review','confirmed']:return vision_json(existing)
    v=VisionExtraction(id=uuid.uuid4().hex,document_id=d.id,patient_id=d.patient_id,status='processing'); db.add(v); db.commit()
    try:
        result=await host.call('vision.extract',{'file_id':d.id,'file_sha256':d.file_sha256,'normalized_path':d.normalized_path,'document_type':d.kind},actor(user),d.patient_id)
        if not result.get('ok'):v.status='failed'; v.error=result.get('error','视觉服务不可用'); v.model_id=result.get('model_id','')
        else:
            payload=normalize_vision_payload(result['payload'],d.kind); checked=validate_fields(payload.fields)
            v.raw_json=dumps(payload.model_dump()); v.validation_json=dumps(checked); v.status='pending_review'; v.model_id=result.get('model_id','')
        d.status='识别失败' if v.status=='failed' else '待复核'
    except Exception as e:v.status='failed';v.error=str(e)[:500];d.status='识别失败'
    audit(db,user,'图像字段识别',d.patient_id,{'extraction_id':v.id,'status':v.status}); db.commit(); return vision_json(v)
def vision_json(v):
    payload=loads(v.raw_json,{}) or {}; return {'id':v.id,'document_id':v.document_id,'patient_id':v.patient_id,'status':v.status,'payload':payload,'validation':loads(v.validation_json,{}) or {},'model_id':v.model_id,'error':v.error,'created_at':v.created_at}
@app.get('/api/vision')
def vision_list(patient_id:str='',db:Session=Depends(get_db),_:User=Depends(current_user)):
    q=db.query(VisionExtraction)
    if patient_id:q=q.filter_by(patient_id=patient_id)
    return {'items':[vision_json(v) for v in q.order_by(VisionExtraction.created_at.desc()).limit(100).all()]}
@app.get('/api/vision/{vid}')
def vision_detail(vid:str,db:Session=Depends(get_db),_:User=Depends(current_user)):return vision_json(extraction_or_404(db,vid))
@app.post('/api/vision/{vid}/confirm')
async def confirm_vision(vid:str,body:ConfirmIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    v=extraction_or_404(db,vid)
    if v.status=='confirmed':return {'ok':True,'id':v.id,'idempotent':True}
    if v.status!='pending_review':raise HTTPException(409,'当前状态不可确认')
    checked=validate_fields(body.fields)
    if not checked['valid']:raise HTTPException(422,'；'.join(checked['errors']))
    v.status='confirming';db.commit()
    try:
        result=await reviewed_commit(v.patient_id,[f.model_dump() for f in body.fields],user,'图像识别','图像识别人工复核',f'vision:{v.id}')
        v.status='confirmed';v.reviewed_json=dumps(checked['fields']);db.add(ObservationReview(extraction_id=v.id,action='确认',actor_id=user.id,reason=body.reason));audit(db,user,'确认图像识别观测',v.patient_id,result);db.commit();return {'ok':True,**result}
    except Exception as e:
        v.status='pending_review';v.error=str(e)[:500];db.commit();raise HTTPException(502,'复核入库失败，请重试')
@app.post('/api/vision/{vid}/reject')
def reject_vision(vid:str,body:RejectIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    v=extraction_or_404(db,vid)
    if v.status=='confirmed':raise HTTPException(409,'已确认记录不能驳回')
    v.status='rejected';db.add(ObservationReview(extraction_id=v.id,action='驳回',actor_id=user.id,reason=body.reason));audit(db,user,'驳回图像识别观测',v.patient_id,{'reason':body.reason});db.commit();return {'ok':True}
@app.post('/api/observations/manual')
async def manual_observation(body:ManualIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    patient_or_404(db,body.patient_id)
    result=await reviewed_commit(body.patient_id,[f.model_dump() for f in body.fields],user,'人工录入','人工录入复核',f'manual:{body.request_id}')
    audit(db,user,'人工录入观测',body.patient_id,result);db.commit();return result
@app.post('/api/adapters/{kind}')
async def adapter_import(kind:str,body:AdapterIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    if kind not in ['urine','pmut','ast']:raise HTTPException(404,'适配器不存在')
    patient_or_404(db,body.patient_id)
    result=await reviewed_commit(body.patient_id,[f.model_dump() for f in body.fields],user,{'urine':'尿液生化','pmut':'PMUT超声','ast':'微流控药敏'}[kind],'结构化数据导入',f'adapter:{kind}:{body.request_id}')
    audit(db,user,'专科数据导入',body.patient_id,{'kind':kind,**result});db.commit();return result

def simulation_json(db,r):
    p=db.get(Patient,r.patient_id); branches=db.query(SimulationBranch).filter_by(run_id=r.id).all()
    return {'id':r.id,'patient_id':r.patient_id,'input_observation_revision':r.input_observation_revision,'current_observation_revision':p.observation_revision,'is_outdated':r.input_observation_revision<p.observation_revision,'input_snapshot':loads(r.input_snapshot,{}),'created_at':r.created_at,'branches':[{'name':b.name,'trajectory':loads(b.trajectory_json,[]),'assumptions':b.assumptions,'uncertainty':b.uncertainty,'risks':loads(b.risks,[])} for b in branches]}
@app.post('/api/simulations')
async def run_simulation(body:BriefIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    p=patient_or_404(db,body.patient_id); obs=latest_map(db,p.id); snapshot={'patient':pj(p),'observations':obs}
    result=await host.call('simulation.run',{'patient':pj(p),'observations':obs},actor(user),p.id)
    evidence=await host.call('guideline.search',{'query':'sepsis crystalloid norepinephrine fluid resuscitation','limit':3},actor(user),p.id)
    run=SimulationRun(id=uuid.uuid4().hex,patient_id=p.id,input_observation_revision=p.observation_revision,input_snapshot=dumps(snapshot));db.add(run);db.flush()
    for b in result['branches']:db.add(SimulationBranch(run_id=run.id,name=b['name'],trajectory_json=dumps(b['trajectory']),assumptions=b['assumptions'],uncertainty=b['uncertainty'],risks=dumps(b['risks'])))
    for e in evidence.get('results',[]):db.add(EvidenceLink(simulation_id=run.id,chunk_id=e['chunk_id']))
    audit(db,user,'创建干预路径推演',p.id,{'simulation_id':run.id});db.commit();return {**simulation_json(db,run),'evidence':evidence}
@app.get('/api/simulations')
def simulations(patient_id:str,db:Session=Depends(get_db),_:User=Depends(current_user)):
    rows=db.query(SimulationRun).filter_by(patient_id=patient_id).order_by(SimulationRun.created_at.desc()).limit(30).all();return {'items':[simulation_json(db,r) for r in rows]}
@app.get('/api/simulations/{sid}')
def simulation_detail(sid:str,db:Session=Depends(get_db),_:User=Depends(current_user)):
    r=db.get(SimulationRun,sid)
    if not r:raise HTTPException(404,'推演记录不存在')
    links=db.query(EvidenceLink).filter_by(simulation_id=sid).all();ev=[]
    for link in links:
        c=db.get(EvidenceChunk,link.chunk_id);d=db.get(EvidenceDocument,c.document_id);ev.append({'chunk_id':c.id,'text':c.text,'section':c.section,'title':d.title,'source':d.source})
    return {**simulation_json(db,r),'evidence':{'status':'ok','results':ev}}

def template_brief(p,obs):
    return f"【交接班摘要】{p.bed}床 {p.name}，{p.age}岁，主要诊断：{p.diagnosis}。当前SOFA {p.sofa}分，风险评分{p.risk_score}（{p.risk_level}风险）。MAP {obs.get('map','未记录')} mmHg，乳酸{obs.get('lactate','未记录')} mmol/L，尿量{obs.get('urine_output','未记录')} mL/h，去甲肾上腺素{obs.get('ne_dose','未记录')} μg/kg/min。重点复核灌注变化、乳酸清除、尿量及液体反应性；所有干预路径均需结合床旁评估。"
@app.post('/api/briefs')
async def create_brief(body:BriefIn,db:Session=Depends(get_db),user:User=Depends(clinician)):
    p=patient_or_404(db,body.patient_id);obs=latest_map(db,p.id);content=template_brief(p,obs);mode='结构化模板'
    try:content,model=await chat(dumps({'patient':pj(p),'observations':obs}));mode=f'本地模型:{model}'
    except Exception:pass
    b=ClinicalBrief(patient_id=p.id,content=content,generation_mode=mode,updated_by=user.id,updated_at=now());db.add(b);db.flush();audit(db,user,'生成交接班简报',p.id,{'brief_id':b.id,'mode':mode});db.commit();return brief_json(b)
def brief_json(b):return {'id':b.id,'patient_id':b.patient_id,'content':b.content,'generation_mode':b.generation_mode,'updated_by':b.updated_by,'updated_at':b.updated_at}
@app.get('/api/briefs')
def briefs(patient_id:str,db:Session=Depends(get_db),_:User=Depends(current_user)):
    rows=db.query(ClinicalBrief).filter_by(patient_id=patient_id).order_by(ClinicalBrief.id.desc()).limit(20).all();return {'items':[brief_json(b) for b in rows]}
@app.put('/api/briefs/{bid}')
def edit_brief(bid:int,body:BriefEdit,db:Session=Depends(get_db),user:User=Depends(clinician)):
    b=db.get(ClinicalBrief,bid)
    if not b:raise HTTPException(404,'简报不存在')
    b.content=body.content;b.updated_by=user.id;b.updated_at=now();audit(db,user,'编辑交接班简报',b.patient_id,{'brief_id':bid});db.commit();return brief_json(b)

@app.get('/api/evidence')
async def evidence(q:str='sepsis fluid',user:User=Depends(current_user)):return await host.call('guideline.search',{'query':q,'limit':5},actor(user))
@app.get('/api/audit')
def audit_list(patient_id:str='',page:int=1,page_size:int=50,db:Session=Depends(get_db),_:User=Depends(current_user)):
    q=db.query(AuditEvent)
    if patient_id:q=q.filter_by(patient_id=patient_id)
    total=q.count();rows=q.order_by(AuditEvent.id.desc()).offset((page-1)*page_size).limit(min(page_size,100)).all()
    return {'total':total,'items':[{'id':a.id,'trace_id':a.trace_id,'actor_id':a.actor_id,'action':a.action,'patient_id':a.patient_id,'detail':loads(a.detail_json,{}),'created_at':a.created_at} for a in rows]}
@app.get('/api/mcp/tools')
async def mcp_tools(_:User=Depends(current_user)):return {'items':await host.tools()}
@app.get('/api/mcp/health')
def mcp_health(_:User=Depends(current_user)):return host.health()
@app.get('/api/mcp/calls')
def mcp_calls(db:Session=Depends(get_db),_:User=Depends(current_user)):
    rows=db.query(MCPToolCall).order_by(MCPToolCall.id.desc()).limit(100).all();return {'items':[{'id':r.id,'trace_id':r.trace_id,'server':r.server,'tool':r.tool,'actor_id':r.actor_id,'status':r.status,'duration_ms':r.duration_ms,'error':r.error,'created_at':r.created_at} for r in rows]}
@app.post('/api/mcp/call')
async def mcp_call(body:dict,user:User=Depends(current_user)):
    tool=body.get('tool','');readonly={'patient.get','patient.timeline','observation.query','guideline.search','audit.query','safety.validate'}
    if tool not in readonly:
        db=SessionLocal();audit(db,user,'拒绝非只读诊断调用',detail={'tool':tool});db.commit();db.close()
        if tool not in TOOL_SERVER: await host.call(tool,body.get('args',{}),actor(user))
        raise HTTPException(403,'诊断接口仅允许只读工具')
    return await host.call(tool,body.get('args',{}),actor(user))
from .mcp_host import TOOL_SERVER
@app.get('/api/system/health')
async def system_health(_:User=Depends(current_user)):return {'lm_studio':await lm_health(),'mcp':host.health(),'database':'ready'}
@app.get('/api/quality')
def quality(patient_id:str,db:Session=Depends(get_db),_:User=Depends(current_user)):
    p=patient_or_404(db,patient_id);pending=db.query(VisionExtraction).filter_by(patient_id=patient_id,status='pending_review').count();runs=db.query(SimulationRun).filter_by(patient_id=patient_id).all();obs=db.query(Observation).filter_by(patient_id=patient_id).count()
    return {'patient_id':patient_id,'pending_reviews':pending,'outdated_simulations':sum(r.input_observation_revision<p.observation_revision for r in runs),'observation_count':obs,'current_revision':p.observation_revision,'completeness':min(100,round(obs/56*100))}
@app.get('/api/policies')
def policies(db:Session=Depends(get_db),_:User=Depends(current_user)):return {'items':[{'id':p.id,'name':p.name,'version':p.version,'status':p.status,'metrics':loads(p.metrics_json,{}),'created_at':p.created_at} for p in db.query(PolicyVersion).order_by(PolicyVersion.id.desc()).all()]}
@app.post('/api/policies/{pid}/activate')
def activate_policy(pid:int,db:Session=Depends(get_db),user:User=Depends(clinician)):
    target=db.get(PolicyVersion,pid)
    if not target:raise HTTPException(404,'策略版本不存在')
    for p in db.query(PolicyVersion).filter_by(name=target.name).all():p.status='历史版本'
    target.status='当前生效';audit(db,user,'切换预警策略版本',detail={'policy_id':pid});db.commit();return {'ok':True}

@app.get('/',include_in_schema=False)
def index():return FileResponse(ROOT/'static'/'index.html')
app.mount('/static',StaticFiles(directory=ROOT/'static'),name='static')

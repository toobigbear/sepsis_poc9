import asyncio, io, os, tempfile, uuid
from pathlib import Path
import pytest
from PIL import Image

TMP=tempfile.mkdtemp(prefix='sepsis-tests-')
os.environ['DATABASE_URL']='sqlite:///'+TMP+'/test.db'
os.environ['IMAGE_STORAGE_DIR']=TMP+'/uploads'
os.environ['LOG_DIR']=TMP+'/logs'
os.environ['FAISS_INDEX_PATH']=TMP+'/vector/test.index'
os.environ['RAG_EMBED_MODE']='hash'
os.environ['MCP_VISION_TIMEOUT']='2'

from fastapi.testclient import TestClient
from app.main import app
from app.db import SessionLocal
from app.models import Document, VisionExtraction, Observation, EvidenceLink
from app.mcp_host import MCPProcess
from app.config import settings

@pytest.fixture(scope='session')
def client():
    with TestClient(app) as c: yield c

def login(c,user='clinician'):
    password='clinician123' if user=='clinician' else 'engineer123'
    r=c.post('/api/session/login',json={'username':user,'password':password});assert r.status_code==200

def test_auth_and_census(client):
    assert client.get('/api/ward/census').status_code==401
    assert client.post('/api/session/login',json={'username':'clinician','password':'wrong'}).status_code==401
    login(client)
    d=client.get('/api/ward/census').json();assert len(d['items'])==6;assert d['summary']['total']==6

def test_mcp_registry_and_evidence_rebuild(client):
    login(client)
    tools=client.get('/api/mcp/tools').json()['items'];assert len(tools)==9
    Path(settings.faiss_index_path).unlink(missing_ok=True);Path(settings.faiss_index_path+'.json').unlink(missing_ok=True)
    d=client.get('/api/evidence',params={'q':'sepsis crystalloid'}).json()
    assert d['status']=='ok' and len(d['results'])==3
    assert all(x['chunk_id'].startswith('SSC2021-') for x in d['results'])

def test_write_dedup_validation_and_actor_spoof(client):
    login(client)
    body={'patient_id':'P002','request_id':'pytest-write','fields':[{'code':'lactate','name':'伪造名称','value':3.8,'unit':'mmol/L'}],'actor':{'actor_id':'root','role':'clinician'}}
    a=client.post('/api/observations/manual',json=body);assert a.status_code==200,a.text;assert a.json()['inserted']==1
    b=client.post('/api/observations/manual',json=body);assert b.json()['inserted']==0
    db=SessionLocal();o=db.query(Observation).filter_by(dedup_key='manual:pytest-write:lactate').one();assert o.name=='乳酸';db.close()
    bad={'patient_id':'P002','request_id':'pytest-bad','fields':[{'code':'lactate','value':3.8,'unit':'mg/dL'}]}
    assert client.post('/api/observations/manual',json=bad).status_code==422

def test_engineer_cannot_write_or_invoke_commit(client):
    login(client,'engineer')
    body={'patient_id':'P002','request_id':'pytest-role','fields':[{'code':'map','value':70,'unit':'mmHg'}]}
    assert client.post('/api/observations/manual',json=body).status_code==403
    assert client.post('/api/mcp/call',json={'tool':'review.commit','args':{}}).status_code==403
    assert client.post('/api/alerts/1/acknowledge',json={'note':'越权'}).status_code==403
    login(client)

def test_simulation_becomes_outdated(client):
    login(client)
    run=client.post('/api/simulations',json={'patient_id':'P003'}).json();assert len(run['branches'])==3;assert not run['is_outdated']
    assert '28' not in str(run) and '生存概率' not in str(run)
    body={'patient_id':'P003','request_id':'pytest-new-revision','fields':[{'code':'map','value':61,'unit':'mmHg'}]}
    assert client.post('/api/observations/manual',json=body).json()['inserted']==1
    old=client.get('/api/simulations/'+run['id']).json();assert old['is_outdated'];assert old['current_observation_revision']>old['input_observation_revision']

def upload_png(client):
    buf=io.BytesIO();Image.new('RGB',(32,32),(230,230,230)).save(buf,'PNG')
    r=client.post('/api/documents',data={'patient_id':'P004','kind':'lab_report'},files={'file':('report.png',buf.getvalue(),'image/png')});assert r.status_code==200,r.text;return r.json()['id']

def test_vision_confirm_idempotent_and_original_retained(client):
    login(client);did=upload_png(client);vid=uuid.uuid4().hex
    db=SessionLocal();db.add(VisionExtraction(id=vid,document_id=did,patient_id='P004',status='pending_review',raw_json='{"fields":[]}',model_id='pytest'));db.commit();doc=db.get(Document,did);original=Path(doc.original_path);db.close()
    body={'fields':[{'code':'lactate','value':2.9,'unit':'mmol/L'}],'reason':'原图核对','actor':{'actor_id':'root','role':'clinician'}}
    a=client.post(f'/api/vision/{vid}/confirm',json=body);assert a.status_code==200,a.text;assert a.json()['inserted']==1
    b=client.post(f'/api/vision/{vid}/confirm',json=body);assert b.json()['idempotent'];assert original.exists()
    db=SessionLocal();assert db.query(Observation).filter_by(dedup_key=f'vision:{vid}:lactate').count()==1;db.close()

def test_failed_vision_keeps_file_and_allows_reject(client):
    login(client);did=upload_png(client)
    r=client.post('/api/vision/extract',json={'document_id':did});assert r.status_code==200;v=r.json();assert v['status']=='failed'
    db=SessionLocal();path=Path(db.get(Document,did).original_path);db.close();assert path.exists()
    db=SessionLocal();vdb=db.get(VisionExtraction,v['id']);vdb.status='pending_review';db.commit();db.close()
    assert client.post(f"/api/vision/{v['id']}/reject",json={'reason':'字段不清晰'}).status_code==200;assert path.exists()

def test_alert_and_quality(client):
    login(client)
    alerts=client.get('/api/alerts',params={'status':'未处理'}).json()['items'];aid=alerts[0]['id']
    assert client.post(f'/api/alerts/{aid}/acknowledge',json={'note':'已床旁评估'}).status_code==200
    q=client.get('/api/quality',params={'patient_id':'P003'}).json();assert 'current_revision' in q
    audit=client.get('/api/audit',params={'patient_id':'P003'}).json();assert audit['total']>0

def test_timeout_does_not_restart_process():
    class FakeSession:
        async def call_tool(self,*args): await asyncio.sleep(.05)
    async def run():
        p=MCPProcess('patient');p.session=FakeSession();p.state='ready';original=p.session
        with pytest.raises(TimeoutError): await p.call('patient.get',{},.001)
        assert p.session is original and p.restarts==0
    asyncio.run(run())

def test_vision_document_type_union_is_normalized():
    from app.schemas import normalize_vision_payload
    p=normalize_vision_payload({'document_type':'lab_report|monitor|pmut','fields':[]},'monitor')
    assert p.document_type=='monitor' and p.warnings

def test_vision_model_json_parser():
    from app.lm import parse_model_json
    expected={'document_type':'lab_report','fields':[]}
    assert parse_model_json('```json\n{"document_type":"lab_report","fields":[]}\n```')==expected
    assert parse_model_json('提取结果如下：{"document_type":"lab_report","fields":[]}')==expected

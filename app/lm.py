import asyncio, base64, json
from pathlib import Path
import httpx
from .config import settings

async def health():
    try:
        async with httpx.AsyncClient(timeout=2.5) as c:
            r=await c.get(settings.lm_studio_base_url.rstrip('/')+'/models'); r.raise_for_status()
            ids=[m.get('id') for m in r.json().get('data',[])]
            return {'online':True,'models':ids,'text_ready':settings.text_model in ids,'vision_ready':settings.vision_model in ids}
    except Exception as e: return {'online':False,'models':[],'text_ready':False,'vision_ready':False,'error':str(e)[:240]}
async def chat(prompt):
    messages=[{'role':'system','content':'你是ICU临床文书助手。仅根据输入结构化事实写交接班摘要，不补充未提供的数值、诊断或医嘱。'},{'role':'user','content':prompt}]
    errors=[]
    async with httpx.AsyncClient(timeout=45) as c:
        for model in [settings.text_model,settings.text_fallback_model]:
            try:
                r=await c.post(settings.lm_studio_base_url.rstrip()+'/chat/completions',json={'model':model,'messages':messages,'temperature':0.1}); r.raise_for_status()
                return r.json()['choices'][0]['message']['content'],model
            except Exception as e: errors.append(str(e)[:160])
    raise RuntimeError('；'.join(errors))
def parse_model_json(text):
    """Accept pure JSON, Markdown fences, or short prose around one JSON object."""
    if not isinstance(text,str): raise ValueError('视觉模型未返回文本JSON')
    start=text.find('{')
    if start<0: raise ValueError('视觉模型返回内容中没有JSON对象')
    try: return json.JSONDecoder().raw_decode(text[start:].lstrip())[0]
    except json.JSONDecodeError as e: raise ValueError(f'视觉模型JSON格式不完整：{e.msg}') from e
_vision_lock=asyncio.Lock()
async def vision_extract(path,document_type='lab_report'):
    if document_type not in ['lab_report','monitor','pmut']: document_type='lab_report'
    prompt=f'''只提取图片中明确可见的临床测量字段，不诊断、不建议、不猜测。
仅输出一个完整JSON对象，不要输出Markdown、解释文字或候选值。
document_type必须且只能填写"{document_type}"，不要输出竖线或lab_report|monitor|pmut。
JSON结构：{{"document_type":"{document_type}","fields":[{{"code":"lactate","name":"乳酸","value":3.2,"unit":"mmol/L","observed_at":null,"raw_text":"原文","quality_flags":[]}}],"unreadable_fields":[],"warnings":[]}}。
每个field的code只能单选：map,lactate,urine_output,hr,spo2,rr,ne_dose,urine_na,urine_k,urine_creatinine,urine_ph,psv,edv,vti,mic。
value必须是数值或null，unit必须与图片一致，看不到的字段不要编造。'''
    async with _vision_lock:
        data=base64.b64encode(Path(path).read_bytes()).decode()
        payload={'model':settings.vision_model,'temperature':0,'messages':[{'role':'user','content':[{'type':'text','text':prompt},{'type':'image_url','image_url':{'url':'data:image/png;base64,'+data}}]}]}
        async with httpx.AsyncClient(timeout=settings.mcp_vision_timeout) as c:
            r=await c.post(settings.lm_studio_base_url.rstrip()+'/chat/completions',json=payload); r.raise_for_status()
            content=r.json()['choices'][0]['message']['content']
            if isinstance(content,list): content=''.join(x.get('text','') for x in content if isinstance(x,dict))
            return parse_model_json(content)

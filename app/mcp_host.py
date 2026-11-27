import asyncio, json, logging, os, sys, time, uuid
from contextlib import AsyncExitStack
from pathlib import Path
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from .config import settings, ROOT
from .db import SessionLocal
from .models import MCPToolCall

log=logging.getLogger('mcp.host')
TOOL_SERVER={'patient.get':'patient','patient.timeline':'patient','observation.query':'patient','simulation.run':'simulation','guideline.search':'rag','vision.extract':'vision','safety.validate':'safety','review.commit':'review','audit.query':'audit'}
class MCPProcess:
    def __init__(self,name): self.name=name; self.stack=None; self.session=None; self.err=None; self.lock=asyncio.Lock(); self.restarts=0; self.state='stopped'
    async def start(self):
        if self.session: return
        self.err=open(Path(settings.log_dir)/f'mcp_{self.name}.log','a',encoding='utf-8')
        params=StdioServerParameters(command=sys.executable,args=['-m','app.mcp_server',self.name],cwd=str(ROOT),env=os.environ.copy())
        self.stack=AsyncExitStack(); read,write=await self.stack.enter_async_context(stdio_client(params,errlog=self.err))
        self.session=await self.stack.enter_async_context(ClientSession(read,write)); await self.session.initialize(); self.state='ready'
    async def close(self):
        self.state='stopped'
        if self.stack: await self.stack.aclose()
        self.stack=None; self.session=None
        if self.err: self.err.close(); self.err=None
    async def restart(self):
        if self.restarts>=settings.mcp_max_restarts: self.state='circuit_open'; raise RuntimeError(f'{self.name} 熔断：重启次数已达上限')
        self.restarts+=1; self.state='restarting'; await self.close(); self.state='restarting'; await asyncio.sleep(min(.2*self.restarts,1)); await self.start()
    async def call(self,tool,args,timeout):
        async with self.lock:
            if self.state=='circuit_open': raise RuntimeError(f'{self.name} 服务熔断')
            try:
                result=await asyncio.wait_for(self.session.call_tool(tool,args),timeout)
                if getattr(result,'isError',False): raise RuntimeError(str(getattr(result,'content','工具调用失败'))[:500])
                structured=getattr(result,'structuredContent',None)
                if structured is not None: return structured
                content=getattr(result,'content',[])
                if content and hasattr(content[0],'text'): return json.loads(content[0].text)
                return {'result':str(result)}
            except asyncio.TimeoutError: raise TimeoutError(f'{tool} 调用超过 {timeout} 秒')
            except (TimeoutError,PermissionError,ValueError,RuntimeError): raise
            except Exception:
                await self.restart(); raise
class MCPHost:
    def __init__(self): self.processes={n:MCPProcess(n) for n in ['patient','simulation','rag','vision','safety','review','audit']}
    async def start(self): await asyncio.gather(*(p.start() for p in self.processes.values()))
    async def close(self): await asyncio.gather(*(p.close() for p in self.processes.values()),return_exceptions=True)
    async def tools(self):
        out=[]
        for name,p in self.processes.items():
            result=await p.session.list_tools()
            out += [{'server':name,'name':t.name,'description':t.description,'input_schema':t.input_schema} for t in result.tools]
        return out
    def health(self): return {n:{'state':p.state,'restarts':p.restarts} for n,p in self.processes.items()}
    def record(self,trace,request,server,tool,actor,patient_id,status,duration,params,result='',error=''):
        db=SessionLocal()
        safe={k:v for k,v in params.items() if k in ['file_id','file_sha256','patient_id','code','query','source','reason','dedup_prefix']}
        db.add(MCPToolCall(trace_id=trace,request_id=request,server=server,tool=tool,actor_id=actor.get('actor_id',''),patient_id=patient_id or '',status=status,duration_ms=duration,params_summary=json.dumps(safe,ensure_ascii=False),result_summary=str(result)[:1000],error=str(error)[:1000],model_id=settings.vision_model if tool=='vision.extract' else ''))
        db.commit(); db.close()
    async def call(self,tool,args,actor=None,patient_id=''):
        if hasattr(actor,'model_dump'): actor=actor.model_dump()
        actor=actor or {'actor_id':'system','role':'engineer'}; server=TOOL_SERVER.get(tool,'unregistered'); trace=uuid.uuid4().hex; request=uuid.uuid4().hex; started=time.monotonic()
        if not server in self.processes:
            self.record(trace,request,server,tool,actor,patient_id,'rejected',0,args,error='未注册工具'); raise ValueError('未注册 MCP 工具')
        timeout=settings.mcp_vision_timeout if tool=='vision.extract' else settings.mcp_default_timeout
        try:
            result=await self.processes[server].call(tool,args,timeout); status='success' if result.get('ok',True) else 'failed'; self.record(trace,request,server,tool,actor,patient_id,status,int((time.monotonic()-started)*1000),args,result,result.get('error','')); return result
        except Exception as e:
            self.record(trace,request,server,tool,actor,patient_id,'timeout' if isinstance(e,TimeoutError) else 'failed',int((time.monotonic()-started)*1000),args,error=e); raise
host=MCPHost()

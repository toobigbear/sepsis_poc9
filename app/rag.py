import json, os, re
from pathlib import Path
import numpy as np, httpx
from .vector_backend import faiss, BACKEND
from .config import settings
from .db import SessionLocal
from .models import EvidenceChunk, EvidenceDocument

def meta_path(): return settings.faiss_index_path+'.json'
def hash_vectors(texts,dim=384):
    out=np.zeros((len(texts),dim),dtype='float32')
    for i,text in enumerate(texts):
        tokens=re.findall(r'[A-Za-z0-9]+|[\u4e00-\u9fff]',text.lower())
        for token in tokens:
            out[i,hash(token)%dim]+=1
        faiss.normalize_L2(out[i:i+1])
    return out
async def vectors(texts,method):
    if method=='local':
        async with httpx.AsyncClient(timeout=20) as c:
            r=await c.post(settings.lm_studio_base_url.rstrip()+'/embeddings',json={'model':settings.embedding_model,'input':texts}); r.raise_for_status()
            return np.array([x['embedding'] for x in r.json()['data']],dtype='float32')
    return hash_vectors(texts)
async def rebuild():
    db=SessionLocal(); chunks=db.query(EvidenceChunk).order_by(EvidenceChunk.vector_position).all(); db.close()
    if not chunks: raise RuntimeError('证据分块为空')
    texts=[c.text for c in chunks]; method='hash' if settings.rag_embed_mode=='hash' else 'local'
    try: vecs=await vectors(texts,method)
    except Exception:
        if settings.rag_embed_mode=='local': raise
        method='hash'; vecs=await vectors(texts,method)
    faiss.normalize_L2(vecs); index=faiss.IndexFlatIP(vecs.shape[1]); index.add(vecs)
    target=Path(settings.faiss_index_path); target.parent.mkdir(parents=True,exist_ok=True)
    tmp=str(target)+'.tmp'; faiss.write_index(index,tmp); os.replace(tmp,target)
    mt=meta_path()+'.tmp'; Path(mt).write_text(json.dumps({'method':method,'ids':[c.id for c in chunks]},ensure_ascii=False),encoding='utf-8'); os.replace(mt,meta_path())
    return {'status':'ready','method':method,'count':len(chunks)}
async def search(query,limit=4):
    if not Path(settings.faiss_index_path).exists() or not Path(meta_path()).exists(): await rebuild()
    try:
        meta=json.loads(Path(meta_path()).read_text(encoding='utf-8')); index=faiss.read_index(settings.faiss_index_path)
        q=await vectors([query],meta['method']); faiss.normalize_L2(q); scores,pos=index.search(q,min(limit,index.ntotal))
        db=SessionLocal(); results=[]
        for score,p in zip(scores[0],pos[0]):
            if p<0 or p>=len(meta['ids']): continue
            chunk=db.get(EvidenceChunk,meta['ids'][p]); doc=db.get(EvidenceDocument,chunk.document_id)
            results.append({'chunk_id':chunk.id,'text':chunk.text,'section':chunk.section,'locator':chunk.locator,'title':doc.title,'version':doc.version,'source':doc.source,'score':round(float(score),4)})
        db.close(); return {'status':'ok','results':results,'embedding_method':meta['method']}
    except Exception as e: return {'status':'unavailable','results':[],'error':str(e)[:240]}

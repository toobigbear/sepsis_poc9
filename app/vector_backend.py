"""FAISS backend with a small NumPy fallback for platforms without FAISS wheels."""
try:
    import faiss
    BACKEND='faiss'
except ImportError:
    import numpy as np
    BACKEND='numpy'
    def normalize_L2(x):
        norms=np.linalg.norm(x,axis=1,keepdims=True); norms[norms==0]=1; x/=norms
    class IndexFlatIP:
        def __init__(self,dim): self.dim=dim; self.vectors=np.empty((0,dim),dtype='float32')
        @property
        def ntotal(self): return len(self.vectors)
        def add(self,x): self.vectors=np.vstack([self.vectors,x.astype('float32')])
        def search(self,q,k):
            scores=q@self.vectors.T
            pos=np.argsort(-scores,axis=1)[:,:k]
            return np.take_along_axis(scores,pos,axis=1),pos
    def write_index(index,path):
        with open(path,'wb') as f: np.save(f,index.vectors,allow_pickle=False)
    def read_index(path):
        vectors=np.load(path,allow_pickle=False).astype('float32'); index=IndexFlatIP(vectors.shape[1]); index.add(vectors); return index
    class _FaissCompat:
        IndexFlatIP=IndexFlatIP
        normalize_L2=staticmethod(normalize_L2)
        write_index=staticmethod(write_index)
        read_index=staticmethod(read_index)
    faiss=_FaissCompat()

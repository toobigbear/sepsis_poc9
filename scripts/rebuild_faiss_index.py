import asyncio, sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from app.rag import rebuild
from app.vector_backend import BACKEND

if __name__=='__main__':
    print(asyncio.run(rebuild()))
    print('向量后端：'+BACKEND)

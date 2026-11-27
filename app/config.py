from pathlib import Path
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / '.env', extra='ignore')
    lm_studio_base_url: str = 'http://127.0.0.1:1234/v1'
    text_model: str = 'qwen3-8b'
    vision_model: str = 'qwen2.5-vl-7b-instruct'
    text_fallback_model: str = 'qwen2.5-3b-instruct'
    embedding_model: str = 'nomic-ai/text-embedding-nomic-embed-text-v1.5'
    database_url: str = f'sqlite:///{ROOT / "data" / "sepsis.db"}'
    mcp_default_timeout: float = 15.0
    mcp_vision_timeout: float = 180.0
    mcp_max_restarts: int = 2
    image_storage_dir: str = str(ROOT / 'data' / 'uploads')
    log_dir: str = str(ROOT / 'data' / 'logs')
    session_secret: str = 'change-this-local-secret'
    session_hours: int = 12
    faiss_index_path: str = str(ROOT / 'data' / 'vector' / 'guideline.index')
    rag_embed_mode: str = 'auto'

settings = Settings()
for path in [settings.image_storage_dir, settings.log_dir, str(ROOT / 'data' / 'vector')]:
    Path(path).mkdir(parents=True, exist_ok=True)

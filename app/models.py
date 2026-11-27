from datetime import datetime, timezone
from sqlalchemy import String, Integer, Float, DateTime, Text, ForeignKey, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base

def now(): return datetime.now(timezone.utc).isoformat(timespec='seconds')
class Stamp:
    created_at: Mapped[str] = mapped_column(String, default=now)

class User(Stamp, Base):
    __tablename__='users'
    id: Mapped[str]=mapped_column(String,primary_key=True); name: Mapped[str]=mapped_column(String); role: Mapped[str]=mapped_column(String); password_hash: Mapped[str]=mapped_column(String)
class Session(Stamp, Base):
    __tablename__='sessions'
    id: Mapped[str]=mapped_column(String,primary_key=True); user_id: Mapped[str]=mapped_column(ForeignKey('users.id')); expires_at: Mapped[str]=mapped_column(String)
class Patient(Stamp, Base):
    __tablename__='patients'
    id: Mapped[str]=mapped_column(String,primary_key=True); bed: Mapped[str]=mapped_column(String,unique=True); name: Mapped[str]=mapped_column(String); age: Mapped[int]=mapped_column(Integer); sex: Mapped[str]=mapped_column(String); diagnosis: Mapped[str]=mapped_column(String); sofa: Mapped[int]=mapped_column(Integer); risk_score: Mapped[float]=mapped_column(Float,default=0); risk_level: Mapped[str]=mapped_column(String,default='低'); observation_revision: Mapped[int]=mapped_column(Integer,default=1)
class Encounter(Stamp, Base):
    __tablename__='encounters'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),unique=True); admitted_at: Mapped[str]=mapped_column(String); infection_source: Mapped[str]=mapped_column(String); comorbidities: Mapped[str]=mapped_column(String)
class Observation(Stamp, Base):
    __tablename__='observations'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); code: Mapped[str]=mapped_column(String,index=True); name: Mapped[str]=mapped_column(String); value: Mapped[float]=mapped_column(Float); unit: Mapped[str]=mapped_column(String); observed_at: Mapped[str]=mapped_column(String); source: Mapped[str]=mapped_column(String); review_status: Mapped[str]=mapped_column(String,default='已复核'); revision: Mapped[int]=mapped_column(Integer); dedup_key: Mapped[str]=mapped_column(String,unique=True)
class ObservationRevision(Stamp, Base):
    __tablename__='observation_revisions'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id')); revision: Mapped[int]=mapped_column(Integer); reason: Mapped[str]=mapped_column(String); actor_id: Mapped[str]=mapped_column(String)
class Alert(Stamp, Base):
    __tablename__='alerts'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); severity: Mapped[str]=mapped_column(String); title: Mapped[str]=mapped_column(String); reason: Mapped[str]=mapped_column(String); status: Mapped[str]=mapped_column(String,default='未处理',index=True)
class AlertEvent(Stamp, Base):
    __tablename__='alert_events'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); alert_id: Mapped[int]=mapped_column(ForeignKey('alerts.id')); action: Mapped[str]=mapped_column(String); note: Mapped[str]=mapped_column(Text,default=''); actor_id: Mapped[str]=mapped_column(String)
class Document(Stamp, Base):
    __tablename__='documents'
    id: Mapped[str]=mapped_column(String,primary_key=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); kind: Mapped[str]=mapped_column(String); original_path: Mapped[str]=mapped_column(String); normalized_path: Mapped[str]=mapped_column(String); file_sha256: Mapped[str]=mapped_column(String); normalized_sha256: Mapped[str]=mapped_column(String); file_size: Mapped[int]=mapped_column(Integer); mime: Mapped[str]=mapped_column(String); status: Mapped[str]=mapped_column(String,default='已上传'); uploaded_by: Mapped[str]=mapped_column(String)
class VisionExtraction(Stamp, Base):
    __tablename__='vision_extractions'
    id: Mapped[str]=mapped_column(String,primary_key=True); document_id: Mapped[str]=mapped_column(ForeignKey('documents.id')); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); status: Mapped[str]=mapped_column(String,default='pending_review',index=True); raw_json: Mapped[str]=mapped_column(Text,default='{}'); reviewed_json: Mapped[str]=mapped_column(Text,default=''); validation_json: Mapped[str]=mapped_column(Text,default='{}'); model_id: Mapped[str]=mapped_column(String,default=''); error: Mapped[str]=mapped_column(Text,default='')
class ObservationReview(Stamp, Base):
    __tablename__='observation_reviews'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); extraction_id: Mapped[str]=mapped_column(ForeignKey('vision_extractions.id')); action: Mapped[str]=mapped_column(String); actor_id: Mapped[str]=mapped_column(String); reason: Mapped[str]=mapped_column(Text,default='')
class SimulationRun(Stamp, Base):
    __tablename__='simulation_runs'
    id: Mapped[str]=mapped_column(String,primary_key=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); input_observation_revision: Mapped[int]=mapped_column(Integer); input_snapshot: Mapped[str]=mapped_column(Text); status: Mapped[str]=mapped_column(String,default='已完成')
class SimulationBranch(Stamp, Base):
    __tablename__='simulation_branches'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); run_id: Mapped[str]=mapped_column(ForeignKey('simulation_runs.id')); name: Mapped[str]=mapped_column(String); trajectory_json: Mapped[str]=mapped_column(Text); assumptions: Mapped[str]=mapped_column(Text); uncertainty: Mapped[str]=mapped_column(String); risks: Mapped[str]=mapped_column(Text)
class EvidenceDocument(Stamp, Base):
    __tablename__='evidence_documents'
    id: Mapped[str]=mapped_column(String,primary_key=True); title: Mapped[str]=mapped_column(String); version: Mapped[str]=mapped_column(String); source: Mapped[str]=mapped_column(String); file_sha256: Mapped[str]=mapped_column(String)
class EvidenceChunk(Stamp, Base):
    __tablename__='evidence_chunks'
    id: Mapped[str]=mapped_column(String,primary_key=True); document_id: Mapped[str]=mapped_column(ForeignKey('evidence_documents.id')); section: Mapped[str]=mapped_column(String); locator: Mapped[str]=mapped_column(String); text: Mapped[str]=mapped_column(Text); vector_position: Mapped[int]=mapped_column(Integer,default=0)
class EvidenceLink(Stamp, Base):
    __tablename__='evidence_links'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); simulation_id: Mapped[str]=mapped_column(String,nullable=True); brief_id: Mapped[int]=mapped_column(Integer,nullable=True); chunk_id: Mapped[str]=mapped_column(ForeignKey('evidence_chunks.id'))
class ClinicalBrief(Stamp, Base):
    __tablename__='clinical_briefs'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); patient_id: Mapped[str]=mapped_column(ForeignKey('patients.id'),index=True); content: Mapped[str]=mapped_column(Text); generation_mode: Mapped[str]=mapped_column(String); updated_by: Mapped[str]=mapped_column(String); updated_at: Mapped[str]=mapped_column(String,default=now)
class MCPToolCall(Stamp, Base):
    __tablename__='mcp_tool_calls'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); trace_id: Mapped[str]=mapped_column(String,index=True); request_id: Mapped[str]=mapped_column(String); server: Mapped[str]=mapped_column(String); tool: Mapped[str]=mapped_column(String); actor_id: Mapped[str]=mapped_column(String,default=''); patient_id: Mapped[str]=mapped_column(String,default=''); status: Mapped[str]=mapped_column(String); duration_ms: Mapped[int]=mapped_column(Integer); params_summary: Mapped[str]=mapped_column(Text,default=''); result_summary: Mapped[str]=mapped_column(Text,default=''); error: Mapped[str]=mapped_column(Text,default=''); model_id: Mapped[str]=mapped_column(String,default='')
class AuditEvent(Stamp, Base):
    __tablename__='audit_events'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); trace_id: Mapped[str]=mapped_column(String); actor_id: Mapped[str]=mapped_column(String); action: Mapped[str]=mapped_column(String); patient_id: Mapped[str]=mapped_column(String,default=''); detail_json: Mapped[str]=mapped_column(Text,default='{}')
class PolicyVersion(Stamp, Base):
    __tablename__='policy_versions'
    id: Mapped[int]=mapped_column(Integer,primary_key=True,autoincrement=True); name: Mapped[str]=mapped_column(String); version: Mapped[str]=mapped_column(String,unique=True); status: Mapped[str]=mapped_column(String); metrics_json: Mapped[str]=mapped_column(Text,default='{}')

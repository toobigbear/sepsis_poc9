from typing import Literal
from pydantic import BaseModel, Field, ConfigDict

class LoginIn(BaseModel):
    username: str; password: str
class Actor(BaseModel):
    actor_id: str; role: Literal['clinician','engineer']
class FieldIn(BaseModel):
    model_config=ConfigDict(extra='forbid')
    code: str; name: str=''; value: float|None=None; unit: str=''; observed_at: str|None=None; raw_text: str=''; quality_flags: list[str]=Field(default_factory=list)
class VisionPayload(BaseModel):
    model_config=ConfigDict(extra='ignore')
    document_type: Literal['lab_report','monitor','pmut']='lab_report'; fields: list[FieldIn]=Field(default_factory=list); unreadable_fields: list[str]=Field(default_factory=list); warnings: list[str]=Field(default_factory=list)
def normalize_vision_payload(payload,expected_type='lab_report'):
    if not isinstance(payload,dict): raise ValueError('视觉模型返回值不是JSON对象')
    data=dict(payload); supplied=str(data.get('document_type','')).strip().lower()
    aliases={'检验报告':'lab_report','化验单':'lab_report','lab':'lab_report','监护截屏':'monitor','监护仪':'monitor','pmut影像':'pmut','超声':'pmut'}
    supplied=aliases.get(supplied,supplied); warnings=list(data.get('warnings') or [])
    if expected_type not in ['lab_report','monitor','pmut']: expected_type='lab_report'
    if supplied!=expected_type:
        if supplied: warnings.append(f'资料类型返回值“{supplied}”不规范或与上传类型不一致，已按上传类型校正')
        data['document_type']=expected_type
    data['warnings']=warnings
    return VisionPayload.model_validate(data)
class ConfirmIn(BaseModel):
    model_config=ConfigDict(extra='ignore')
    fields: list[FieldIn]; reason: str=''
class RejectIn(BaseModel):
    model_config=ConfigDict(extra='ignore')
    reason: str=''
class ManualIn(BaseModel):
    model_config=ConfigDict(extra='ignore')
    patient_id: str; fields: list[FieldIn]; request_id: str
class AdapterIn(BaseModel):
    patient_id: str; fields: list[FieldIn]; request_id: str
class NoteIn(BaseModel):
    model_config=ConfigDict(extra='ignore')
    note: str=''
class BriefIn(BaseModel):
    patient_id: str
class BriefEdit(BaseModel):
    content: str=Field(min_length=1,max_length=20000)
class ExtractIn(BaseModel):
    document_id: str

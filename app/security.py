import hashlib, hmac, secrets
from datetime import datetime, timedelta, timezone
from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session
from .config import settings
from .db import get_db
from .models import User, Session as UserSession
from .schemas import Actor
COOKIE='sepsis_session'

def password_hash(password: str, salt: str|None=None):
    salt=salt or secrets.token_hex(8)
    return salt+'$'+hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),120_000).hex()
def verify(password: str, stored: str):
    salt,_=stored.split('$',1)
    return hmac.compare_digest(password_hash(password,salt),stored)
def actor(user: User): return Actor(actor_id=user.id,role=user.role)
def current_user(request: Request, db: Session=Depends(get_db)):
    token=request.cookies.get(COOKIE)
    if not token: raise HTTPException(401,'未登录')
    sess=db.get(UserSession,token)
    if not sess or sess.expires_at < datetime.now(timezone.utc).isoformat(): raise HTTPException(401,'会话已失效')
    user=db.get(User,sess.user_id)
    if not user: raise HTTPException(401,'用户不存在')
    return user
def optional_user(request: Request, db: Session=Depends(get_db)):
    token=request.cookies.get(COOKIE)
    if not token: return None
    sess=db.get(UserSession,token)
    if not sess or sess.expires_at < datetime.now(timezone.utc).isoformat(): return None
    return db.get(User,sess.user_id)
def clinician(user: User=Depends(current_user)):
    if user.role!='clinician': raise HTTPException(403,'当前角色无临床写入权限')
    return user
def login(response: Response, user: User, db: Session):
    token=secrets.token_urlsafe(32)
    expires=(datetime.now(timezone.utc)+timedelta(hours=settings.session_hours)).isoformat()
    db.add(UserSession(id=token,user_id=user.id,expires_at=expires)); db.commit()
    response.set_cookie(COOKIE,token,httponly=True,samesite='lax',secure=False,max_age=settings.session_hours*3600)
    return actor(user)
def logout(response: Response, request: Request, db: Session):
    token=request.cookies.get(COOKIE)
    if token: db.query(UserSession).filter_by(id=token).delete(); db.commit()
    response.delete_cookie(COOKIE)

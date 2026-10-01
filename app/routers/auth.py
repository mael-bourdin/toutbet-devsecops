from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.audit import audit
from app.config import get_settings
from app.db import get_db
from app.models import User
from app.schemas import LoginIn, RegisterIn, TokenOut, UserOut
from app.security import create_access_token, get_current_user, hash_password, limiter, verify_password

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=UserOut, status_code=201)
def register(body: RegisterIn, request: Request, db: Session = Depends(get_db)):
    limiter.check(f"register:{request.client.host}", get_settings().login_rate_limit)
    exists = db.scalar(select(User).where(or_(User.username == body.username, User.email == body.email)))
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "Inscription impossible")
    user = User(username=body.username, email=body.email, password_hash=hash_password(body.password))
    db.add(user)
    db.flush()
    audit(db, user.id, "user.registered")
    db.commit()
    return user


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, request: Request, db: Session = Depends(get_db)):
    s = get_settings()
    limiter.check(f"login:{request.client.host}:{body.username}", s.login_rate_limit)
    user = db.scalar(select(User).where(User.username == body.username))
    if not verify_password(user.password_hash if user else None, body.password):
        audit(db, None, "auth.failed", username=body.username, ip=request.client.host)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Identifiants invalides")  # message générique
    audit(db, user.id, "auth.success", ip=request.client.host)
    db.commit()
    return TokenOut(access_token=create_access_token(user), expires_in=s.jwt_ttl_seconds)


@router.get("/me", response_model=UserOut)
def me(user: User = Depends(get_current_user)):
    return user

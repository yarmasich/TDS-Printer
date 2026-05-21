from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import Session, select

from ..db import get_session
from ..models import AuthName

router = APIRouter(prefix="/api/auth-names", tags=["auth-names"])


@router.get("", response_model=List[AuthName])
def list_auth(session: Session = Depends(get_session)) -> List[AuthName]:
    return session.exec(select(AuthName).order_by(AuthName.name)).all()


@router.post("", response_model=AuthName)
def create_auth(a: AuthName, session: Session = Depends(get_session)) -> AuthName:
    session.add(a)
    session.commit()
    session.refresh(a)
    return a


@router.delete("/{auth_id}")
def delete_auth(auth_id: int, session: Session = Depends(get_session)) -> dict:
    a = session.get(AuthName, auth_id)
    if not a:
        raise HTTPException(404, "Auth name not found")
    session.delete(a)
    session.commit()
    return {"deleted": auth_id}

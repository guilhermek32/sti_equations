from __future__ import annotations

import uuid

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyBaseAccessTokenTableUUID
from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "user"
    __table_args__ = {"schema": "identity"}

    role: Mapped[str] = mapped_column(String(16), default="student", nullable=False)


UserId = uuid.UUID


class AccessToken(SQLAlchemyBaseAccessTokenTableUUID, Base):
    __tablename__ = "access_token"
    __table_args__ = {"schema": "identity"}

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("identity.user.id", ondelete="cascade"), nullable=False
    )

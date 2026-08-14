from __future__ import annotations

import uuid

from fastapi_users.db import SQLAlchemyBaseUserTableUUID
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from ..database import Base


class User(SQLAlchemyBaseUserTableUUID, Base):
    __tablename__ = "user"
    __table_args__ = {"schema": "identity"}

    role: Mapped[str] = mapped_column(String(16), default="student", nullable=False)


UserId = uuid.UUID

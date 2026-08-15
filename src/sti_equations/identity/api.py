from __future__ import annotations

import uuid
from collections.abc import AsyncGenerator, Callable

from fastapi import Depends, HTTPException, status
from fastapi_users import BaseUserManager, FastAPIUsers, UUIDIDMixin, exceptions, schemas
from fastapi_users.authentication import AuthenticationBackend, CookieTransport
from fastapi_users.authentication.strategy.db import DatabaseStrategy
from fastapi_users.db import SQLAlchemyUserDatabase
from fastapi_users_db_sqlalchemy.access_token import SQLAlchemyAccessTokenDatabase
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import get_settings
from ..database import get_session
from .models import AccessToken, User


class UserRead(schemas.BaseUser[uuid.UUID]):
    role: str


class UserCreate(schemas.BaseUserCreate):
    """Public registration never accepts a privileged role."""


class UserUpdate(schemas.BaseUserUpdate):
    role: str | None = None


class Actor(BaseModel):
    id: uuid.UUID
    email: str
    role: str


async def get_user_database(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SQLAlchemyUserDatabase]:
    yield SQLAlchemyUserDatabase(session, User)


class UserManager(UUIDIDMixin, BaseUserManager[User, uuid.UUID]):
    reset_password_token_secret = get_settings().auth_secret
    verification_token_secret = get_settings().auth_secret

    async def validate_password(self, password: str, user: UserCreate | User) -> None:
        if len(password) < 8:
            raise exceptions.InvalidPasswordException(
                reason="Password must contain at least 8 characters"
            )


async def get_user_manager(
    database: SQLAlchemyUserDatabase = Depends(get_user_database),
) -> AsyncGenerator[UserManager]:
    yield UserManager(database)


cookie_transport = CookieTransport(
    cookie_name="sti_session",
    cookie_max_age=3600,
    cookie_secure=get_settings().cookie_secure,
    cookie_httponly=True,
    cookie_samesite="lax",
)


async def get_access_token_database(
    session: AsyncSession = Depends(get_session),
) -> AsyncGenerator[SQLAlchemyAccessTokenDatabase]:
    yield SQLAlchemyAccessTokenDatabase(session, AccessToken)


def get_database_strategy(
    database: SQLAlchemyAccessTokenDatabase = Depends(get_access_token_database),
) -> DatabaseStrategy:
    return DatabaseStrategy(database, lifetime_seconds=3600)


auth_backend = AuthenticationBackend(
    name="cookie",
    transport=cookie_transport,
    get_strategy=get_database_strategy,
)
users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])
current_user = users.current_user(active=True)


def require_role(role: str) -> Callable:
    async def dependency(user: User = Depends(current_user)) -> Actor:
        if user.role != role:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Insufficient role")
        return Actor(id=user.id, email=user.email, role=user.role)

    return dependency


async def current_actor(user: User = Depends(current_user)) -> Actor:
    return Actor(id=user.id, email=user.email, role=user.role)


async def actor_by_id(session: AsyncSession, user_id: uuid.UUID) -> Actor | None:
    user = await session.get(User, user_id)
    if user is None:
        return None
    return Actor(id=user.id, email=user.email, role=user.role)

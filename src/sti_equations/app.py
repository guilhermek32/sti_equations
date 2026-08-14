from __future__ import annotations

import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy import func, select

from .database import async_session_factory, create_database
from .identity.api import UserCreate, UserRead, auth_backend, users
from .learning.api import router as learning_router
from .learning.models import Problem
from .learning.seed import PROBLEMS


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    await create_database()
    async with async_session_factory() as session:
        if not await session.scalar(select(func.count()).select_from(Problem)):
            session.add_all(
                [
                    Problem(
                        equation=equation, variable=variable, difficulty=difficulty, skills=skills
                    )
                    for equation, variable, difficulty, skills in PROBLEMS
                ]
            )
            await session.commit()
    yield


app = FastAPI(title="STI Equations", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
    request.state.request_id = request_id
    response = await call_next(request)
    response.headers["X-Request-ID"] = request_id
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(
        status_code=422,
        content={
            "code": "validation_error",
            "message": "Request validation failed",
            "request_id": request.state.request_id,
            "details": exc.errors(),
        },
    )


app.include_router(
    users.get_auth_router(auth_backend),
    prefix="/v1/auth",
    tags=["auth"],
)
app.include_router(
    users.get_register_router(UserRead, UserCreate),
    prefix="/v1/auth",
    tags=["auth"],
)
app.include_router(learning_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}

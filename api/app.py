'''FastAPI 应用组装入口'''

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from api.routes.auth import router as auth_router
from api.routes.runtime import router as runtime_router
from api.routes.tasks import router as tasks_router
from core.settings import SETTINGS
from repositories.task_repository_contracts import (
    TaskNotFoundError,
    TaskRepositoryUnavailableError,
)
from services.task_lock import TaskLockBusyError, TaskLockUnavailableError
from services.task_queue import TaskQueueUnavailableError
from services.auth_service import validate_auth_configuration


@asynccontextmanager
async def lifespan(_: FastAPI):
    validate_auth_configuration()
    yield


app = FastAPI(
    title="脑肿瘤图像分析 API",
    version="0.11.0",
    lifespan=lifespan,
)


@app.exception_handler(TaskNotFoundError)
async def handle_task_not_found(_, exc: TaskNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(TaskRepositoryUnavailableError)
async def handle_task_repository_unavailable(
    _,
    exc: TaskRepositoryUnavailableError,
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})


@app.exception_handler(TaskLockBusyError)
async def handle_task_lock_busy(_, exc: TaskLockBusyError) -> JSONResponse:
    return JSONResponse(status_code=409, content={"detail": str(exc)})


@app.exception_handler(TaskLockUnavailableError)
@app.exception_handler(TaskQueueUnavailableError)
async def handle_task_service_unavailable(
    _,
    exc: TaskLockUnavailableError | TaskQueueUnavailableError,
) -> JSONResponse:
    return JSONResponse(status_code=503, content={"detail": str(exc)})

app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 由 API 在同一来源托管随附前端
@app.get("/")
async def root():
    return RedirectResponse(url="/web/")


app.mount(
    "/web",
    StaticFiles(directory=SETTINGS.frontend_dir, html=True),
    name="web",
)

app.mount(
    "/login",
    StaticFiles(directory=SETTINGS.frontend_dir, html=True),
    name="login",
)

app.include_router(auth_router)
app.include_router(runtime_router)
app.include_router(tasks_router)

'''FastAPI 应用组装入口'''

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware

from api.routes.auth import router as auth_router
from api.routes.admin import router as admin_router
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
    version="0.12.0",
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


@app.middleware("http")
async def no_cache_frontend_assets(request: Request, call_next):
    '''前端静态资源始终重新校验，避免浏览器缓存旧版页面导致显示异常'''
    response = await call_next(request)
    if request.url.path.startswith(("/web", "/login", "/assets")):
        response.headers["Cache-Control"] = "no-cache"
    return response


app.add_middleware(
    CORSMiddleware,
    allow_origins=SETTINGS.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(GZipMiddleware, minimum_size=1024)

'''重定向至前端页面'''
@app.get("/")
async def root():
    return RedirectResponse(url="/web/")


@app.get("/frontend-config")
async def frontend_config() -> dict[str, int]:
    '''暴露不含敏感信息的前端运行配置'''
    return {
        "report_export_cooldown_seconds": SETTINGS.report_export_cooldown_seconds,
    }


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

app.mount(
    "/assets",
    StaticFiles(directory=SETTINGS.project_root / "assets"),
    name="assets",
)

app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(runtime_router)
app.include_router(tasks_router)

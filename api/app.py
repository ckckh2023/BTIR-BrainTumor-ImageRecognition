'''FastAPI 应用组装入口'''

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from api.routes.runtime import router as runtime_router
from api.routes.tasks import router as tasks_router
from core.settings import SETTINGS
from repositories.task_repository import (
    TaskNotFoundError,
    TaskRepositoryUnavailableError,
)


app = FastAPI(title="脑肿瘤图像分析 API", version="0.1.0")


@app.exception_handler(TaskNotFoundError)
async def handle_task_not_found(_, exc: TaskNotFoundError) -> JSONResponse:
    return JSONResponse(status_code=404, content={"detail": str(exc)})


@app.exception_handler(TaskRepositoryUnavailableError)
async def handle_task_repository_unavailable(
    _,
    exc: TaskRepositoryUnavailableError,
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
app.mount(
    "/web",
    StaticFiles(directory=SETTINGS.frontend_dir, html=True),
    name="web",
)

app.include_router(runtime_router)
app.include_router(tasks_router)

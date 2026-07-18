'''FastAPI 应用组装入口'''

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routes.runtime import router as runtime_router
from api.routes.tasks import router as tasks_router
from core.settings import SETTINGS


app = FastAPI(title="脑肿瘤图像分析 API", version="0.1.0")

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

'''用来创建任务的 API 接口'''


from __future__ import annotations

from pathlib import Path

from fastapi import (
    FastAPI,
    File,
    Form,
    HTTPException,
    UploadFile,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

import json
import shutil

from contracts.task import (
    ClassificationData,
    ClassifyTaskResponse,
    CreateTaskRequest, 
    TaskCreatedResponse,
    TaskStatusResponse,
    TaskInputData,
    SegmentTaskRequest,
    SegmentTaskResponse,
    SegmentationData,
    RunTaskRequest,
    RunTaskResponse,
)
from services.inference_service import classify, segment
from services.task_service import (
    create_task_dir,
    get_task_dir,
    initialize_task,
    load_task_image,
    persist_model_result,
    task_relative_path,
    validate_image_path,
    create_run_dir,
    initialize_uploaded_task
)


# 常用路径
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "output"
PRIVATE_PATH_FIELDS = {
    "frontend_result_path",
    "history_result_path",
    "image_path",
    "mask_path",
    "model_result_path",
    "path",
    "source_path",
    "task_dir",
}


# FastAPI实例
app = FastAPI(
    title="脑肿瘤图像分析 API",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 由 API 在同一来源托管随附前端
# 前端访问地址：http://127.0.0.1:8000/web/
app.mount(
    "/web",
    StaticFiles(directory=PROJECT_ROOT / "frontend", html=True),
    name="web",
)


def sanitize_public_payload(value):
    '''移除历史结果 JSON 中可能存在的本机路径字段。'''
    if isinstance(value, dict):
        return {
            key: sanitize_public_payload(item)
            for key, item in value.items()
            if key not in PRIVATE_PATH_FIELDS
        }
    if isinstance(value, list):
        return [sanitize_public_payload(item) for item in value]
    return value

def require_task_dir(task_id: str) -> Path:
    '''获取指定任务的目录，如果不存在则抛出 HTTP 404 异常'''
    try:
        return get_task_dir(DEFAULT_OUTPUT_DIR, task_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务不存在",
        ) from exc


@app.post(
        "/tasks",
        response_model=TaskCreatedResponse,
        status_code=status.HTTP_201_CREATED,
) # 对app.post装饰器进行修饰
def create_task_from_upload(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
) -> TaskCreatedResponse:
    '''创建一个新的任务'''
    task_dir: Path | None = None

    try:
        task_dir = create_task_dir(DEFAULT_OUTPUT_DIR)
        task_image = initialize_uploaded_task(
            task_dir=task_dir,
            upload=file.file,
            filename=file.filename,
            name=name,
        )
    except ValueError as exc:
        if task_dir is not None:
            shutil.rmtree(task_dir, ignore_errors=True)

        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    
    return TaskCreatedResponse(
        task_id=task_dir.name,
        input_file=task_image.name,
    )
    


@app.post(
    "/tasks/from-path",
    response_model=TaskCreatedResponse,
    status_code=status.HTTP_201_CREATED,
) # 对app.post装饰器进行修饰
def create_task_from_path(request: CreateTaskRequest) -> TaskCreatedResponse:
    '''创建一个新的任务'''
    try:
        source_image = validate_image_path(request.image_path)
        task_dir = create_task_dir(DEFAULT_OUTPUT_DIR)
        task_image = initialize_task(
            task_dir=task_dir,
            source_image=source_image,
            input_mode=request.input_mode,
            name=request.name,
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    
    return TaskCreatedResponse(
        task_id=task_dir.name,
        input_file=task_image.name,
    )


@app.post(
    "/tasks/{task_id}/classify",
    response_model=ClassifyTaskResponse,
) # 对app.post装饰器进行修饰
def classify_task(task_id: str) -> ClassifyTaskResponse:
    '''对指定任务进行分类预测'''
    try:
        task_dir = require_task_dir(task_id)
        image_path = load_task_image(task_dir)

        result = persist_model_result(
            task_dir=task_dir,
            image_path=image_path,
            model_name="classification",
            result=classify(image_path),
        )

        task_record = json.loads(
            (task_dir / "task.json").read_text(encoding="utf-8")
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    
    prediction = result["classification"]
    return ClassifyTaskResponse(
        task_id=task_id,
        status=task_record["status"],
        completed_models=task_record["completed_models"],
        classification=ClassificationData(
            label=prediction["class"],
            confidence=prediction["confidence"],
            probabilities=prediction["probabilities"],
        ),
        frontend_result_file=result["frontend_result_path"],
    )


@app.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
) # 对app.get装饰器进行修饰
def get_task(task_id: str) -> TaskStatusResponse:
    '''获取指定任务的状态'''
    task_dir = require_task_dir(task_id)
    
    task_data = json.loads(
        (task_dir / "task.json").read_text(encoding="utf-8")
    )

    input_data = task_data["input"]
    frontend_path = task_dir / "frontend_result.json"
    frontend_result = (
        json.loads(frontend_path.read_text(encoding="utf-8"))
        if frontend_path.is_file() else None
    )
    if frontend_result is not None:
        frontend_result = sanitize_public_payload(frontend_result)
        frontend_result.setdefault("image_file", Path(input_data["path"]).name)

    return TaskStatusResponse(
        task_id=task_data["task_id"],
        name=task_data["name"],
        status=task_data["status"],
        created_at=task_data["created_at"],
        updated_at=task_data["updated_at"],
        completed_models=task_data["completed_models"],
        input=TaskInputData(
            filename=Path(input_data["path"]).name,
            storage_mode=input_data["storage_mode"],
            size_bytes=input_data["size_bytes"],
            sha256=input_data["sha256"],
        ),
        frontend_result=frontend_result,
    )


@app.get(
    "/tasks/{task_id}/files/{file_path:path}"
) # 对app.get装饰器进行修饰
def get_task_file(task_id: str, file_path: str) -> FileResponse:
    '''安全读取任务目录中的结果文件。'''
    task_dir = require_task_dir(task_id)
    try:
        file = (task_dir / file_path).resolve()
        file.relative_to(task_dir.resolve())
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        ) from exc

    if not file.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        )

    if file.name == "task.json":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="任务文件不存在",
        )

    if file.suffix.lower() == ".json":
        try:
            data = json.loads(file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="任务文件不存在",
            ) from exc
        return JSONResponse(sanitize_public_payload(data))

    return FileResponse(file, filename=file.name)


@app.post(
    "/tasks/{task_id}/segment",
    response_model=SegmentTaskResponse,
) # 对app.post装饰器进行修饰
def segment_task(
    task_id: str,
    request: SegmentTaskRequest,
) -> SegmentTaskResponse:
    '''对指定任务进行分割预测'''

    task_dir = require_task_dir(task_id)

    try:
        image_path = load_task_image(task_dir)

        run_dir = create_run_dir(task_dir, "segmentation")
        result = persist_model_result(
            task_dir=task_dir,
            image_path=image_path,
            model_name="segmentation",
            result=segment(
                image_path=image_path,
                threshold=request.threshold,
                output_dir=run_dir,
            ),
            run_dir=run_dir,
        )

        task_record = json.loads(
            (task_dir / "task.json").read_text(encoding="utf-8")
        )
        mask_file = task_relative_path(task_dir, Path(result["mask_path"]))
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    
    return SegmentTaskResponse(
        task_id=task_id,
        status=task_record["status"],
        completed_models=task_record["completed_models"],
        segmentation=SegmentationData(
            threshold=result["threshold"],
            tumor_pixels=result["tumor_pixels"],
            image_pixels=result["image_pixels"],
            tumor_area_ratio=result["tumor_area_ratio"],
            mask_file=mask_file,
        ),
        frontend_result_file=result["frontend_result_path"],
    )


@app.post(
    "/tasks/{task_id}/run",
    response_model=RunTaskResponse,
) # 对app.post装饰器进行修饰
def run_task(
    task_id: str,
    request: RunTaskRequest | None = None,
) -> RunTaskResponse:
    '''对同一任务依次执行分类与分割'''
    task_dir = require_task_dir(task_id)
    threshold = request.threshold if request is not None else 0.5

    try:
        image_path = load_task_image(task_dir)

        classification_result = persist_model_result(
            task_dir=task_dir,
            image_path=image_path,
            model_name="classification",
            result=classify(image_path),
        )

        run_dir = create_run_dir(task_dir, "segmentation")
        segmentation_result = persist_model_result(
            task_dir=task_dir,
            image_path=image_path,
            model_name="segmentation",
            result=segment(
                image_path=image_path,
                threshold=threshold,
                output_dir=run_dir,
            ),
            run_dir=run_dir,
        )

        task_record = json.loads(
            (task_dir / "task.json").read_text(encoding="utf-8")
        )

        prediction = classification_result["classification"]
        mask_file = task_relative_path(
            task_dir, Path(segmentation_result["mask_path"])
        )

    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    return RunTaskResponse(
        task_id=task_id,
        status=task_record["status"],
        completed_models=task_record["completed_models"],
        classification=ClassificationData(
            label=prediction["class"],
            confidence=prediction["confidence"],
            probabilities=prediction["probabilities"],
        ),
        segmentation=SegmentationData(
            threshold=segmentation_result["threshold"],
            tumor_pixels=segmentation_result["tumor_pixels"],
            image_pixels=segmentation_result["image_pixels"],
            tumor_area_ratio=segmentation_result["tumor_area_ratio"],
            mask_file=mask_file,
        ),
        frontend_result_file=segmentation_result["frontend_result_path"],
    )

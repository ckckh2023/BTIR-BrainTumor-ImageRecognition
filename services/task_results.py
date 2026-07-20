'''模型结果、历史结果和前端结果 JSON 的持久化'''

from __future__ import annotations

from datetime import datetime
import json
from pathlib import Path
from typing import Any

from core.task_definitions import (
    ModelName,
    TaskArtifact,
    TaskStatus,
    model_result_filename,
)
from services.task_files import create_run_dir, task_relative_path, write_json
from services.task_lock import task_write_lock
from services.task_state import mark_task_completed, record_task_run


def persist_model_result(
    task_dir: Path,
    image_path: Path,
    model_name: ModelName | str,
    result: dict[str, Any],
    run_dir: Path | None = None,
) -> dict[str, Any]:
    '''在 Redis 任务锁保护下持久化一项模型结果'''
    with task_write_lock(task_dir.name):
        return _persist_model_result_unlocked(
            task_dir=task_dir,
            image_path=image_path,
            model_name=model_name,
            result=result,
            run_dir=run_dir,
        )


def _persist_model_result_unlocked(
    task_dir: Path,
    image_path: Path,
    model_name: ModelName | str,
    result: dict[str, Any],
    run_dir: Path | None = None,
) -> dict[str, Any]:
    '''将模型结果写入文件，并同步任务运行记录和完成状态'''
    try:
        model = ModelName(model_name)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in ModelName)
        raise ValueError(
            f"不支持的模型名称：{model_name}；仅支持 {allowed}"
        ) from exc

    run_dir = run_dir or create_run_dir(task_dir, model)
    result["run_id"] = run_dir.name
    result["run_directory"] = run_dir.relative_to(task_dir).as_posix()

    stored_result = dict(result)
    stored_result.pop("image_path", None)
    if "mask_path" in stored_result:
        stored_result["mask_file"] = task_relative_path(
            task_dir, Path(stored_result.pop("mask_path"))
        )

    latest_path = write_json(task_dir / model_result_filename(model), stored_result)
    history_path = write_json(run_dir / TaskArtifact.RUN_RESULT, stored_result)
    frontend_data = build_frontend_result(
        task_dir,
        image_path,
        **{model.value: result},
    )
    frontend_path = write_json(task_dir / TaskArtifact.FRONTEND_RESULT, frontend_data)

    result["task_dir"] = task_dir.name
    result["model_result_path"] = task_relative_path(task_dir, latest_path)
    result["history_result_path"] = task_relative_path(task_dir, history_path)
    result["frontend_result_path"] = task_relative_path(task_dir, frontend_path)
    record_task_run(task_dir, model, history_path)
    mark_task_completed(task_dir, model)
    return result


def build_frontend_result(
    task_dir: Path,
    image_path: Path,
    *,
    classification: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    '''构建不包含绝对路径的统一前端结果数据'''
    frontend_path = task_dir / TaskArtifact.FRONTEND_RESULT
    if frontend_path.is_file():
        result = json.loads(frontend_path.read_text(encoding="utf-8"))
        if not isinstance(result, dict):
            raise ValueError("前端结果文件格式无效")
        existing_image_file = result.get("image_file")
        if existing_image_file and existing_image_file != image_path.name:
            raise ValueError("一个任务只能包含同一张输入图像的结果")
    else:
        result = {
            "task_id": task_dir.name,
            "created_at": datetime.now().astimezone().isoformat(),
            "image_file": image_path.name,
            "result_files": {"frontend": TaskArtifact.FRONTEND_RESULT},
        }

    result["task_id"] = task_dir.name
    result["updated_at"] = datetime.now().astimezone().isoformat()
    result.pop("image_path", None)
    result["image_file"] = image_path.name
    result.setdefault("result_files", {})
    result.setdefault("latest_runs", {})
    result["result_files"]["frontend"] = TaskArtifact.FRONTEND_RESULT
    if classification is not None:
        result["classification"] = classification["classification"]
        result["result_files"]["classification"] = TaskArtifact.CLASSIFICATION_RESULT
        result["latest_runs"]["classification"] = (
            f"{classification['run_directory']}/{TaskArtifact.RUN_RESULT}"
        )
    if segmentation is not None:
        mask_file = task_relative_path(task_dir, Path(segmentation["mask_path"]))
        result["segmentation"] = {
            "model": segmentation["model"],
            "threshold": segmentation["threshold"],
            "tumor_pixels": segmentation["tumor_pixels"],
            "image_pixels": segmentation["image_pixels"],
            "tumor_area_ratio": segmentation["tumor_area_ratio"],
            "mask_file": mask_file,
        }
        result["result_files"]["segmentation"] = TaskArtifact.SEGMENTATION_RESULT
        result["result_files"]["mask"] = mask_file
        result["latest_runs"]["segmentation"] = (
            f"{segmentation['run_directory']}/{TaskArtifact.RUN_RESULT}"
        )
    completed_models = [
        name for name in ModelName if name.value in result
    ]
    result["completed_models"] = [name.value for name in completed_models]
    result["status"] = (
        TaskStatus.COMPLETED.value
        if len(completed_models) == len(ModelName)
        else TaskStatus.PARTIAL.value
    )
    return result

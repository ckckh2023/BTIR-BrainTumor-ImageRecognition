'''任务服务，对于任务存储，分类和分割模型的推理结果进行管理'''

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path
from typing import Any, BinaryIO
from PIL import Image, UnidentifiedImageError

# 允许传入的图像文件后缀
ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}

def validate_image_path(path: Path) -> Path:
    '''验证输入图像路径是否存在，并返回绝对路径'''
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError("输入图像不存在或不可读取")
    return resolved


def task_relative_path(task_dir: Path, path: Path) -> str:
    '''将任务内文件转换为可安全返回的相对路径。'''
    try:
        return path.resolve().relative_to(task_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("文件不属于当前任务") from exc


def create_task_dir(output_root: Path) -> Path:
    '''创建一个新的任务目录，目录名为当前时间戳'''
    output_root.mkdir(parents=True, exist_ok=True)
    task_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    task_dir = output_root / task_name
    if task_dir.exists():
        task_dir = output_root / f"{task_name}_{uuid.uuid4().hex[:6]}"
    task_dir.mkdir()
    return task_dir


def get_task_dir(output_root: Path, task_id: str | None) -> Path:
    '''获取任务目录，如果不存在则创建一个新的任务目录'''
    if not task_id:
        return create_task_dir(output_root)

    if Path(task_id).name != task_id or task_id in {".", ".."}:
        raise ValueError("--task-id 必须是任务目录名，不能是路径")

    task_dir = output_root / task_id
    if not task_dir.is_dir():
        raise ValueError("任务不存在")
    return task_dir.resolve()


def create_run_dir(task_dir: Path, model_name: str) -> Path:
    '''创建一个不可变的历史目录，用于单个模型调用'''
    run_root = task_dir / "runs" / model_name
    run_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    run_dir = run_root / run_id
    if run_dir.exists():
        run_dir = run_root / f"{run_id}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir()
    return run_dir


def initialize_task(
    task_dir: Path,
    source_image: Path,
    input_mode: str,
    name: str | None = None,
) -> Path:
    '''初始化任务目录，存储输入图像，并创建任务元数据'''
    source_image = source_image.resolve()
    input_dir = task_dir / "input"
    input_dir.mkdir(exist_ok=True)
    stored_image = input_dir / f"image{source_image.suffix.lower()}"

    actual_mode = input_mode
    if input_mode == "reference":
        task_image = source_image
    elif input_mode == "copy":
        shutil.copy2(source_image, stored_image)
        task_image = stored_image
    else:
        try:
            os.link(source_image, stored_image)
            actual_mode = "hardlink"
            task_image = stored_image
        except OSError as exc:
            if input_mode == "hardlink":
                raise ValueError(f"无法创建硬链接：{exc}") from exc
            shutil.copy2(source_image, stored_image)
            actual_mode = "copy"
            task_image = stored_image

    task_image = task_image.resolve()
    stored_path = (
        str(task_image.relative_to(task_dir))
        if task_image.is_relative_to(task_dir)
        else str(task_image)
    )
    now = datetime.now().astimezone().isoformat()
    write_json(
        task_dir / "task.json",
        {
            "task_id": task_dir.name,
            "name": name.strip() if name and name.strip() else task_dir.name,
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "completed_models": [],
            "input": {
                "path": stored_path,
                "source_file": source_image.name,
                "storage_mode": actual_mode,
                "size_bytes": task_image.stat().st_size,
                "sha256": sha256(task_image),
            },
        },
    )
    return task_image


def initialize_uploaded_task(
        task_dir: Path,
        upload: BinaryIO,
        filename: str | None,
        name: str | None = None,
) -> Path:
    '''初始化任务目录，存储上传的图像，并创建任务元数据'''
    original_filename = Path(filename or "").name
    suffix = Path(original_filename).suffix.lower()

    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise ValueError(f"仅支持以下图片格式:{allowed}")
    
    input_dir = task_dir / "input"
    input_dir.mkdir(exist_ok=True)
    task_image = input_dir / f"image{suffix}"

    try:
        with task_image.open("wb") as destination:
            shutil.copyfileobj(upload, destination)

        if task_image.stat().st_size == 0:
            raise ValueError("上传文件为空")
        
        with Image.open(task_image) as image:
            image.verify()
    except (OSError, UnidentifiedImageError) as exc:
        task_image.unlink(missing_ok=True)
        raise ValueError("上传文件不是可读取的图片") from exc
    
    task_image = task_image.resolve()
    now = datetime.now().astimezone().isoformat()

    write_json(
        task_dir / "task.json",
        {
            "task_id": task_dir.name,
            "name": name.strip() if name and name.strip() else task_dir.name,
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "completed_models": [],
            "input": {
                "path": str(task_image.relative_to(task_dir)),
                "original_filename": original_filename,
                "storage_mode": "uploaded",
                "size_bytes": task_image.stat().st_size,
                "sha256": sha256(task_image),
            },
        },
    )

    return task_image


def load_task_image(task_dir: Path) -> Path:
    '''加载任务目录中的输入图像路径，并验证其存在性'''
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        raise ValueError("任务元数据缺失")

    record = json.loads(task_file.read_text(encoding="utf-8"))
    input_record = record.get("input", {})
    stored_path = input_record.get("path")
    if not stored_path:
        raise ValueError("任务输入缺失")

    image_path = Path(stored_path)
    if not image_path.is_absolute():
        image_path = task_dir / image_path
    image_path = validate_image_path(image_path)

    expected_hash = input_record.get("sha256")
    if expected_hash and sha256(image_path) != expected_hash:
        raise ValueError("任务创建后输入图像已发生变化")
    return image_path


def write_json(path: Path, data: dict[str, Any]) -> Path:
    '''将字典数据写入JSON文件，并返回文件路径'''
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path.resolve()


def persist_model_result(
    task_dir: Path,
    image_path: Path,
    model_name: str,
    result: dict[str, Any],
    run_dir: Path | None = None,
) -> dict[str, Any]:
    '''将模型推理结果持久化到任务目录中，并更新任务元数据'''
    allowed_model_names = {"classification", "segmentation"}
    if model_name not in allowed_model_names:
        raise ValueError(
            f"不支持的模型名称: {model_name};"
            f"仅支持: {', '.join(sorted(allowed_model_names))}"
        )
    
    run_dir = run_dir or create_run_dir(task_dir, model_name)
    result["run_id"] = run_dir.name
    result["run_directory"] = run_dir.relative_to(task_dir).as_posix()

    stored_result = dict(result)
    stored_result.pop("image_path", None)
    if "mask_path" in stored_result:
        stored_result["mask_file"] = task_relative_path(
            task_dir, Path(stored_result.pop("mask_path"))
        )

    latest_path = write_json(task_dir / f"{model_name}.json", stored_result)
    history_path = write_json(run_dir / "result.json", stored_result)
    frontend_data = build_frontend_result(
        task_dir,
        image_path,
        **{model_name: result},
    )
    frontend_path = write_json(task_dir / "frontend_result.json", frontend_data)

    result["task_dir"] = task_dir.name
    result["model_result_path"] = task_relative_path(task_dir, latest_path)
    result["history_result_path"] = task_relative_path(task_dir, history_path)
    result["frontend_result_path"] = task_relative_path(task_dir, frontend_path)
    record_task_run(task_dir, model_name, history_path)
    mark_task_completed(task_dir, model_name)
    return result


def build_frontend_result(
    task_dir: Path,
    image_path: Path,
    *,
    classification: dict[str, Any] | None = None,
    segmentation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    '''构建前端结果数据结构，包含任务信息、输入图像路径以及分类和分割模型的结果'''
    frontend_path = task_dir / "frontend_result.json"
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
            "result_files": {"frontend": "frontend_result.json"},
        }

    result["task_id"] = task_dir.name
    result["updated_at"] = datetime.now().astimezone().isoformat()
    result.pop("image_path", None)
    result["image_file"] = image_path.name
    result.setdefault("result_files", {})
    result.setdefault("latest_runs", {})
    result["result_files"]["frontend"] = "frontend_result.json"
    if classification is not None:
        result["classification"] = classification["classification"]
        result["result_files"]["classification"] = "classification.json"
        result["latest_runs"]["classification"] = (
            f"{classification['run_directory']}/result.json"
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
        result["result_files"]["segmentation"] = "segmentation.json"
        result["result_files"]["mask"] = mask_file
        result["latest_runs"]["segmentation"] = (
            f"{segmentation['run_directory']}/result.json"
        )
    completed_models = [
        name for name in ("classification", "segmentation") if name in result
    ]
    result["completed_models"] = completed_models
    result["status"] = "completed" if len(completed_models) == 2 else "partial"
    return result


def mark_task_completed(task_dir: Path, *models: str) -> None:
    '''将指定模型标记为已完成，并更新任务元数据'''
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        return

    record = json.loads(task_file.read_text(encoding="utf-8"))
    completed = set(record.get("completed_models", []))
    completed.update(models)
    record["completed_models"] = sorted(completed)
    record["status"] = "completed" if {"classification", "segmentation"} <= completed else "partial"
    record["updated_at"] = datetime.now().astimezone().isoformat()
    write_json(task_file, record)


def record_task_run(task_dir: Path, model_name: str, result_path: Path) -> None:
    '''记录模型运行结果到任务元数据中'''
    task_file = task_dir / "task.json"
    if not task_file.is_file():
        return

    record = json.loads(task_file.read_text(encoding="utf-8"))
    relative_result_path = task_relative_path(task_dir, result_path)
    record.setdefault("runs", []).append(
        {
            "run_id": result_path.parent.name,
            "model": model_name,
            "result_file": relative_result_path,
            "created_at": datetime.now().astimezone().isoformat(),
        }
    )
    record["updated_at"] = datetime.now().astimezone().isoformat()
    write_json(task_file, record)


def sha256(path: Path) -> str:
    '''计算文件的SHA256哈希值'''
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

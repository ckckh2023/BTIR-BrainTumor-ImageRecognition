'''任务目录、输入图片与 JSON 文件的管理'''

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO

from PIL import Image, UnidentifiedImageError

from repositories.task_repository import task_repository


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}


def validate_image_path(path: Path) -> Path:
    '''验证输入图片存在且可读取，返回绝对路径'''
    resolved = path.expanduser().resolve()
    if not resolved.is_file():
        raise ValueError("输入图像不存在或不可读取")
    return resolved


def task_relative_path(task_dir: Path, path: Path) -> str:
    '''将任务目录内的文件转换为可安全返回的相对路径'''
    try:
        return path.resolve().relative_to(task_dir.resolve()).as_posix()
    except ValueError as exc:
        raise ValueError("文件不属于当前任务") from exc


def create_task_dir(output_root: Path) -> Path:
    '''创建以时间戳命名的新任务目录'''
    output_root.mkdir(parents=True, exist_ok=True)
    task_name = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    task_dir = output_root / task_name
    if task_dir.exists():
        task_dir = output_root / f"{task_name}_{uuid.uuid4().hex[:6]}"
    task_dir.mkdir()
    return task_dir


def get_task_dir(output_root: Path, task_id: str | None) -> Path:
    '''获取任务目录；未指定任务 ID 时创建新目录'''
    if not task_id:
        return create_task_dir(output_root)

    if Path(task_id).name != task_id or task_id in {".", ".."}:
        raise ValueError("--task-id 必须是任务目录名，不能是路径")

    task_dir = output_root / task_id
    if not task_dir.is_dir():
        raise ValueError("任务不存在")
    return task_dir.resolve()


def create_run_dir(task_dir: Path, model_name: str) -> Path:
    '''创建单次模型调用对应的不可变历史目录'''
    run_root = task_dir / "runs" / model_name
    run_root.mkdir(parents=True, exist_ok=True)
    run_id = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
    run_dir = run_root / run_id
    if run_dir.exists():
        run_dir = run_root / f"{run_id}_{uuid.uuid4().hex[:6]}"
    run_dir.mkdir()
    return run_dir


def _save_created_task(
    task_dir: Path,
    name: str | None,
    input_record: dict[str, Any],
) -> None:
    '''以统一结构写入新建任务的元数据'''
    now = datetime.now().astimezone().isoformat()
    task_repository.save(
        task_dir,
        {
            "task_id": task_dir.name,
            "name": name.strip() if name and name.strip() else task_dir.name,
            "status": "created",
            "created_at": now,
            "updated_at": now,
            "completed_models": [],
            "input": input_record,
        },
    )


def initialize_task(
    task_dir: Path,
    source_image: Path,
    input_mode: str,
    name: str | None = None,
) -> Path:
    '''保存本机图片引用或副本，并创建任务元数据'''
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
    _save_created_task(
        task_dir,
        name,
        {
            "path": stored_path,
            "source_file": source_image.name,
            "storage_mode": actual_mode,
            "size_bytes": task_image.stat().st_size,
            "sha256": sha256(task_image),
        },
    )
    return task_image


def initialize_uploaded_task(
    task_dir: Path,
    upload: BinaryIO,
    filename: str | None,
    name: str | None = None,
) -> Path:
    '''保存浏览器上传的图片，并创建任务元数据'''
    original_filename = Path(filename or "").name
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise ValueError(f"仅支持以下图片格式：{allowed}")

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
    _save_created_task(
        task_dir,
        name,
        {
            "path": str(task_image.relative_to(task_dir)),
            "original_filename": original_filename,
            "storage_mode": "uploaded",
            "size_bytes": task_image.stat().st_size,
            "sha256": sha256(task_image),
        },
    )
    return task_image


def load_task_image(task_dir: Path) -> Path:
    '''读取任务输入图片，并校验其未在创建后被修改'''
    record = task_repository.load(task_dir)
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
    '''以原子替换方式写入 JSON，避免半写入文件被读取'''
    path.parent.mkdir(parents=True, exist_ok=True)
    file_descriptor, temporary_name = tempfile.mkstemp(
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        text=True,
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(file_descriptor, "w", encoding="utf-8") as temporary_file:
            json.dump(data, temporary_file, ensure_ascii=False, indent=2)
            temporary_file.write("\n")
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        os.replace(temporary_path, path)
    except Exception:
        temporary_path.unlink(missing_ok=True)
        raise
    return path.resolve()


def sha256(path: Path) -> str:
    '''计算文件的 SHA-256 哈希值'''
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

'''任务目录、输入图片与 JSON 文件的管理'''

from __future__ import annotations

from datetime import datetime
import hashlib
import json
import math
import os
import shutil
import tempfile
import uuid
import warnings
from pathlib import Path
from typing import Any, BinaryIO
from collections.abc import Mapping

from PIL import Image, UnidentifiedImageError

from core.settings import SETTINGS
from core.task_records import StoredTaskInput, StoredTaskModality, TaskRecord
from repositories.task_repository import task_repository
from core.task_definitions import (
    AnalysisMode,
    InputStorageMode,
    TaskDirectory,
    TaskStatus,
    expected_models_for_mode,
)


ALLOWED_IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png"}
VOLUME_MODALITIES = ("flair", "t1ce", "t1", "t2")
UPLOAD_COPY_CHUNK_BYTES = 1024 * 1024


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
    run_root = task_dir / TaskDirectory.RUNS / model_name
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
    input_record: StoredTaskInput,
    user_id: str | None = None,
    analysis_mode: AnalysisMode = AnalysisMode.TWO_D,
) -> None:
    '''以统一结构写入新建任务的元数据'''
    now = datetime.now().astimezone()
    task_repository.save(
        task_dir,
        TaskRecord(
            task_id=task_dir.name,
            name=name.strip() if name and name.strip() else task_dir.name,
            status=TaskStatus.CREATED,
            created_at=now,
            updated_at=now,
            analysis_mode=analysis_mode,
            expected_models=sorted(
                expected_models_for_mode(analysis_mode),
                key=lambda model: model.value,
            ),
            input=input_record,
        ),
        user_id=user_id,
    )


def initialize_task(
    task_dir: Path,
    source_image: Path,
    input_mode: InputStorageMode | str,
    name: str | None = None,
    user_id: str | None = None,
) -> Path:
    '''保存本机图片引用或副本，并创建任务元数据'''
    source_image = source_image.resolve()
    input_dir = task_dir / TaskDirectory.INPUT
    input_dir.mkdir(exist_ok=True)
    stored_image = input_dir / f"image{source_image.suffix.lower()}"

    try:
        storage_mode = InputStorageMode(input_mode)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in InputStorageMode)
        raise ValueError(f"不支持的输入保存方式：{input_mode}；仅支持 {allowed}") from exc

    actual_mode = storage_mode.value
    if storage_mode is InputStorageMode.COPY:
        shutil.copy2(source_image, stored_image)
        task_image = stored_image
    else:
        try:
            os.link(source_image, stored_image)
            actual_mode = "hardlink"
            task_image = stored_image
        except OSError as exc:
            if storage_mode is InputStorageMode.HARDLINK:
                raise ValueError(f"无法创建硬链接：{exc}") from exc
            shutil.copy2(source_image, stored_image)
            actual_mode = "copy"
            task_image = stored_image

    task_image = task_image.resolve()
    _save_created_task(
        task_dir,
        name,
        StoredTaskInput(
            path=str(task_image.relative_to(task_dir)),
            original_filename=source_image.name,
            storage_mode=actual_mode,
            size_bytes=task_image.stat().st_size,
            sha256=sha256(task_image),
        ),
        user_id=user_id,
    )
    return task_image


def initialize_uploaded_task(
    task_dir: Path,
    upload: BinaryIO,
    filename: str | None,
    name: str | None = None,
    user_id: str | None = None,
) -> Path:
    '''保存浏览器上传的图片，并创建任务元数据'''
    original_filename = Path(filename or "").name
    suffix = Path(original_filename).suffix.lower()
    if suffix not in ALLOWED_IMAGE_SUFFIXES:
        allowed = ", ".join(sorted(ALLOWED_IMAGE_SUFFIXES))
        raise ValueError(f"仅支持以下图片格式：{allowed}")

    input_dir = task_dir / TaskDirectory.INPUT
    input_dir.mkdir(exist_ok=True)
    task_image = input_dir / f"image{suffix}"
    try:
        with task_image.open("wb") as destination:
            _copy_upload_with_limit(
                upload,
                destination,
                SETTINGS.max_upload_bytes,
            )

        _verify_uploaded_image(task_image, SETTINGS.max_image_pixels)
    except ValueError:
        task_image.unlink(missing_ok=True)
        raise
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        task_image.unlink(missing_ok=True)
        raise ValueError("上传文件不是可读取的图片") from exc

    task_image = task_image.resolve()
    _save_created_task(
        task_dir,
        name,
        StoredTaskInput(
            path=str(task_image.relative_to(task_dir)),
            original_filename=original_filename,
            storage_mode="uploaded",
            size_bytes=task_image.stat().st_size,
            sha256=sha256(task_image),
        ),
        user_id=user_id,
    )
    return task_image


def initialize_uploaded_volume_task(
    task_dir: Path,
    uploads: Mapping[str, BinaryIO],
    filenames: Mapping[str, str | None],
    name: str | None = None,
    user_id: str | None = None,
) -> dict[str, Path]:
    '''保存四模态 NIfTI，并创建一个独立的 3D 任务'''

    if set(uploads) != set(VOLUME_MODALITIES):
        raise ValueError("3D 任务必须同时提供 flair、t1ce、t1、t2 四个模态")

    input_dir = task_dir / TaskDirectory.INPUT
    input_dir.mkdir(exist_ok=True)
    stored_paths: dict[str, Path] = {}
    original_filenames: dict[str, str] = {}
    total_size = 0

    try:
        for modality in VOLUME_MODALITIES:
            original_filename = Path(filenames.get(modality) or "").name
            suffix = _nifti_suffix(original_filename)
            if suffix is None:
                raise ValueError(
                    f"{modality} 仅支持 .nii 或 .nii.gz 文件"
                )

            stored_path = input_dir / f"{modality}{suffix}"
            stored_paths[modality] = stored_path.resolve()
            with stored_path.open("wb") as destination:
                _copy_upload_with_limit(
                    uploads[modality],
                    destination,
                    SETTINGS.max_3d_upload_bytes,
                )
            original_filenames[modality] = original_filename
            total_size += stored_path.stat().st_size
            if total_size > SETTINGS.max_3d_upload_bytes:
                raise ValueError(
                    "四模态上传总大小超过限制"
                    f"（最大 {SETTINGS.max_3d_upload_bytes} 字节）"
                )
        _validate_volume_headers(stored_paths)
    except Exception:
        for path in stored_paths.values():
            path.unlink(missing_ok=True)
        raise

    modality_records = {
        modality: StoredTaskModality(
            path=str(stored_paths[modality].relative_to(task_dir)),
            original_filename=original_filenames[modality],
            size_bytes=stored_paths[modality].stat().st_size,
            sha256=sha256(stored_paths[modality]),
        )
        for modality in VOLUME_MODALITIES
    }
    _save_created_task(
        task_dir,
        name,
        StoredTaskInput(
            path=str(input_dir.resolve().relative_to(task_dir)),
            storage_mode="uploaded_multimodal",
            size_bytes=total_size,
            sha256=_modality_manifest_hash(modality_records),
            modalities=modality_records,
        ),
        user_id=user_id,
        analysis_mode=AnalysisMode.THREE_D,
    )
    return stored_paths


def load_task_modalities(task_dir: Path) -> dict[str, Path]:
    '''读取并校验一个 3D 任务保存的四模态输入'''

    record = task_repository.load(task_dir)
    if record.analysis_mode is not AnalysisMode.THREE_D:
        raise ValueError("当前任务不是 3D 任务")
    modality_records = record.input.modalities
    if not modality_records or set(modality_records) != set(VOLUME_MODALITIES):
        raise ValueError("3D 任务缺少完整的四模态输入记录")

    resolved: dict[str, Path] = {}
    task_root = task_dir.resolve()
    for modality in VOLUME_MODALITIES:
        stored = modality_records[modality]
        path = (task_dir / stored.path).resolve()
        try:
            path.relative_to(task_root)
        except ValueError as exc:
            raise ValueError(f"{modality} 输入路径不属于当前任务") from exc
        if not path.is_file():
            raise ValueError(f"{modality} 输入文件不存在")
        if stored.sha256 and sha256(path) != stored.sha256:
            raise ValueError(f"{modality} 输入文件在任务创建后发生变化")
        resolved[modality] = path
    return resolved


def _nifti_suffix(filename: str) -> str | None:
    lowered = filename.lower()
    if lowered.endswith(".nii.gz"):
        return ".nii.gz"
    if lowered.endswith(".nii"):
        return ".nii"
    return None


def _validate_volume_headers(paths: Mapping[str, Path]) -> None:
    '''仅读取 NIfTI 头部，拒绝空间不一致的四模态上传'''

    try:
        import nibabel as nib
        import numpy as np
    except ImportError as exc:
        raise RuntimeError("3D NIfTI 校验依赖 nibabel 和 numpy") from exc

    images = {}
    for modality in VOLUME_MODALITIES:
        try:
            image = nib.load(str(paths[modality]))
        except Exception as exc:
            raise ValueError(f"{modality} 不是可读取的 NIfTI 文件") from exc
        if len(image.shape) != 3 or any(int(size) <= 0 for size in image.shape):
            raise ValueError(f"{modality} 必须是有效的三维 NIfTI")
        voxel_count = math.prod(int(size) for size in image.shape)
        if voxel_count > SETTINGS.max_3d_voxels:
            raise ValueError(
                f"{modality} 体素数超过限制"
                f"（最大 {SETTINGS.max_3d_voxels}）"
            )
        affine = np.asarray(image.affine, dtype=np.float64)
        if (
            affine.shape != (4, 4)
            or not np.isfinite(affine).all()
            or abs(float(np.linalg.det(affine[:3, :3]))) < 1e-8
        ):
            raise ValueError(f"{modality} 的 affine 无效")
        if any(axis is None for axis in nib.aff2axcodes(affine)):
            raise ValueError(f"{modality} 的空间方向无效")
        images[modality] = image

    reference = images["flair"]
    reference_zooms = reference.header.get_zooms()[:3]
    reference_orientation = nib.aff2axcodes(reference.affine)
    for modality in VOLUME_MODALITIES[1:]:
        image = images[modality]
        if image.shape != reference.shape:
            raise ValueError(
                f"四模态 shape 不一致：flair={reference.shape}，"
                f"{modality}={image.shape}"
            )
        if not np.allclose(
            image.affine,
            reference.affine,
            rtol=1e-5,
            atol=1e-4,
        ):
            raise ValueError(f"{modality} 与 flair 的 affine 不一致")
        if not np.allclose(
            image.header.get_zooms()[:3],
            reference_zooms,
            rtol=1e-5,
            atol=1e-5,
        ):
            raise ValueError(f"{modality} 与 flair 的体素间距不一致")
        if nib.aff2axcodes(image.affine) != reference_orientation:
            raise ValueError(f"{modality} 与 flair 的空间方向不一致")


def _modality_manifest_hash(
    modalities: Mapping[str, StoredTaskModality],
) -> str:
    digest = hashlib.sha256()
    for modality in VOLUME_MODALITIES:
        digest.update(modality.encode("ascii"))
        digest.update(modalities[modality].sha256.encode("ascii"))
    return digest.hexdigest()


def _copy_upload_with_limit(
    upload: BinaryIO,
    destination: BinaryIO,
    max_upload_bytes: int,
) -> None:
    '''分块写入上传内容，避免单个请求无限占用磁盘'''
    written_bytes = 0
    while chunk := upload.read(UPLOAD_COPY_CHUNK_BYTES):
        written_bytes += len(chunk)
        if written_bytes > max_upload_bytes:
            raise ValueError(
                f"上传文件超过大小限制（最大 {max_upload_bytes} 字节）"
            )
        destination.write(chunk)

    if written_bytes == 0:
        raise ValueError("上传文件为空")


def _verify_uploaded_image(image_path: Path, max_image_pixels: int) -> None:
    '''验证上传文件可解码，且解码后的像素数量不超过限制'''
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", Image.DecompressionBombWarning)
        with Image.open(image_path) as image:
            width, height = image.size
            if width * height > max_image_pixels:
                raise ValueError(
                    f"图像像素超过限制（最大 {max_image_pixels} 像素）"
                )
            image.verify()


def load_task_image(task_dir: Path) -> Path:
    '''读取任务输入图片，并校验其未在创建后被修改'''
    record = task_repository.load(task_dir)
    input_record = record.input
    stored_path = input_record.path
    if not stored_path:
        raise ValueError("任务输入缺失")

    image_path = Path(stored_path)
    if not image_path.is_absolute():
        image_path = task_dir / image_path
    image_path = validate_image_path(image_path)

    expected_hash = input_record.sha256
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

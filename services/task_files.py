'''任务目录、四模态体数据与 JSON 文件的管理'''

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import gzip
import hashlib
import json
import math
import os
import tempfile
import uuid
from pathlib import Path
from typing import Any, BinaryIO
from collections.abc import Mapping

from core.settings import SETTINGS
from core.task_records import StoredTaskInput, StoredTaskModality, TaskRecord
from repositories.task_repository import task_repository
from core.task_definitions import TaskDirectory, TaskStatus


VOLUME_MODALITIES = ("flair", "t1ce", "t1", "t2")
UPLOAD_COPY_CHUNK_BYTES = 1024 * 1024


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


def get_task_dir(output_root: Path, task_id: str) -> Path:
    '''校验任务 ID 并返回已经存在的任务目录'''
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
            input=input_record,
        ),
        user_id=user_id,
    )


def initialize_uploaded_volume_task(
    task_dir: Path,
    uploads: Mapping[str, BinaryIO],
    filenames: Mapping[str, str | None],
    name: str | None = None,
    user_id: str | None = None,
) -> dict[str, Path]:
    '''保存四模态 NIfTI，并创建一个独立的 3D 任务

    上传字节先原样暂存，用于大小限制与空间一致性校验；随后统一以
    ``.nii.gz`` 落盘：原本就是 gzip 的上传直接复用，未压缩的 ``.nii``
    在服务器上压缩一次，避免前端 3D 查看时反复传输大文件。
    '''

    if set(uploads) != set(VOLUME_MODALITIES):
        raise ValueError("3D 任务必须同时提供 flair、t1ce、t1、t2 四个模态")

    input_dir = task_dir / TaskDirectory.INPUT
    input_dir.mkdir(exist_ok=True)
    staging_paths: dict[str, Path] = {}
    stored_paths: dict[str, Path] = {}
    original_filenames: dict[str, str] = {}
    upload_sizes: dict[str, int] = {}
    upload_hashes: dict[str, str] = {}
    stored_sizes: dict[str, int] = {}
    stored_hashes: dict[str, str] = {}
    created_files: list[Path] = []
    total_size = 0

    try:
        for modality in VOLUME_MODALITIES:
            original_filename = Path(filenames.get(modality) or "").name
            suffix = _nifti_suffix(original_filename)
            if suffix is None:
                raise ValueError(
                    f"{modality} 仅支持 .nii 或 .nii.gz 文件"
                )

            staging_path = input_dir / f".{modality}{suffix}"
            with staging_path.open("wb") as destination:
                upload_size, upload_hash = _copy_upload_with_limit(
                    uploads[modality],
                    destination,
                    SETTINGS.max_3d_upload_bytes,
                )
            original_filenames[modality] = original_filename
            upload_sizes[modality] = upload_size
            upload_hashes[modality] = upload_hash
            staging_paths[modality] = staging_path
            created_files.append(staging_path)
            total_size += upload_size
            if total_size > SETTINGS.max_3d_upload_bytes:
                raise ValueError(
                    "四模态上传总大小超过限制"
                    f"（最大 {SETTINGS.max_3d_upload_bytes} 字节）"
                )

        _validate_volume_headers(staging_paths)

        for modality in VOLUME_MODALITIES:
            staging_path = staging_paths[modality]
            stored_path = input_dir / f"{modality}.nii.gz"
            try:
                if _nifti_suffix(original_filenames[modality]) == ".nii.gz":
                    os.replace(staging_path, stored_path)
                    stored_sizes[modality] = upload_sizes[modality]
                    stored_hashes[modality] = upload_hashes[modality]
                else:
                    stored_sizes[modality], stored_hashes[modality] = (
                        _gzip_stage_to_destination(staging_path, stored_path)
                    )
                stored_paths[modality] = stored_path.resolve()
                created_files.append(stored_path)
            finally:
                staging_path.unlink(missing_ok=True)
    except Exception:
        for path in created_files:
            path.unlink(missing_ok=True)
        raise

    modality_records = {
        modality: StoredTaskModality(
            path=task_relative_path(task_dir, stored_paths[modality]),
            original_filename=original_filenames[modality],
            size_bytes=stored_sizes[modality],
            sha256=stored_hashes[modality],
        )
        for modality in VOLUME_MODALITIES
    }
    _save_created_task(
        task_dir,
        name,
        StoredTaskInput(
            size_bytes=sum(stored_sizes.values()),
            sha256=_modality_manifest_hash(modality_records),
            modalities=modality_records,
        ),
        user_id=user_id,
    )
    return stored_paths


def _gzip_stage_to_destination(source: Path, destination: Path) -> tuple[int, str]:
    '''把未压缩的阶段文件压缩为 ``.nii.gz``，返回最终文件大小与哈希'''
    with source.open("rb") as raw, destination.open("wb") as output:
        with gzip.GzipFile(filename="", mode="wb", fileobj=output, mtime=0) as gzip_stream:
            while chunk := raw.read(UPLOAD_COPY_CHUNK_BYTES):
                gzip_stream.write(chunk)
    return destination.stat().st_size, sha256(destination)


def load_task_modalities(task_dir: Path) -> dict[str, Path]:
    '''读取并校验一个 3D 任务保存的四模态输入'''

    record = task_repository.load(task_dir)
    if record.analysis_mode != "3d":
        raise ValueError("当前任务不是 3D 任务")
    modality_records = record.input.modalities
    if not modality_records or set(modality_records) != set(VOLUME_MODALITIES):
        raise ValueError("3D 任务缺少完整的四模态输入记录")

    resolved: dict[str, Path] = {}
    hashes_to_verify: list[tuple[str, Path, str]] = []
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
        if path.stat().st_size != stored.size_bytes:
            raise ValueError(f"{modality} 输入文件在任务创建后发生变化")
        if stored.sha256:
            hashes_to_verify.append((modality, path, stored.sha256))
        resolved[modality] = path

    with ThreadPoolExecutor(max_workers=len(hashes_to_verify) or 1) as executor:
        actual_hashes = list(
            executor.map(sha256, (item[1] for item in hashes_to_verify))
        )
    for (modality, _, expected_hash), actual_hash in zip(
        hashes_to_verify,
        actual_hashes,
        strict=True,
    ):
        if actual_hash != expected_hash:
            raise ValueError(f"{modality} 输入文件在任务创建后发生变化")
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
) -> tuple[int, str]:
    '''分块写入并同步计算哈希，避免保存后再次完整读取文件'''
    written_bytes = 0
    digest = hashlib.sha256()
    while chunk := upload.read(UPLOAD_COPY_CHUNK_BYTES):
        written_bytes += len(chunk)
        if written_bytes > max_upload_bytes:
            raise ValueError(
                f"上传文件超过大小限制（最大 {max_upload_bytes} 字节）"
            )
        destination.write(chunk)
        digest.update(chunk)

    if written_bytes == 0:
        raise ValueError("上传文件为空")
    return written_bytes, digest.hexdigest()


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

'''DICOM 多序列识别与 NIfTI 转换'''

from __future__ import annotations

from contextlib import ExitStack
import re
import shutil
from datetime import date
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Mapping

from core.settings import SETTINGS
from core.task_definitions import VOLUME_MODALITIES
from services.task_files import initialize_uploaded_volume_task


class DICOMSeriesSelectionRequired(ValueError):
    '''DICOM 存在重复模态序列时要求用户确认'''

    def __init__(self, modalities: dict[str, list[dict[str, object]]]) -> None:
        self.modalities = modalities
        labels = "、".join(modality.upper() for modality in modalities)
        super().__init__(f"请为 {labels} 选择用于分析的 DICOM 序列")


def initialize_uploaded_dicom_task(
    task_dir: Path,
    uploads: Iterable[tuple[str, BinaryIO]],
    *,
    name: str | None = None,
    case_id: str | None = None,
    case_name: str | None = None,
    study_date: date | None = None,
    user_id: str | None = None,
    max_tasks_per_user: int | None = None,
    selected_series_uids: Mapping[str, str | None] | None = None,
) -> dict[str, Path]:
    '''将同一病例的 DICOM 序列转换为四模态 NIfTI 任务'''

    staging_dir = task_dir / ".dicom-staging"
    converted_dir = task_dir / ".dicom-converted"
    staging_dir.mkdir(parents=True)
    try:
        paths, source_filenames = _save_dicom_uploads(staging_dir, uploads)
        selected_series = _select_dicom_series(
            paths,
            selected_series_uids,
            source_filenames,
        )
        converted_paths = _convert_dicom_series(
            staging_dir,
            converted_dir,
            selected_series,
        )
        with ExitStack() as streams:
            return initialize_uploaded_volume_task(
                task_dir=task_dir,
                uploads={
                    modality: streams.enter_context(converted_paths[modality].open("rb"))
                    for modality in VOLUME_MODALITIES
                },
                filenames={
                    modality: f"{modality}_from_dicom.nii.gz"
                    for modality in VOLUME_MODALITIES
                },
                name=name,
                case_id=case_id,
                case_name=case_name,
                study_date=study_date,
                user_id=user_id,
                max_tasks_per_user=max_tasks_per_user,
            )
    finally:
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(converted_dir, ignore_errors=True)


def _save_dicom_uploads(
    destination: Path,
    uploads: Iterable[tuple[str, BinaryIO]],
) -> tuple[list[Path], dict[Path, str]]:
    '''限制总大小后保存待转换的 DICOM 文件'''

    paths: list[Path] = []
    source_filenames: dict[Path, str] = {}
    total_size = 0
    for index, (upload_name, upload) in enumerate(uploads, 1):
        if index > SETTINGS.max_dicom_files:
            raise ValueError(
                "DICOM 文件数量超过限制"
                f"（最多 {SETTINGS.max_dicom_files} 个）"
            )
        path = destination / f"{index:05d}.dcm"
        with path.open("wb") as output:
            while chunk := upload.read(SETTINGS.upload_copy_chunk_bytes):
                total_size += len(chunk)
                if total_size > SETTINGS.max_3d_upload_bytes:
                    raise ValueError("DICOM 上传总大小超过限制")
                output.write(chunk)
        if path.stat().st_size:
            paths.append(path)
            source_filenames[path] = _dicom_source_directory(upload_name)

    if not paths:
        raise ValueError("未收到可转换的 DICOM 文件")
    return paths, source_filenames


def _select_dicom_series(
    paths: list[Path],
    selected_series_uids: Mapping[str, str | None] | None = None,
    source_filenames: Mapping[Path, str] | None = None,
) -> dict[str, str]:
    '''按 SeriesInstanceUID 归类并识别四个所需模态'''

    try:
        import pydicom
    except ImportError as exc:
        raise RuntimeError("DICOM 转换依赖 pydicom") from exc

    series: dict[str, dict[str, object]] = {}
    for path in paths:
        try:
            dataset = pydicom.dcmread(
                path,
                stop_before_pixels=True,
                force=True,
                specific_tags=[
                    "SeriesInstanceUID",
                    "SeriesDescription",
                    "ProtocolName",
                    "SequenceName",
                    "ImageType",
                    "ContrastBolusAgent",
                ],
            )
        except Exception:
            continue
        series_uid = str(getattr(dataset, "SeriesInstanceUID", "")).strip()
        if not series_uid:
            continue
        description = " ".join(
            str(getattr(dataset, field, ""))
            for field in (
                "SeriesDescription",
                "ProtocolName",
                "SequenceName",
                "ImageType",
                "ContrastBolusAgent",
            )
        )
        item = series.setdefault(
            series_uid,
            {
                "description": description,
                "label": str(getattr(dataset, "SeriesDescription", "")).strip()
                or str(getattr(dataset, "ProtocolName", "")).strip()
                or "未命名序列",
                "file_count": 0,
                "source_name": (source_filenames or {}).get(path, ""),
            },
        )
        item["file_count"] = int(item["file_count"]) + 1

    candidates: dict[str, list[dict[str, object]]] = {
        modality: [] for modality in VOLUME_MODALITIES
    }
    for series_uid, metadata in series.items():
        modality = _modality_from_dicom_description(str(metadata["description"]))
        if modality is not None:
            candidates[modality].append(
                {
                    "series_uid": series_uid,
                    "label": str(metadata["label"]),
                    "file_count": int(metadata["file_count"]),
                    "source_name": str(metadata["source_name"]),
                }
            )

    errors: list[str] = []
    selected: dict[str, str] = {}
    ambiguities: dict[str, list[dict[str, object]]] = {}
    for modality in VOLUME_MODALITIES:
        matches = candidates[modality]
        if not matches:
            errors.append(f"未识别到 {modality.upper()} DICOM 序列")
        else:
            requested_uid = (selected_series_uids or {}).get(modality)
            if requested_uid:
                if any(item["series_uid"] == requested_uid for item in matches):
                    selected[modality] = requested_uid
                else:
                    errors.append(f"所选 {modality.upper()} DICOM 序列无效")
            elif len(matches) == 1:
                selected[modality] = str(matches[0]["series_uid"])
            else:
                ambiguities[modality] = matches
    if errors:
        raise ValueError(
            "DICOM 病例需同时包含 FLAIR、T1CE、T1、T2 序列；"
            + "；".join(errors)
        )
    if ambiguities:
        raise DICOMSeriesSelectionRequired(ambiguities)
    return selected


def _dicom_source_directory(filename: str) -> str:
    '''提取上传文件所在的序列目录名称'''

    parent = PurePosixPath(filename.replace("\\", "/")).parent.name
    return parent if parent not in {"", "."} else ""


def _modality_from_dicom_description(description: str) -> str | None:
    '''根据常见 DICOM 序列描述识别输入模态'''

    value = description.lower()
    compact = re.sub(r"[^a-z0-9+]", "", value)
    has_t1 = bool(re.search(r"(?:^|[^a-z0-9])t1(?:$|[^a-z0-9])", value)) or "t1" in compact
    has_t2 = bool(re.search(r"(?:^|[^a-z0-9])t2(?:$|[^a-z0-9])", value)) or "t2" in compact
    if "flair" in compact:
        return "flair"
    has_contrast_suffix = bool(
        re.search(r"(?:^|[^a-z0-9])(?:c|ce)(?:$|[^a-z0-9])", value)
    )
    if has_t1 and any(
        marker in compact
        for marker in ("t1ce", "t1c", "t1gd", "postcontrast", "postcon", "contrast", "enhanc", "+c", "gad")
    ) or (has_t1 and has_contrast_suffix):
        return "t1ce"
    if has_t1:
        return "t1"
    if has_t2:
        return "t2"
    return None


def _convert_dicom_series(
    staging_dir: Path,
    destination: Path,
    series_uids: dict[str, str],
) -> dict[str, Path]:
    '''读取 DICOM 序列并全部重采样至 FLAIR 空间'''

    try:
        import SimpleITK as sitk
    except ImportError as exc:
        raise RuntimeError("DICOM 转换依赖 SimpleITK") from exc

    available_series = set(sitk.ImageSeriesReader.GetGDCMSeriesIDs(str(staging_dir)) or [])
    images = {}
    for modality in VOLUME_MODALITIES:
        series_uid = series_uids[modality]
        if series_uid not in available_series:
            raise ValueError(f"无法读取 {modality.upper()} DICOM 序列")
        file_names = sitk.ImageSeriesReader.GetGDCMSeriesFileNames(
            str(staging_dir),
            series_uid,
        )
        reader = sitk.ImageSeriesReader()
        reader.SetFileNames(file_names)
        image = reader.Execute()
        if image.GetDimension() != 3 or min(image.GetSize()) <= 1:
            raise ValueError(f"{modality.upper()} DICOM 序列不是有效三维体数据")
        images[modality] = sitk.Cast(image, sitk.sitkFloat32)

    destination.mkdir()
    reference = images["flair"]
    converted: dict[str, Path] = {}
    for modality in VOLUME_MODALITIES:
        image = images[modality]
        if modality != "flair":
            image = sitk.Resample(
                image,
                reference,
                sitk.Transform(),
                sitk.sitkLinear,
                0.0,
                sitk.sitkFloat32,
            )
        destination_path = destination / f"{modality}.nii.gz"
        sitk.WriteImage(image, str(destination_path), useCompression=True)
        converted[modality] = destination_path
    return converted

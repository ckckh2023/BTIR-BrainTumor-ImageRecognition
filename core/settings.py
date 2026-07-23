'''项目运行配置的唯一入口'''

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from accelerator import validate_device
from core.task_definitions import ModelName


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"


def _load_env_file(path: Path) -> None:
    '''读取项目根目录的 .env；系统环境变量优先级更高'''
    if not path.is_file():
        return

    for line_number, raw_line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f".env 第 {line_number} 行格式错误，应为 KEY=VALUE")

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key.startswith("BTIR_"):
            os.environ.setdefault(key, value)


def _get_path(name: str, default: str) -> Path:
    '''获取环境变量指定的路径，若未指定则使用默认值；相对路径会被解析为相对于项目根目录的绝对路径'''
    value = Path(os.getenv(name, default)).expanduser()
    return (PROJECT_ROOT / value).resolve() if not value.is_absolute() else value.resolve()


def _get_threshold() -> float:
    '''获取默认分割阈值，确保其在 0 到 1 之间'''
    value = float(os.getenv("BTIR_DEFAULT_SEGMENT_THRESHOLD", "0.5"))
    if not 0.0 <= value <= 1.0:
        raise ValueError("BTIR_DEFAULT_SEGMENT_THRESHOLD 必须在 0 到 1 之间")
    return value


def _get_origins() -> list[str]:
    '''获取允许跨域请求的前端地址列表'''
    raw_value = os.getenv(
        "BTIR_CORS_ORIGINS",
        "http://127.0.0.1:8000,http://localhost:8000,null",
    )
    return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


def _get_positive_int(name: str, default: int) -> int:
    '''获取int类型正数'''
    value = int(os.getenv(name, str(default)))
    if value <= 0:
        raise ValueError(f"{name} 必须是大于 0 的整数")
    return value


def _get_nonnegative_int(name: str, default: int) -> int:
    '''获取 int 类型非负数'''
    value = int(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} 不能小于 0")
    return value


def _get_bool(name: str, default: bool) -> bool:
    '''获取布尔环境变量。'''
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true 或 false")


def _get_nonnegative_float(name: str, default: float) -> float:
    '''获取float类型非负数'''
    value = float(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} 不能小于 0")
    return value


@dataclass(frozen=True)
class Settings:
    '''由环境变量和 .env 文件构建的不可变运行配置'''

    project_root: Path
    output_dir: Path
    frontend_dir: Path
    classifier_script: Path
    classifier_model: Path
    classifier_config: Path
    segmenter_script: Path
    segmenter_model: Path
    task_database_path: Path
    task_archive_dir: Path
    device: str
    default_segment_threshold: float
    max_upload_bytes: int
    max_image_pixels: int
    cors_origins: list[str]
    redis_url: str
    task_lock_timeout_seconds: int
    task_lock_wait_seconds: float
    task_queue_name: str
    task_job_timeout_seconds: int
    task_job_result_ttl_seconds: int
    task_job_max_retries: int
    task_stale_after_seconds: int
    task_reconcile_batch_size: int
    worker_preload_models: bool
    task_cleanup_enabled: bool
    succeeded_task_retention_days: int
    failed_task_retention_days: int
    task_archive_grace_days: int


def _build_settings() -> Settings:
    '''构建 Settings 实例，读取 .env 文件和环境变量'''
    _load_env_file(ENV_FILE)
    models_dir = _get_path("BTIR_MODELS_DIR", "models")
    device = validate_device(os.getenv("BTIR_DEVICE", "auto"))

    classifier_dir = models_dir / ModelName.CLASSIFICATION
    segmenter_dir = models_dir / ModelName.SEGMENTATION
    return Settings(
        project_root=PROJECT_ROOT,
        output_dir=_get_path("BTIR_OUTPUT_DIR", "output"),
        frontend_dir=_get_path("BTIR_FRONTEND_DIR", "frontend"),
        classifier_script=_get_path(
            "BTIR_CLASSIFIER_SCRIPT", str(classifier_dir / "inference.py")
        ),
        classifier_model=_get_path(
            "BTIR_CLASSIFIER_MODEL", str(classifier_dir / "model" / "pytorch_model.pth")
        ),
        classifier_config=_get_path(
            "BTIR_CLASSIFIER_CONFIG", str(classifier_dir / "model" / "config.json")
        ),
        segmenter_script=_get_path(
            "BTIR_SEGMENTER_SCRIPT", str(segmenter_dir / "inference.py")
        ),
        segmenter_model=_get_path(
            "BTIR_SEGMENTER_MODEL", str(segmenter_dir / "model" / "best_unet_model.pth")
        ),
        device=device,
        default_segment_threshold=_get_threshold(),
        max_upload_bytes=_get_positive_int(
            "BTIR_MAX_UPLOAD_BYTES",
            20 * 1024 * 1024,
        ),
        max_image_pixels=_get_positive_int(
            "BTIR_MAX_IMAGE_PIXELS",
            40_000_000,
        ),
        cors_origins=_get_origins(),
        redis_url=os.getenv(
            "BTIR_REDIS_URL",
            "redis://127.0.0.1:6379/0",
        ).strip(),
        task_lock_timeout_seconds=_get_positive_int(
            "BTIR_TASK_LOCK_TIMEOUT_SECONDS",
            30,
        ),
        task_lock_wait_seconds=_get_nonnegative_float(
            "BTIR_TASK_LOCK_WAIT_SECONDS",
            5.0,
        ),
        task_queue_name=os.getenv("BTIR_TASK_QUEUE_NAME", "inference").strip(),
        task_job_timeout_seconds=_get_positive_int(
            "BTIR_TASK_JOB_TIMEOUT_SECONDS",
            3600,
        ),
        task_job_result_ttl_seconds=_get_positive_int(
            "BTIR_TASK_JOB_RESULT_TTL_SECONDS",
            86400,
        ),
        task_job_max_retries=_get_nonnegative_int(
            "BTIR_TASK_JOB_MAX_RETRIES",
            1,
        ),
        task_stale_after_seconds=_get_positive_int(
            "BTIR_TASK_STALE_AFTER_SECONDS",
            3660,
        ),
        task_reconcile_batch_size=_get_positive_int(
            "BTIR_TASK_RECONCILE_BATCH_SIZE",
            100,
        ),
        worker_preload_models=_get_bool("BTIR_WORKER_PRELOAD_MODELS", True),
        task_cleanup_enabled=_get_bool("BTIR_TASK_CLEANUP_ENABLED", False),
        succeeded_task_retention_days=_get_nonnegative_int(
            "BTIR_SUCCEEDED_TASK_RETENTION_DAYS",
            30,
        ),
        failed_task_retention_days=_get_nonnegative_int(
            "BTIR_FAILED_TASK_RETENTION_DAYS",
            7,
        ),
        task_archive_grace_days=_get_nonnegative_int(
            "BTIR_TASK_ARCHIVE_GRACE_DAYS",
            7,
        ),
        task_database_path=_get_path(
            "BTIR_TASK_DATABASE_PATH",
            "data/btir.db",
        ),
        task_archive_dir=_get_path("BTIR_TASK_ARCHIVE_DIR", "archive"),
    )


SETTINGS = _build_settings()

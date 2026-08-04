'''项目运行配置的唯一入口'''

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from accelerator import validate_device


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = PROJECT_ROOT / ".env"
UNSAFE_DEFAULT_JWT_SECRET = "change-me-to-a-random-secret-in-production"


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
    '''获取布尔环境变量'''
    value = os.getenv(name, str(default)).strip().lower()
    if value in {"1", "true", "yes", "on"}:
        return True
    if value in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} 必须是 true 或 false")


def _get_linux_worker_mode() -> str:
    value = os.getenv("BTIR_LINUX_WORKER_MODE", "standard").strip().lower()
    if value not in {"standard", "simple"}:
        raise ValueError("BTIR_LINUX_WORKER_MODE 必须是 standard 或 simple")
    return value


def _get_nonnegative_float(name: str, default: float) -> float:
    '''获取float类型非负数'''
    value = float(os.getenv(name, str(default)))
    if value < 0:
        raise ValueError(f"{name} 不能小于 0")
    return value


def _get_bounded_float(name: str, default: float, *, minimum: float, maximum: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not minimum <= value <= maximum:
        raise ValueError(f"{name} 必须位于 [{minimum}, {maximum}]")
    return value


def _get_overlap(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 <= value < 1:
        raise ValueError(f"{name} 必须位于 [0, 1)")
    return value


def _get_fraction(name: str, default: float) -> float:
    value = float(os.getenv(name, str(default)))
    if not 0 < value <= 1:
        raise ValueError(f"{name} 必须位于 (0, 1]")
    return value


def _get_volume_classifier_modality() -> str:
    value = os.getenv("BTIR_3D_CLASSIFIER_MODALITY", "flair").strip().lower()
    allowed = {"flair", "t1ce", "t1", "t2"}
    if value not in allowed:
        raise ValueError(
            "BTIR_3D_CLASSIFIER_MODALITY 必须是 flair、t1ce、t1 或 t2"
        )
    return value


def _get_task_queue_name() -> str:
    queue_name = os.getenv("BTIR_TASK_QUEUE_NAME", "inference-3d").strip()
    if not queue_name:
        raise ValueError("BTIR_TASK_QUEUE_NAME 不能为空")
    return queue_name


@dataclass(frozen=True)
class Settings:
    '''由环境变量和 .env 文件构建的不可变运行配置'''

    project_root: Path
    output_dir: Path
    frontend_dir: Path
    segmenter_3d_script: Path
    segmenter_3d_model: Path
    segmenter_3d_overlap: float
    segmenter_3d_fast_inference: bool
    volume_classifier_modality: str
    vit_classifier_model_dir: Path
    vit_classifier_max_slices: int
    vit_classifier_batch_size: int
    vit_classifier_threshold: float
    task_database_path: Path
    task_archive_dir: Path
    device: str
    max_3d_upload_bytes: int
    max_3d_voxels: int
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
    linux_worker_mode: str
    task_cleanup_enabled: bool
    succeeded_task_retention_days: int
    failed_task_retention_days: int
    task_archive_grace_days: int
    jwt_secret_key: str
    jwt_expiration_hours: int
    jwt_algorithm: str
    registration_enabled: bool
    auth_login_user_attempts: int
    auth_login_ip_attempts: int
    auth_login_window_seconds: int
    auth_registration_ip_attempts: int
    auth_registration_window_seconds: int
    max_tasks_per_user: int
    max_active_tasks_per_user: int
    supplementary_analysis_enabled: bool
    deepseek_api_key: str
    deepseek_base_url: str
    deepseek_model: str
    supplementary_analysis_timeout_seconds: int
    supplementary_analysis_max_retries: int
    supplementary_analysis_max_tokens: int
    supplementary_analysis_temperature: float

def _build_settings() -> Settings:
    '''构建 Settings 实例，读取 .env 文件和环境变量'''
    _load_env_file(ENV_FILE)
    models_dir = _get_path("BTIR_MODELS_DIR", "models")
    device = validate_device(os.getenv("BTIR_DEVICE", "auto"))

    classifier_dir = models_dir / "classification"
    segmenter_3d_dir = models_dir / "segmentation3d"
    task_queue_name = _get_task_queue_name()
    return Settings(
        project_root=PROJECT_ROOT,
        output_dir=_get_path("BTIR_OUTPUT_DIR", "output"),
        frontend_dir=_get_path("BTIR_FRONTEND_DIR", "frontend"),
        segmenter_3d_script=_get_path(
            "BTIR_3D_SEGMENTER_SCRIPT",
            str(segmenter_3d_dir / "inference.py"),
        ),
        segmenter_3d_model=_get_path(
            "BTIR_3D_SEGMENTER_MODEL",
            str(segmenter_3d_dir / "model" / "model_epoch_297.pth"),
        ),
        segmenter_3d_overlap=_get_overlap("BTIR_3D_SEGMENTER_OVERLAP", 0.5),
        segmenter_3d_fast_inference=_get_bool(
            "BTIR_3D_FAST_INFERENCE",
            True,
        ),
        volume_classifier_modality=_get_volume_classifier_modality(),
        vit_classifier_model_dir=_get_path(
            "BTIR_VIT_CLASSIFIER_MODEL_DIR",
            str(classifier_dir / "vit-binary"),
        ),
        vit_classifier_max_slices=_get_positive_int(
            "BTIR_VIT_CLASSIFIER_MAX_SLICES",
            25,
        ),
        vit_classifier_batch_size=_get_positive_int(
            "BTIR_VIT_CLASSIFIER_BATCH_SIZE",
            25,
        ),
        vit_classifier_threshold=_get_fraction(
            "BTIR_VIT_CLASSIFIER_THRESHOLD",
            0.5,
        ),
        device=device,
        max_3d_upload_bytes=_get_positive_int(
            "BTIR_MAX_3D_UPLOAD_BYTES",
            512 * 1024 * 1024,
        ),
        max_3d_voxels=_get_positive_int(
            "BTIR_MAX_3D_VOXELS",
            20_000_000,
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
        task_queue_name=task_queue_name,
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
        linux_worker_mode=_get_linux_worker_mode(),
        task_cleanup_enabled=_get_bool("BTIR_TASK_CLEANUP_ENABLED", True),
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
        jwt_secret_key=os.getenv("BTIR_JWT_SECRET_KEY", "").strip(),
        jwt_expiration_hours=_get_positive_int("BTIR_JWT_EXPIRATION_HOURS", 24),
        jwt_algorithm=os.getenv("BTIR_JWT_ALGORITHM", "HS256").strip(),
        registration_enabled=_get_bool("BTIR_REGISTRATION_ENABLED", False),
        auth_login_user_attempts=_get_positive_int(
            "BTIR_AUTH_LOGIN_USER_ATTEMPTS",
            10,
        ),
        auth_login_ip_attempts=_get_positive_int(
            "BTIR_AUTH_LOGIN_IP_ATTEMPTS",
            60,
        ),
        auth_login_window_seconds=_get_positive_int(
            "BTIR_AUTH_LOGIN_WINDOW_SECONDS",
            300,
        ),
        auth_registration_ip_attempts=_get_positive_int(
            "BTIR_AUTH_REGISTRATION_IP_ATTEMPTS",
            5,
        ),
        auth_registration_window_seconds=_get_positive_int(
            "BTIR_AUTH_REGISTRATION_WINDOW_SECONDS",
            3600,
        ),
        max_tasks_per_user=_get_positive_int("BTIR_MAX_TASKS_PER_USER", 1000),
        max_active_tasks_per_user=_get_positive_int(
            "BTIR_MAX_ACTIVE_TASKS_PER_USER",
            2,
        ),
        supplementary_analysis_enabled=_get_bool(
            "BTIR_SUPPLEMENTARY_ANALYSIS_ENABLED",
            False,
        ),
        deepseek_api_key=os.getenv("BTIR_DEEPSEEK_API_KEY", "").strip(),
        deepseek_base_url=os.getenv(
            "BTIR_DEEPSEEK_BASE_URL",
            "https://api.deepseek.com",
        ).strip().rstrip("/"),
        deepseek_model=os.getenv(
            "BTIR_DEEPSEEK_MODEL",
            "deepseek-v4-flash",
        ).strip(),
        supplementary_analysis_timeout_seconds=_get_positive_int(
            "BTIR_SUPPLEMENTARY_ANALYSIS_TIMEOUT_SECONDS",
            20,
        ),
        supplementary_analysis_max_retries=_get_nonnegative_int(
            "BTIR_SUPPLEMENTARY_ANALYSIS_MAX_RETRIES",
            1,
        ),
        supplementary_analysis_max_tokens=_get_positive_int(
            "BTIR_SUPPLEMENTARY_ANALYSIS_MAX_TOKENS",
            700,
        ),
        supplementary_analysis_temperature=_get_bounded_float(
            "BTIR_SUPPLEMENTARY_ANALYSIS_TEMPERATURE",
            0.2,
            minimum=0.0,
            maximum=2.0,
        ),
    )


'''全局运行配置'''
SETTINGS = _build_settings()

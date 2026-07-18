'''项目运行配置的唯一入口'''

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from accelerator import validate_device


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
        "http://127.0.0.1:8000,http://localhost:8000",
    )
    return [origin.strip() for origin in raw_value.split(",") if origin.strip()]


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
    device: str
    default_segment_threshold: float
    cors_origins: list[str]


def _build_settings() -> Settings:
    '''构建 Settings 实例，读取 .env 文件和环境变量'''
    _load_env_file(ENV_FILE)
    models_dir = _get_path("BTIR_MODELS_DIR", "models")
    device = validate_device(os.getenv("BTIR_DEVICE", "auto"))

    classifier_dir = models_dir / "classification"
    segmenter_dir = models_dir / "segmentation"
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
        cors_origins=_get_origins(),
    )


SETTINGS = _build_settings()

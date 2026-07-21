'''模型推理性能基准；只使用临时输出，不创建任务或修改任务元数据'''

from __future__ import annotations

from pathlib import Path
from statistics import mean
from tempfile import TemporaryDirectory
from time import perf_counter
from typing import Any, Callable

from services.inference_service import classify, segment
from services.task_files import validate_image_path


def benchmark_models(
    image_path: Path,
    *,
    threshold: float,
    warm_runs: int,
) -> dict[str, Any]:
    '''测量当前 Python 进程中的首次与连续推理耗时'''
    if warm_runs < 1:
        raise ValueError("warm_runs 必须大于 0")
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold 必须位于 0 到 1 之间")

    image_path = validate_image_path(image_path)
    with TemporaryDirectory(prefix="btir-benchmark-") as temporary_dir:
        output_dir = Path(temporary_dir)
        return {
            "image_path": str(image_path),
            "warm_runs": warm_runs,
            "classification": _benchmark_operation(
                lambda: classify(image_path),
                warm_runs,
            ),
            "segmentation": _benchmark_operation(
                lambda: segment(image_path, threshold, output_dir),
                warm_runs,
            ),
        }


def _benchmark_operation(
    operation: Callable[[], object],
    warm_runs: int,
) -> dict[str, float | int]:
    '''先测一次当前进程的首次调用，再测连续调用的稳定耗时'''
    cold_seconds = _measure(operation)
    warm_seconds = [_measure(operation) for _ in range(warm_runs)]
    sorted_seconds = sorted(warm_seconds)
    p95_index = max(0, round((len(sorted_seconds) - 1) * 0.95))
    return {
        "cold_seconds": cold_seconds,
        "warm_mean_seconds": mean(warm_seconds),
        "warm_min_seconds": min(warm_seconds),
        "warm_p95_seconds": sorted_seconds[p95_index],
        "warm_runs": warm_runs,
    }


def _measure(operation: Callable[[], object]) -> float:
    started_at = perf_counter()
    operation()
    return perf_counter() - started_at

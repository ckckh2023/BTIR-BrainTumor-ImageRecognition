'''性能基准服务的无模型回归测试'''

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from services.benchmark_service import benchmark_models


class BenchmarkServiceTests(unittest.TestCase):
    '''验证基准使用临时输出并为两项模型生成统计结果'''

    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.image_path = Path(self.temporary_directory.name) / "image.png"
        self.image_path.write_bytes(b"image")

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def test_benchmark_measures_both_model_operations(self) -> None:
        with (
            patch("services.benchmark_service.classify", return_value={}) as classify,
            patch("services.benchmark_service.segment", return_value={}) as segment,
        ):
            result = benchmark_models(
                self.image_path,
                threshold=0.5,
                warm_runs=2,
            )

        self.assertEqual(classify.call_count, 3)
        self.assertEqual(segment.call_count, 3)
        self.assertEqual(result["classification"]["warm_runs"], 2)
        self.assertEqual(result["segmentation"]["warm_runs"], 2)

    def test_benchmark_rejects_invalid_run_count(self) -> None:
        with self.assertRaisesRegex(ValueError, "warm_runs"):
            benchmark_models(self.image_path, threshold=0.5, warm_runs=0)


if __name__ == "__main__":
    unittest.main()

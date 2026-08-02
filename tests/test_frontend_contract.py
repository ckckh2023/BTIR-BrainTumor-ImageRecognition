'''前端任务操作与 3D 结果展示的轻量契约回归测试'''

from pathlib import Path
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND_HTML = PROJECT_ROOT / "frontend" / "index.html"


class FrontendContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.html = FRONTEND_HTML.read_text(encoding="utf-8")

    def test_3d_result_does_not_render_an_outdated_hint(self) -> None:
        self.assertNotIn("当前 3D 路线仅提供分割与定量统计", self.html)
        self.assertNotIn('class="result-note"', self.html)

    def test_upload_flow_is_3d_only(self) -> None:
        self.assertIn("/tasks/3d", self.html)
        self.assertNotIn("analysisMode", self.html)
        self.assertNotIn("switchAnalysisMode", self.html)
        self.assertNotIn("image-viewer", self.html)
        self.assertNotIn(".jpg", self.html)

    def test_active_task_polling_is_fast_then_backs_off(self) -> None:
        self.assertIn("pollingStartedAt", self.html)
        self.assertIn("< 15_000 ? 500 : 1000", self.html)

    def test_task_manager_exposes_cancel_action(self) -> None:
        self.assertIn("canCancelTask(task.status)", self.html)
        self.assertIn("@click=\"cancelTask(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(task.task_id)}/cancel`", self.html)

    def test_task_manager_exposes_run_history(self) -> None:
        self.assertIn("@click=\"toggleTaskRunHistory(task)\"", self.html)
        self.assertIn("/${encodeURIComponent(taskId)}/runs?limit=20&offset=0`", self.html)
        self.assertIn("formatInferenceTime(run.inference_ms)", self.html)
        self.assertIn("value === null || value === undefined", self.html)


if __name__ == "__main__":
    unittest.main()

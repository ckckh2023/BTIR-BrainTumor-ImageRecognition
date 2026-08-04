'''浏览器端到端流程回归测试'''

from __future__ import annotations

from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Thread
import unittest
from urllib.parse import urlparse
import zipfile

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    sync_playwright = None


PROJECT_ROOT = Path(__file__).resolve().parents[1]
RUN_BROWSER_E2E = os.getenv("BTIR_RUN_BROWSER_E2E") == "1"


class _BrowserE2EHandler(SimpleHTTPRequestHandler):
    '''提供前端页面和可预测的本地测试接口'''

    request_counts: dict[str, int] = {}

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, directory=str(PROJECT_ROOT), **kwargs)

    def log_message(self, *_: object) -> None:
        return

    @classmethod
    def _count(cls, key: str) -> None:
        cls.request_counts[key] = cls.request_counts.get(key, 0) + 1

    def _send_json(self, payload: object, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    @staticmethod
    def _task_item(task_id: str, status: str) -> dict[str, object]:
        return {
            "task_id": task_id,
            "name": task_id,
            "status": status,
            "analysis_mode": "3d",
            "created_at": "2026-08-04T00:00:00+00:00",
            "input": {"files": {"flair": "flair.nii.gz"}},
        }

    @classmethod
    def _task_result(cls, task_id: str) -> dict[str, object]:
        input_files = {
            modality: f"{modality}.nii.gz"
            for modality in ("flair", "t1ce", "t1", "t2")
        }
        return {
            **cls._task_item(task_id, "succeeded"),
            "input": {"files": input_files},
            "frontend_result": {
                "task_id": task_id,
                "result_files": {
                    "frontend": "frontend_result.json",
                    "classification": "classification.json",
                    "segmentation": "segmentation.json",
                    "mask": "prediction.nii.gz",
                },
                "input_files": input_files,
                "classification": {"class": "yes", "confidence": 0.91},
                "segmentation": {
                    "mask_file": "prediction.nii.gz",
                    "regions": {"1": {"volume_mm3": 42, "ratio": 0.01}},
                },
            },
        }

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/auth/me":
            self._send_json({"user_id": "browser-e2e-user", "username": "browser_e2e"})
            return
        if path == "/tasks":
            self._send_json(
                {
                    "items": [
                        self._task_item("e2e-failed", "failed"),
                        self._task_item("e2e-running", "running"),
                    ],
                    "total": 2,
                }
            )
            return
        if path.startswith("/tasks/") and path.endswith("/runs"):
            self._send_json({"items": [], "total": 0, "limit": 20, "offset": 0})
            return
        if path.startswith("/tasks/") and "/files/" in path:
            self._count("file")
            body = b"browser-e2e-volume"
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/octet-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/tasks/"):
            self._count("task_status")
            self._send_json(self._task_result(path.rsplit("/", 1)[-1]))
            return
        if path == "/web/volume_viewer.js":
            body = (
                "window.BtirVolumeViewer=class{"
                "constructor(canvas){this.canvas=canvas}"
                "async load(){this.canvas.dataset.loaded='true'}"
                "setViewMode(){}setMaskOpacity(){}cleanup(){}}"
            ).encode("utf-8")
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", "application/javascript; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if path.startswith("/web/"):
            self.path = "/frontend/" + path.removeprefix("/web/")
        elif path.startswith("/login/"):
            self.path = "/frontend/" + path.removeprefix("/login/")
        return super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", "0"))
        if length:
            self.rfile.read(length)
        if path == "/auth/login":
            self._count("login")
            self._send_json(
                {
                    "access_token": "browser-e2e-token",
                    "user_id": "browser-e2e-user",
                    "username": "browser_e2e",
                }
            )
            return
        if path == "/tasks/3d/archive":
            self._count("upload")
            self._send_json({"task_id": "browser-upload-task"}, HTTPStatus.CREATED)
            return
        if path.endswith("/run-async"):
            self._count("run")
            self._send_json({"status": "queued", "job": {"id": "e2e-job"}})
            return
        if path.endswith("/retry"):
            self._count("retry")
            self._send_json({"status": "queued", "job": {"id": "retry-job"}})
            return
        if path.endswith("/cancel"):
            self._count("cancel")
            self._send_json({"task_id": "e2e-running", "status": "canceled"})
            return
        self.send_error(HTTPStatus.NOT_FOUND)


@unittest.skipUnless(
    sync_playwright is not None and RUN_BROWSER_E2E,
    "需要安装 Playwright 并设置 BTIR_RUN_BROWSER_E2E=1",
)
class BrowserE2ETests(unittest.TestCase):
    '''使用真实浏览器验证登录、上传、任务操作和三维查看'''

    @classmethod
    def setUpClass(cls) -> None:
        cls.temporary_directory = TemporaryDirectory()
        cls.archive_path = Path(cls.temporary_directory.name) / "case.zip"
        with zipfile.ZipFile(cls.archive_path, "w") as archive:
            archive.writestr("case_flair.nii.gz", b"browser-e2e")
        _BrowserE2EHandler.request_counts = {}
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), _BrowserE2EHandler)
        cls.server_thread = Thread(target=cls.server.serve_forever, daemon=True)
        cls.server_thread.start()
        cls.base_url = f"http://127.0.0.1:{cls.server.server_port}"
        cls.playwright = sync_playwright().start()
        cls.browser = cls.playwright.chromium.launch()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.browser.close()
        cls.playwright.stop()
        cls.server.shutdown()
        cls.server.server_close()
        cls.server_thread.join(timeout=5)
        cls.temporary_directory.cleanup()

    def setUp(self) -> None:
        self.page = self.browser.new_page()

    def tearDown(self) -> None:
        self.page.close()

    def _login(self) -> None:
        self.page.goto(f"{self.base_url}/login/login.html", wait_until="networkidle")
        self.page.get_by_test_id("login-username").fill("browser_e2e")
        self.page.get_by_test_id("login-password").fill("safe-browser-e2e-password")
        self.page.get_by_test_id("login-submit").click()
        self.page.wait_for_url(f"{self.base_url}/web/")
        self.page.wait_for_selector("[data-testid='volume-drop-zone']")

    def test_login_redirects_to_the_workspace(self) -> None:
        self._login()

        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("login", 0), 1)
        self.assertTrue(self.page.get_by_test_id("logout").is_visible())

    def test_archive_upload_runs_task_and_opens_3d_viewer(self) -> None:
        self._login()
        self.page.get_by_test_id("volume-archive-picker").set_input_files(
            str(self.archive_path)
        )
        start_button = self.page.get_by_test_id("start-analysis")
        self.assertTrue(start_button.is_enabled())
        start_button.click()
        self.page.wait_for_selector("[data-testid='volume-viewer-tab']")
        self.page.get_by_test_id("volume-viewer-tab").click()
        self.page.wait_for_selector("canvas[data-loaded='true']")

        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("upload", 0), 1)
        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("run", 0), 1)
        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("file", 0), 1)

    def test_task_manager_retries_and_cancels_tasks(self) -> None:
        self._login()
        self.page.on("dialog", lambda dialog: dialog.accept())
        self.page.get_by_test_id("task-manager-tab").click()
        self.page.wait_for_selector("[data-testid='task-retry-e2e-failed']")
        self.page.get_by_test_id("task-retry-e2e-failed").click()
        self.page.wait_for_timeout(100)
        self.page.get_by_test_id("task-cancel-e2e-running").click()
        self.page.wait_for_timeout(100)

        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("retry", 0), 1)
        self.assertGreaterEqual(_BrowserE2EHandler.request_counts.get("cancel", 0), 1)


if __name__ == "__main__":
    unittest.main()

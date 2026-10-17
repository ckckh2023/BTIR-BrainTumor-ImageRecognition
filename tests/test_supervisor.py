"""在隔离的 Bash 环境中验证 API 启动健康检查，不启动真实服务。"""

from pathlib import Path
import re
import shlex
import subprocess
from tempfile import TemporaryDirectory
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "run-supervisor.sh"


class SupervisorStartupTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        source = SCRIPT.read_text(encoding="utf-8")
        cls.start_api = re.search(
            r"^start_api\(\) \{\n.*?^\}", source, re.MULTILINE | re.DOTALL
        ).group()
        cls.output_helpers = "\n".join(
            re.search(rf"^{name}\(\) \{{\n.*?^\}}", source, re.MULTILINE | re.DOTALL).group()
            for name in ("show_access_urls", "component_label", "report_readiness")
        )
        start = source.index('    if [[ "$health_checks_enabled" == true')
        end = source.index('    if [[ "$now" -ge "$next_task_reconcile" ]]', start)
        cls.health_check = "check_health() {\n" + source[start:end] + "}\n"

    def run_scenario(self, scenario: str) -> str:
        with TemporaryDirectory() as directory:
            harness = "\n".join([
                "set -Eeuo pipefail",
                f"PROJECT_ROOT={shlex.quote(directory)}",
                'LOG_DIRECTORY="$PROJECT_ROOT"',
                "PYTHON_EXE=/bin/true",
                "API_HOST=127.0.0.1 API_PORT=8000",
                "HEALTH_BASE_URL=http://127.0.0.1:8000",
                "API_STARTUP_GRACE_SECONDS=30 HEALTH_CHECK_SECONDS=15",
                "API_FAILURE_THRESHOLD=3 WORKER_STARTUP_GRACE_SECONDS=120",
                "health_checks_enabled=true worker_started_at=100",
                "api_pid=0 api_health_failures=0 api_startup_pending=false",
                "clock=100 now=100 next_health_check=100 api_status=000 restart_count=0",
                'date() { printf "%s\\n" "$clock"; }',
                'log() { printf "%s\\n" "$*"; }',
                'http_status() { printf "%s" "$api_status"; }',
                'http_body() { printf \'{"redis":"ok","inference_worker":"ok"}\'; }',
                'hostname() { printf "192.168.1.20 127.0.0.1\\n"; }',
                "restart_worker() { return 1; }",
                self.output_helpers,
                self.start_api,
                "restart_api() { restart_count=$((restart_count + 1)); start_api; wait \"$api_pid\"; }",
                self.health_check,
                'start_api; wait "$api_pid"',
                scenario,
            ])
            result = subprocess.run(
                ["bash"], input=harness, text=True, capture_output=True, timeout=5
            )
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            return result.stdout

    def test_initial_connection_failures_do_not_count_during_startup(self) -> None:
        output = self.run_scenario("""
            check_health
            now=115 clock=115 api_status=503
            check_health
            [[ "$api_health_failures" == 0 && "$restart_count" == 0 ]]
            [[ "$api_startup_pending" == true ]]
        """)
        self.assertNotIn("health check failed", output)

    def test_startup_prints_browser_addresses(self) -> None:
        output = self.run_scenario(":")
        self.assertIn("网页入口: http://127.0.0.1:8000/web/", output)
        self.assertIn("登录 / 注册: http://127.0.0.1:8000/web/login.html", output)
        self.assertIn("5500", output)

    def test_loopback_binding_does_not_advertise_network_access(self) -> None:
        output = self.run_scenario("show_access_urls")
        self.assertNotIn("网络地址:", output)

    def test_wildcard_binding_prints_network_addresses(self) -> None:
        output = self.run_scenario("API_HOST=0.0.0.0; show_access_urls")
        self.assertIn("网络地址: http://192.168.1.20:8000/web/", output)

    def test_component_status_is_updated_only_when_it_changes(self) -> None:
        output = self.run_scenario("""
            pending='{"detail":{"status":"not_ready","components":{"task_database":"ok","redis":"ok","inference_worker":"unavailable","models":"ok"}}}'
            ready='{"status":"ready","components":{"task_database":"ok","redis":"ok","inference_worker":"ok","models":"ok"}}'
            report_readiness "$pending"
            report_readiness "$pending"
            report_readiness "$ready"
            report_readiness "$ready"
        """)
        self.assertEqual(output.count("正在准备:"), 1)
        self.assertIn("Worker 等待", output)
        self.assertEqual(output.count("服务全部就绪"), 1)

    def test_first_success_ends_grace_and_later_failure_counts_immediately(self) -> None:
        output = self.run_scenario("""
            api_status=200
            check_health
            [[ "$api_startup_pending" == false ]]
            now=115 clock=115 api_status=000
            check_health
            [[ "$api_health_failures" == 1 ]]
        """)
        self.assertEqual(output.count("API is ready"), 1)
        self.assertIn("API health check failed (failures=1)", output)

    def test_persistently_unhealthy_api_restarts_after_grace_and_threshold(self) -> None:
        output = self.run_scenario("""
            for moment in 130 145 160; do
                now="$moment" clock="$moment"
                check_health
            done
            [[ "$restart_count" == 1 && "$api_health_failures" == 0 ]]
            [[ "$api_startup_pending" == true && "$api_started_at" == 160 ]]
        """)
        self.assertEqual(output.count("API health check failed"), 3)

    def test_restarting_resets_the_startup_deadline_and_failure_counter(self) -> None:
        output = self.run_scenario("""
            api_status=200
            check_health
            api_health_failures=2
            clock=200
            start_api
            wait "$api_pid"
            now=200 api_status=000
            check_health
            [[ "$api_health_failures" == 0 && "$restart_count" == 0 ]]
            [[ "$api_started_at" == 200 && "$api_startup_pending" == true ]]
        """)
        self.assertNotIn("health check failed", output)


if __name__ == "__main__":
    unittest.main()

'''在隔离目录中验证守护脚本的实时输出、重启和退出行为'''

from __future__ import annotations

import os
import importlib.util
from io import StringIO
from pathlib import Path
import select
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch


CONSOLE_PATH = Path(__file__).resolve().parents[1] / "scripts" / "supervisor_console.py"
spec = importlib.util.spec_from_file_location("supervisor_console", CONSOLE_PATH)
console_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(console_module)


class ConsoleDisplayTests(unittest.TestCase):
    def test_redirected_output_is_plain_and_filters_routine_logs(self) -> None:
        stream = StringIO()
        console = console_module.Console(stream)
        console.worker_event("Worker started with PID 123")
        console.worker_event("*** Listening on inference-3d...")
        console.worker_event("INFO: GET /healthz HTTP/1.1 200 OK")
        self.assertEqual(stream.getvalue(), "")
        console.worker_event("[推理进程] 任务推理进度 任务=case-1 作业=job-1 进度=50.375% 阶段=3D 分割推理中")
        console.worker_event("[推理进程] 任务推理完成 任务=case-1 作业=job-1")
        console.draw()
        self.assertIn("50% · 3D 分割推理中", stream.getvalue())
        self.assertNotIn("50.375%", stream.getvalue())
        self.assertIn("任务推理完成：case-1", stream.getvalue())
        self.assertNotIn("\033", stream.getvalue())
        self.assertNotIn("\r", stream.getvalue())

    def test_interactive_spinner_cycles_without_adding_lines(self) -> None:
        stream = StringIO()
        stream.isatty = lambda: True
        with patch.dict(os.environ, {"TERM": "xterm", "COLUMNS": "100"}):
            console = console_module.Console(stream)
            console.set_status("正在等待服务就绪")
            for _ in range(4):
                console.draw()
        output = stream.getvalue()
        for frame in ("-", "\\", "|", "/"):
            self.assertIn(f"{frame} 正在等待服务就绪", output)
        self.assertNotIn("\n", output)

    def test_idle_service_event_does_not_hide_active_task(self) -> None:
        stream = StringIO()
        console = console_module.Console(stream)
        console.worker_event("任务推理进度 任务=case-1 作业=job-1 进度=50% 阶段=分割中")
        console.supervisor_event("[守护进程] [状态] 运行中")
        self.assertIn("50%", console.status)


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux supervisor")
class SupervisorOutputTests(unittest.TestCase):
    def test_spinner_in_a_real_terminal(self) -> None:
        import pty

        with tempfile.TemporaryDirectory(prefix="btir-console-") as directory:
            root = Path(directory)
            events = root / "events"
            events.write_text("[守护进程] [状态] 正在等待服务就绪\n")
            master, slave = pty.openpty()
            process = subprocess.Popen(
                [sys.executable, str(CONSOLE_PATH), str(events), str(root), str(os.getpid()), "0", "0"],
                stdout=slave,
                stderr=subprocess.PIPE,
                env={**os.environ, "TERM": "xterm", "COLUMNS": "120"},
            )
            os.close(slave)
            output = b""
            try:
                deadline = time.monotonic() + 3
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([master], [], [], 0.2)
                    if readable:
                        output += os.read(master, 65536)
                    if all(f"{frame} 正在等待服务就绪".encode() in output for frame in ("-", "\\", "|", "/")):
                        break
                for frame in ("-", "\\", "|", "/"):
                    self.assertIn(f"{frame} 正在等待服务就绪", output.decode())
            finally:
                process.terminate()
                _, errors = process.communicate(timeout=5)
                os.close(master)
            self.assertEqual(process.returncode, 0, errors.decode())

    def test_live_output_preserves_restart_and_shutdown(self) -> None:
        self._exercise_supervisor()

    def test_missing_models_exposes_web_address_without_claiming_ready(self) -> None:
        self._exercise_supervisor(missing_models=True)

    def test_preflight_failure_is_visible_and_stops_console(self) -> None:
        self._exercise_supervisor(fail_dependencies=True)

    def _exercise_supervisor(self, *, missing_models=False, fail_dependencies=False) -> None:
        with tempfile.TemporaryDirectory(prefix="btir-supervisor-") as directory:
            root = Path(directory)
            (root / "scripts").mkdir()
            script = root / "scripts" / "run-supervisor.sh"
            shutil.copyfile(
                Path(__file__).resolve().parents[1] / "scripts" / script.name,
                script,
            )
            shutil.copyfile(CONSOLE_PATH, root / "scripts" / CONSOLE_PATH.name)
            (root / "Main.py").touch()
            python = root / "python"
            python.write_text(
                f"#!{sys.executable}\n"
                "import os, pathlib, sys, time\n"
                "args = sys.argv[1:]\n"
                "if len(args) > 1 and args[1].endswith('supervisor_console.py'):\n"
                "    os.execv(sys.executable, [sys.executable, *args])\n"
                "if '-c' in args:\n"
                "    if 'import fastapi' in args[1] and os.getenv('BTIR_TEST_FAIL_DEPENDENCIES'):\n"
                "        print('dependency traceback detail', file=sys.stderr)\n"
                "        raise SystemExit(1)\n"
                "    raise SystemExit(1 if 'connect_ex' in args[1] else 0)\n"
                "assert args[0] == '-u', args\n"
                "role = 'worker' if 'workers.run_worker' in args else 'api'\n"
                "pathlib.Path(f'{role}.pid').write_text(str(os.getpid()))\n"
                "print(f'{role} stdout ready', flush=True)\n"
                "print(f'{role} stderr ready', file=sys.stderr, flush=True)\n"
                "if role == 'worker':\n"
                "    print('任务推理进度 任务=case-1 作业=job-1 进度=50% 阶段=3D 分割推理中', flush=True)\n"
                "    marker = pathlib.Path('worker-restarted')\n"
                "    if not marker.exists():\n"
                "        marker.touch()\n"
                "        time.sleep(0.4)\n"
                "        raise SystemExit(7)\n"
                "while True: time.sleep(0.1)\n",
                encoding="utf-8",
            )
            python.chmod(0o755)
            curl = root / "curl"
            curl.write_text(
                '#!/bin/sh\ncase "$*" in\n'
                '  *readyz*) if [ -n "$BTIR_TEST_MISSING_MODELS" ]; then\n'
                '    printf \'{"detail":{"status":"not_ready","components":{"redis":"ok","inference_worker":"ok","models":"unavailable"}}}\'\n'
                '    else printf \'{"status":"ready","components":{"redis":"ok","inference_worker":"ok"}}\'; fi ;;\n'
                '  *) if [ ! -f health-checked ]; then touch health-checked; printf 000; else printf 200; fi ;;\nesac\n',
                encoding="utf-8",
            )
            curl.chmod(0o755)
            environment = {
                **os.environ,
                "PATH": f"{root}:{os.environ['PATH']}",
                "BTIR_SUPERVISOR_RESTART_DELAY_SECONDS": "1",
                "BTIR_SUPERVISOR_SHUTDOWN_GRACE_SECONDS": "1",
                "BTIR_API_HOST": "0.0.0.0",
                "BTIR_API_PORT": "8000",
                "BTIR_SUPERVISOR_API_STARTUP_GRACE_SECONDS": "60",
                "BTIR_TEST_FAIL_DEPENDENCIES": "1" if fail_dependencies else "",
                "BTIR_TEST_MISSING_MODELS": "1" if missing_models else "",
            }
            process = subprocess.Popen(
                ["bash", str(script), str(python)],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                env=environment,
                cwd=root,
            )
            output = b""
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    readable, _, _ = select.select([process.stdout], [], [], 0.2)
                    if readable:
                        chunk = os.read(process.stdout.fileno(), 65536)
                        if not chunk:
                            break
                        output += chunk
                    expected_status = "等待推理服务：模型文件" if missing_models else "服务已就绪"
                    if output.count("50% · 3D 分割推理中".encode()) >= 2 and expected_status.encode() in output:
                        break
                text = output.decode("utf-8")
                if fail_dependencies:
                    self.assertIn("项目依赖不完整，请执行", text)
                    self.assertNotIn("dependency traceback detail", text)
                    self.assertFalse((root / "api.pid").exists())
                    self.assertFalse((root / "worker.pid").exists())
                    child_pids = []
                else:
                    self._assert_running_output(text, missing_models)
                    child_pids = [int((root / f"{role}.pid").read_text()) for role in ("api", "worker")]
            finally:
                process.terminate()
                try:
                    remaining, _ = process.communicate(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    for pid_file in root.glob("*.pid"):
                        try:
                            os.kill(int(pid_file.read_text()), 9)
                        except ProcessLookupError:
                            pass
                    remaining, _ = process.communicate(timeout=5)
                output += remaining

            self.assertEqual(process.returncode, 2 if fail_dependencies else 0, output.decode("utf-8"))
            self.assertIn("守护进程已停止", output.decode("utf-8"))
            self.assertFalse((root / "logs" / "supervisor.pid").exists())
            self.assertEqual(list((root / "logs").glob(".console.*")), [])
            for pid in child_pids:
                with self.assertRaises(ProcessLookupError):
                    os.kill(pid, 0)
            if fail_dependencies:
                self.assertIn("dependency traceback detail", (root / "logs" / "startup.log").read_text())
                return
            for role in ("api", "worker"):
                for stream in ("stdout", "stderr"):
                    log = (root / "logs" / f"{role}.{stream}.log").read_text()
                    self.assertIn(f"{role} {stream} ready", log)
            self.assertIn(
                "进度=50% 阶段=3D 分割推理中",
                (root / "logs" / "worker.stdout.log").read_text(),
            )

    def _assert_running_output(self, text: str, missing_models: bool) -> None:
        self.assertGreaterEqual(text.count("50% · 3D 分割推理中"), 2, text)
        for stage in range(1, 5):
            self.assertIn(f"[{stage}/4]", text)
        self.assertNotIn("api stdout ready", text)
        self.assertNotIn("api stderr ready", text)
        self.assertNotIn("worker stderr ready", text)
        self.assertNotIn("API 健康检查失败", text)
        self.assertIn("http://127.0.0.1:8000/web/", text)
        self.assertIn("http://127.0.0.1:8000/docs", text)
        if missing_models:
            self.assertNotIn("服务已就绪", text)
            self.assertIn("等待推理服务：模型文件", text)
        else:
            self.assertIn("服务已就绪", text)
        self.assertNotIn("\033", text)
        self.assertIn("退出码=7", text)
        self.assertIn("正在检查项目依赖", text)
        self.assertIn("正在启动 3D 推理进程", text)


if __name__ == "__main__":
    unittest.main()

'''终端状态输出回归测试'''

from __future__ import annotations

from io import StringIO
import unittest

from services.console import ConsoleProgress, print_event


class ConsoleOutputTests(unittest.TestCase):
    def test_non_interactive_progress_is_plain_text(self) -> None:
        stream = StringIO()
        progress = ConsoleProgress(stream, width=4)

        progress.update("分类推理中", 0)
        progress.update("分类完成，开始分割", 50)
        progress.update("推理完成", 100)

        output = stream.getvalue()
        self.assertIn("[----]   0% 分类推理中", output)
        self.assertIn("[##--]  50% 分类完成，开始分割", output)
        self.assertIn("[####] 100% 推理完成", output)
        self.assertNotIn("\033[", output)

    def test_non_interactive_event_is_plain_text(self) -> None:
        stream = StringIO()

        print_event("worker 已启动", level="success", stream=stream)

        self.assertEqual(stream.getvalue(), "[BTIR] OK worker 已启动\n")

'''终端扫瘤核心逻辑的回归测试'''

from __future__ import annotations

import random
import unittest

from services.terminal_game import (
    GameDifficulty,
    Minefield,
    ThreatController,
    ThreatLine,
    _colored_cell_symbol,
    _elapsed_seconds,
)


class _CrossingRandom:
    def choice(self, values):  # type: ignore[no-untyped-def]
        return values[0]

    def random(self) -> float:
        return 0.0

    def uniform(self, lower: float, upper: float) -> float:
        return lower


class MinefieldTests(unittest.TestCase):
    def setUp(self) -> None:
        self.difficulty = GameDifficulty("test", "测试", 3, 3, 1)

    def test_revealing_a_zero_cell_expands_the_safe_region(self) -> None:
        minefield = Minefield(self.difficulty, {(0, 0)}, set(), set())

        hit_mine = minefield.reveal((2, 2))

        self.assertFalse(hit_mine)
        self.assertTrue(minefield.is_won)
        self.assertNotIn((0, 0), minefield.revealed)

    def test_flagged_cell_is_not_revealed(self) -> None:
        minefield = Minefield(self.difficulty, {(0, 0)}, set(), set())
        minefield.toggle_flag((1, 1))

        hit_mine = minefield.reveal((1, 1))

        self.assertFalse(hit_mine)
        self.assertNotIn((1, 1), minefield.revealed)
        self.assertIn((1, 1), minefield.flagged)

    def test_revealing_a_mine_reports_failure(self) -> None:
        minefield = Minefield(self.difficulty, {(0, 0)}, set(), set())

        self.assertTrue(minefield.reveal((0, 0)))

    def test_game_first_scan_creates_a_safe_opening(self) -> None:
        difficulty = GameDifficulty("game", "游戏", 5, 5, 3)
        minefield = Minefield.create(difficulty, rng=random.Random(1))

        hit_mine = minefield.reveal((1, 1))

        self.assertFalse(hit_mine)
        self.assertEqual(minefield.adjacent_mine_count((1, 1)), 0)
        self.assertGreater(len(minefield.revealed), 1)

    def test_second_scan_reveals_another_covered_safe_cell(self) -> None:
        minefield = Minefield(self.difficulty, {(0, 0)}, set(), set())
        minefield.reveal((1, 1))
        target = (2, 2)

        minefield.reveal(target)

        self.assertIn(target, minefield.revealed)

    def test_timer_does_not_start_before_the_first_action(self) -> None:
        self.assertEqual(_elapsed_seconds(None), 0.0)

    def test_colored_symbols_fall_back_to_plain_text_without_a_terminal(self) -> None:
        minefield = Minefield(self.difficulty, {(0, 0)}, set(), {(1, 1)})

        self.assertEqual(_colored_cell_symbol(minefield, (1, 1), reveal_mines=False), "!")

    def test_threat_line_enters_and_leaves_the_board(self) -> None:
        line = ThreatLine("horizontal", 1, -2, 1, 3)

        self.assertEqual(line.cells(self.difficulty), {(1, 0)})
        line.move()
        self.assertEqual(line.cells(self.difficulty), {(1, 0), (1, 1)})
        self.assertFalse(line.has_left_board(self.difficulty))

        line.offset = self.difficulty.columns
        self.assertTrue(line.has_left_board(self.difficulty))

    def test_threat_controller_waits_for_first_action_then_spawns_away_from_cursor(self) -> None:
        controller = ThreatController(self.difficulty, random.Random(1))

        self.assertFalse(controller.advance(10.0, (0, 0)))
        controller.begin(10.0)
        self.assertFalse(controller.advance(13.9, (0, 0)))
        self.assertTrue(controller.advance(14.0, (0, 0)))
        self.assertTrue(controller.active_cells)
        self.assertNotIn((0, 0), controller.active_cells)

    def test_hard_difficulty_can_spawn_crossing_threat_lines(self) -> None:
        hard_difficulty = GameDifficulty("3", "困难", 8, 8, 10)
        controller = ThreatController(hard_difficulty, _CrossingRandom())
        controller.begin(10.0)

        controller.advance(13.0, (0, 0))

        self.assertEqual(len(controller.active_lines), 2)
        self.assertEqual(
            {line.orientation for line in controller.active_lines},
            {"horizontal", "vertical"},
        )

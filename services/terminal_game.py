'''BTIR 终端扫瘤小游戏'''

from __future__ import annotations

from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
import os
import random
import shutil
import sys
from time import perf_counter, sleep
from typing import Callable, Iterator


Coordinate = tuple[int, int]

_RESET = "\033[0m"
_CELL_COLORS = {
    "hidden": "\033[90m",
    "flag": "\033[33m",
    "mine": "\033[31m",
    "empty": "\033[37m",
    "one": "\033[36m",
    "two": "\033[32m",
    "many": "\033[35m",
    "danger": "\033[91m",
}


@dataclass(frozen=True)
class GameDifficulty:
    key: str
    name: str
    rows: int
    columns: int
    mine_count: int


DIFFICULTIES = {
    "1": GameDifficulty("1", "简单", 8, 8, 10),
    "2": GameDifficulty("2", "普通", 12, 12, 24),
    "3": GameDifficulty("3", "困难", 16, 16, 48),
}


@dataclass
class ThreatLine:
    '''让玩家在扫描区域中移动的红色扫描线'''

    orientation: str
    fixed_index: int
    offset: int
    step: int
    length: int

    def cells(self, difficulty: GameDifficulty) -> set[Coordinate]:
        limit = difficulty.columns if self.orientation == "horizontal" else difficulty.rows
        cells: set[Coordinate] = set()
        for moving_index in range(self.offset, self.offset + self.length):
            if not 0 <= moving_index < limit:
                continue
            if self.orientation == "horizontal":
                cells.add((self.fixed_index, moving_index))
            else:
                cells.add((moving_index, self.fixed_index))
        return cells

    def move(self) -> None:
        self.offset += self.step

    def has_left_board(self, difficulty: GameDifficulty) -> bool:
        limit = difficulty.columns if self.orientation == "horizontal" else difficulty.rows
        return self.offset >= limit if self.step > 0 else self.offset + self.length <= 0


@dataclass(frozen=True)
class ThreatProfile:
    max_active_lines: int
    first_spawn_delay_seconds: float
    spawn_delay_range: tuple[float, float]
    move_interval_seconds: float
    line_length: int
    cross_spawn_chance: float = 0.0


THREAT_PROFILES = {
    "1": ThreatProfile(1, 5.5, (5.0, 7.0), 0.48, 3),
    "2": ThreatProfile(2, 4.0, (3.2, 5.0), 0.34, 3),
    "3": ThreatProfile(3, 3.0, (2.0, 3.5), 0.24, 4, cross_spawn_chance=0.45),
}


@dataclass
class ThreatController:
    '''控制红色扫描线的生成和移动'''

    difficulty: GameDifficulty
    rng: random.Random
    active_lines: list[ThreatLine] = field(default_factory=list)
    next_spawn_at: float | None = None
    next_move_at: float | None = None

    @property
    def profile(self) -> ThreatProfile:
        return THREAT_PROFILES.get(self.difficulty.key, THREAT_PROFILES["2"])

    @property
    def active_line(self) -> ThreatLine | None:
        '''返回最靠近玩家的扫描线'''
        return self.active_lines[0] if self.active_lines else None

    def begin(self, now: float) -> None:
        if self.next_spawn_at is None:
            self.next_spawn_at = now + self.profile.first_spawn_delay_seconds

    @property
    def active_cells(self) -> set[Coordinate]:
        return {
            cell
            for line in self.active_lines
            for cell in line.cells(self.difficulty)
        }

    def advance(self, now: float, cursor: Coordinate) -> bool:
        '''让扫描线前进；返回是否需要重新渲染'''
        if self.next_spawn_at is None:
            return False
        changed = False
        if (
            now >= self.next_spawn_at
            and len(self.active_lines) < self.profile.max_active_lines
        ):
            available_slots = self.profile.max_active_lines - len(self.active_lines)
            self.active_lines.extend(self._new_spawn_away_from(cursor)[:available_slots])
            self.next_spawn_at = now + self.rng.uniform(*self.profile.spawn_delay_range)
            self.next_move_at = self.next_move_at or now + self.profile.move_interval_seconds
            changed = True

        while self.next_move_at is not None and now >= self.next_move_at:
            for line in self.active_lines:
                line.move()
            self.next_move_at += self.profile.move_interval_seconds
            changed = True

        remaining_lines = [
            line
            for line in self.active_lines
            if not line.has_left_board(self.difficulty)
        ]
        if len(remaining_lines) != len(self.active_lines):
            self.active_lines = remaining_lines
            changed = True
        if not self.active_lines:
            self.next_move_at = None
        return changed

    def _new_spawn_away_from(self, cursor: Coordinate) -> list[ThreatLine]:
        orientation = self.rng.choice(("horizontal", "vertical"))
        lines = [self._new_line_away_from(cursor, orientation)]
        if self.rng.random() < self.profile.cross_spawn_chance:
            other_orientation = "vertical" if orientation == "horizontal" else "horizontal"
            lines.append(self._new_line_away_from(cursor, other_orientation))
        return lines

    def _new_line_away_from(
        self,
        cursor: Coordinate,
        orientation: str,
    ) -> ThreatLine:
        moving_limit = (
            self.difficulty.columns if orientation == "horizontal" else self.difficulty.rows
        )
        blocked_index = cursor[0] if orientation == "horizontal" else cursor[1]
        fixed_choices = [index for index in range(
            self.difficulty.rows if orientation == "horizontal" else self.difficulty.columns
        ) if index != blocked_index]
        fixed_index = self.rng.choice(fixed_choices)
        step = self.rng.choice((-1, 1))
        length = min(self.profile.line_length, moving_limit)
        offset = -length + 1 if step > 0 else moving_limit - 1
        return ThreatLine(orientation, fixed_index, offset, step, length)


@dataclass
class Minefield:
    difficulty: GameDifficulty
    mines: set[Coordinate]
    revealed: set[Coordinate]
    flagged: set[Coordinate]
    protect_first_scan: bool = False

    @classmethod
    def create(
        cls,
        difficulty: GameDifficulty,
        *,
        rng: random.Random | None = None,
    ) -> "Minefield":
        rng = rng or random.Random()
        cells = [
            (row, column)
            for row in range(difficulty.rows)
            for column in range(difficulty.columns)
        ]
        return cls(
            difficulty,
            set(rng.sample(cells, difficulty.mine_count)),
            set(),
            set(),
            protect_first_scan=True,
        )

    def reveal(self, cell: Coordinate) -> bool:
        '''扫描一个位置；返回是否扫到了异常信号'''
        if cell in self.flagged:
            return cell in self.mines
        if cell in self.revealed:
            return self._chord_reveal(cell)
        if self.protect_first_scan and not self.revealed:
            self._create_first_scan_opening(cell)
        if cell in self.mines:
            self.revealed.add(cell)
            return True
        self._reveal_safe_region(cell)
        return False

    def toggle_flag(self, cell: Coordinate) -> None:
        if cell in self.revealed:
            return
        if cell in self.flagged:
            self.flagged.remove(cell)
        else:
            self.flagged.add(cell)

    def adjacent_mine_count(self, cell: Coordinate) -> int:
        return sum(neighbor in self.mines for neighbor in self._neighbors(cell))

    @property
    def is_won(self) -> bool:
        safe_cells = self.difficulty.rows * self.difficulty.columns - len(self.mines)
        return len(self.revealed - self.mines) == safe_cells

    def _reveal_safe_region(self, start: Coordinate) -> None:
        pending = deque([start])
        while pending:
            cell = pending.popleft()
            if cell in self.revealed or cell in self.flagged or cell in self.mines:
                continue
            self.revealed.add(cell)
            if self.adjacent_mine_count(cell) == 0:
                pending.extend(self._neighbors(cell))

    def _create_first_scan_opening(self, cell: Coordinate) -> None:
        protected_cells = {cell, *self._neighbors(cell)}
        mines_to_move = self.mines & protected_cells
        if not mines_to_move:
            return
        available_cells = [
            candidate
            for row in range(self.difficulty.rows)
            for column in range(self.difficulty.columns)
            if (candidate := (row, column)) not in protected_cells
            and candidate not in self.mines
        ]
        if len(available_cells) < len(mines_to_move):
            return
        self.mines.difference_update(mines_to_move)
        self.mines.update(random.sample(available_cells, len(mines_to_move)))

    def _chord_reveal(self, cell: Coordinate) -> bool:
        neighbors = self._neighbors(cell)
        expected_flags = self.adjacent_mine_count(cell)
        if expected_flags == 0 or sum(neighbor in self.flagged for neighbor in neighbors) != expected_flags:
            return False
        hit_mine = False
        for neighbor in neighbors:
            if neighbor in self.flagged or neighbor in self.revealed:
                continue
            if neighbor in self.mines:
                self.revealed.add(neighbor)
                hit_mine = True
            else:
                self._reveal_safe_region(neighbor)
        return hit_mine

    def _neighbors(self, cell: Coordinate) -> list[Coordinate]:
        row, column = cell
        return [
            (next_row, next_column)
            for next_row in range(max(0, row - 1), min(self.difficulty.rows, row + 2))
            for next_column in range(
                max(0, column - 1), min(self.difficulty.columns, column + 2)
            )
            if (next_row, next_column) != cell
        ]


def run_game() -> int:
    '''启动终端小游戏；无交互终端时拒绝启动'''
    if not sys.stdin.isatty() or not sys.stdout.isatty():
        print("[BTIR] game 需要在交互终端中运行")
        return 2

    while True:
        difficulty = _choose_difficulty()
        if difficulty is None:
            return 0
        if _play_round(difficulty):
            return 0


def _choose_difficulty() -> GameDifficulty | None:
    difficulties = list(DIFFICULTIES.values())
    selected_index = 0
    with _single_key_mode() as read_key:
        while True:
            _render_difficulty_menu(difficulties, selected_index)
            key = read_key()
            if key == "UP":
                selected_index = (selected_index - 1) % len(difficulties)
            elif key == "DOWN":
                selected_index = (selected_index + 1) % len(difficulties)
            elif key == "ENTER":
                return difficulties[selected_index]
            elif key == "ESC":
                return None


def _render_difficulty_menu(
    difficulties: list[GameDifficulty],
    selected_index: int,
) -> None:
    _clear_screen()
    print("BTIR · 扫瘤\n")
    print("↑/↓ 选择难度，Enter 确认，Esc 返回\n")
    for index, difficulty in enumerate(difficulties):
        cursor = ">" if index == selected_index else " "
        print(
            f"{cursor} {difficulty.name:<2}  "
            f"{difficulty.rows}x{difficulty.columns} / {difficulty.mine_count} 个异常信号"
        )


def _play_round(difficulty: GameDifficulty) -> bool:
    minefield = Minefield.create(difficulty)
    threats = ThreatController(difficulty, random.Random())
    cursor = (0, 0)
    started_at: float | None = None
    result = ""
    exited = False

    needs_render = True
    last_rendered_second = -1
    with _single_key_mode() as read_key:
        while not result:
            now = perf_counter()
            if threats.advance(now, cursor):
                needs_render = True
            if cursor in threats.active_cells:
                result = "触碰到红色扫描线，任务失败"
                continue
            elapsed_second = int(_elapsed_seconds(started_at))
            if needs_render or elapsed_second != last_rendered_second:
                _render(
                    minefield,
                    cursor,
                    started_at,
                    threat_lines=tuple(threats.active_lines),
                )
                needs_render = False
                last_rendered_second = elapsed_second

            key = _read_key_with_timeout(read_key, 0.1)
            if key is None:
                continue
            needs_render = True
            if key == "ESC":
                result = "已退出本局"
                exited = True
            elif key in {"UP", "w", "W"}:
                started_at = _begin_round(started_at, threats)
                cursor = (max(0, cursor[0] - 1), cursor[1])
            elif key in {"DOWN", "s", "S"}:
                started_at = _begin_round(started_at, threats)
                cursor = (min(difficulty.rows - 1, cursor[0] + 1), cursor[1])
            elif key in {"LEFT", "a", "A"}:
                started_at = _begin_round(started_at, threats)
                cursor = (cursor[0], max(0, cursor[1] - 1))
            elif key in {"RIGHT", "d", "D"}:
                started_at = _begin_round(started_at, threats)
                cursor = (cursor[0], min(difficulty.columns - 1, cursor[1] + 1))
            elif key in {"k", "K"}:
                started_at = _begin_round(started_at, threats)
                minefield.toggle_flag(cursor)
            elif key in {"j", "J"}:
                started_at = _begin_round(started_at, threats)
                if minefield.reveal(cursor):
                    result = "扫描到异常信号，任务失败"
                elif minefield.is_won:
                    result = "扫描完成，安全区域已确认"

            if cursor in threats.active_cells:
                result = "触碰到红色扫描线，任务失败"

    elapsed = _elapsed_seconds(started_at)
    if exited:
        _render(
            minefield,
            cursor,
            started_at,
            reveal_mines=True,
            elapsed_override=elapsed,
        )
        print(f"\n{result} 用时 {elapsed:.1f}s。")
        return True

    for remaining_seconds in range(3, 0, -1):
        _render(
            minefield,
            cursor,
            started_at,
            reveal_mines=True,
            elapsed_override=elapsed,
        )
        print(f"\n{result} 用时 {elapsed:.1f}s。")
        print(f"{remaining_seconds} 秒后返回难度选择")
        sleep(1)
    return exited


def _render(
    minefield: Minefield,
    cursor: Coordinate,
    started_at: float | None,
    *,
    reveal_mines: bool = False,
    elapsed_override: float | None = None,
    threat_lines: tuple[ThreatLine, ...] = (),
) -> None:
    elapsed = _elapsed_seconds(started_at) if elapsed_override is None else elapsed_override
    lines = [
        f"BTIR · 扫瘤 · {minefield.difficulty.name}  "
        f"标记: {len(minefield.flagged)}/{minefield.difficulty.mine_count}  用时: {elapsed:.0f}s"
    ]
    lines.append("J 扫描 | K 标记 | Esc 退出")
    lines.append(_board_border(minefield.difficulty.columns, "┌", "┐"))
    for row in range(minefield.difficulty.rows):
        cells = []
        for column in range(minefield.difficulty.columns):
            cell = (row, column)
            cells.append(
                _render_board_cell(
                    minefield,
                    cell,
                    cursor=cursor,
                    reveal_mines=reveal_mines,
                    threat_lines=threat_lines,
                )
            )
        lines.append("│" + "".join(cells) + "│")
    lines.append(_board_border(minefield.difficulty.columns, "└", "┘"))
    _draw_game_frame(lines, minimum_columns=max(70, minefield.difficulty.columns * 3 + 2))


def _begin_round(
    started_at: float | None,
    threats: ThreatController,
) -> float:
    if started_at is not None:
        return started_at
    started_at = perf_counter()
    threats.begin(started_at)
    return started_at


def _board_border(columns: int, left: str, right: str) -> str:
    return left + "───" * columns + right


def _render_board_cell(
    minefield: Minefield,
    cell: Coordinate,
    *,
    cursor: Coordinate,
    reveal_mines: bool,
    threat_lines: tuple[ThreatLine, ...],
) -> str:
    threat_line = next(
        (line for line in threat_lines if cell in line.cells(minefield.difficulty)),
        None,
    )
    if threat_line is not None:
        symbol = "━━━" if threat_line.orientation == "horizontal" else " ┃ "
        return _colored_text(symbol, "danger")
    symbol = _colored_cell_symbol(minefield, cell, reveal_mines=reveal_mines)
    return f"[{symbol}]" if cell == cursor else f" {symbol} "


def _cell_symbol(
    minefield: Minefield,
    cell: Coordinate,
    *,
    reveal_mines: bool,
) -> str:
    if cell in minefield.flagged:
        return "!"
    if cell in minefield.mines and reveal_mines:
        return "X"
    if cell not in minefield.revealed:
        return "#"
    if cell in minefield.mines:
        return "X"
    return str(minefield.adjacent_mine_count(cell) or " ")


def _colored_cell_symbol(
    minefield: Minefield,
    cell: Coordinate,
    *,
    reveal_mines: bool,
) -> str:
    symbol = _cell_symbol(minefield, cell, reveal_mines=reveal_mines)
    if not _supports_terminal_color():
        return symbol
    if cell in minefield.flagged:
        color = _CELL_COLORS["flag"]
    elif cell in minefield.mines and (reveal_mines or cell in minefield.revealed):
        color = _CELL_COLORS["mine"]
    elif cell not in minefield.revealed:
        color = _CELL_COLORS["hidden"]
    elif symbol == " ":
        color = _CELL_COLORS["empty"]
    elif symbol == "1":
        color = _CELL_COLORS["one"]
    elif symbol == "2":
        color = _CELL_COLORS["two"]
    else:
        color = _CELL_COLORS["many"]
    return f"{color}{symbol}{_RESET}"


def _colored_text(text: str, color_name: str) -> str:
    if not _supports_terminal_color():
        return text
    return f"{_CELL_COLORS[color_name]}{text}{_RESET}"


def _clear_screen() -> None:
    '''清屏并将渲染光标放回窗口左上角'''
    sys.stdout.write("\033[2J\033[H")
    sys.stdout.flush()


def _draw_game_frame(lines: list[str], *, minimum_columns: int) -> None:
    '''在终端中渲染游戏画面；如果终端太窄或不支持交互，则直接打印文本'''
    terminal_columns = shutil.get_terminal_size(fallback=(0, 0)).columns
    if not sys.stdout.isatty() or terminal_columns < minimum_columns:
        _clear_screen()
        print("\n".join(lines))
        return

    sys.stdout.write("\033[H")
    for line in lines:
        sys.stdout.write("\033[2K")
        sys.stdout.write(line)
        sys.stdout.write("\n")
    sys.stdout.write("\033[J")
    sys.stdout.flush()


def _supports_terminal_color() -> bool:
    return (
        not os.getenv("NO_COLOR")
        and os.getenv("TERM") != "dumb"
        and bool(getattr(sys.stdout, "isatty", lambda: False)())
    )


def _elapsed_seconds(started_at: float | None) -> float:
    return 0.0 if started_at is None else perf_counter() - started_at


def _read_key_with_timeout(
    read_key: Callable[[], str],
    timeout_seconds: float,
) -> str | None:
    '''等待按键或超时，以便计时器无需等待用户操作也能刷新'''
    if os.name == "nt":
        import msvcrt

        deadline = perf_counter() + timeout_seconds
        while perf_counter() < deadline:
            if msvcrt.kbhit():
                return read_key()
            sleep(0.01)
        return None

    import select

    return read_key() if select.select([sys.stdin], [], [], timeout_seconds)[0] else None


@contextmanager
def _single_key_mode() -> Iterator[Callable[[], str]]:
    if os.name == "nt":
        import msvcrt

        def read_windows_key() -> str:
            key = msvcrt.getwch()
            if key not in {"\x00", "\xe0"}:
                if key in {"\r", "\n"}:
                    return "ENTER"
                return "ESC" if key == "\x1b" else key
            return {
                "H": "UP",
                "P": "DOWN",
                "K": "LEFT",
                "M": "RIGHT",
            }.get(msvcrt.getwch(), "")

        yield read_windows_key
        return

    import select
    import termios
    import tty

    file_descriptor = sys.stdin.fileno()
    previous_settings = termios.tcgetattr(file_descriptor)
    try:
        tty.setcbreak(file_descriptor)

        def read_posix_key() -> str:
            key = sys.stdin.read(1)
            if key != "\x1b":
                return "ENTER" if key in {"\r", "\n"} else key
            if not select.select([sys.stdin], [], [], 0.05)[0]:
                return "ESC"
            return {
                "[A": "UP",
                "[B": "DOWN",
                "[D": "LEFT",
                "[C": "RIGHT",
            }.get(sys.stdin.read(2), "")

        yield read_posix_key
    finally:
        termios.tcsetattr(file_descriptor, termios.TCSADRAIN, previous_settings)

# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - A whole SMEMA line in memory: upstream conveyor, the cell, downstream conveyor
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""Boards travel from an upstream conveyor through the cell to a downstream conveyor, tick by tick (evidence: simulator).

`SmemaLine` moves boards the way the two SMEMA cables allow: the upstream conveyor releases a board only while the cell
asserts `machine ready`, the downstream conveyor accepts one only while the cell asserts `board available` and the
downstream asserts `machine ready`. The real receiver and sender of the bridge drive the lines through the gate; the neighbours,
the placing time and the cables are simulated, so nothing here says anything about a real conveyor or a 12-24 V cable.
"""

from __future__ import annotations

import unittest

from hydra_umc_sdk.bridge_contract import CellState, MachineState
from hydra_umc_bridge_openpnp import SimulatedSmemaNeighbour, SmemaReceiver, SmemaSender

NO_SLEEP = lambda seconds: None  # noqa: E731


class SmemaLine:
    def __init__(self, boards: int, placing_ticks: int = 3) -> None:
        self.upstream_boards = boards
        self.upstream = SimulatedSmemaNeighbour(board_available=boards > 0)
        self.downstream = SimulatedSmemaNeighbour(machine_ready=True)
        self.receiver = SmemaReceiver(self.upstream.board_available_line(), self.upstream.output(), sleep=NO_SLEEP)
        self.sender = SmemaSender(self.downstream.output(), self.downstream.machine_ready_line(), sleep=NO_SLEEP)
        self.placing_ticks = placing_ticks
        self.cell_state = CellState.READY
        self.fixture: str = "empty"  # empty | placing | staged
        self._left = 0
        self.delivered = 0
        self.log: list[str] = []
        self.violations: list[str] = []

    @property
    def machine_state(self) -> MachineState:
        return MachineState.RUNNING if self.fixture == "placing" else MachineState.IDLE

    def tick(self) -> None:
        # the boards move against the levels the cell set at the end of the previous tick
        if self.receiver.may_take_board() and self.fixture == "empty":
            self.upstream_boards -= 1
            self.upstream.board_available = self.upstream_boards > 0
            self.fixture, self._left = "placing", self.placing_ticks
            self.log.append("board taken")
        elif self.fixture == "placing":
            self._left -= 1
            if self._left <= 0:
                self.fixture = "staged"
                self.log.append("board staged")
        elif self.fixture == "staged" and self.sender.may_deliver_board():
            self.fixture = "empty"
            self.delivered += 1
            self.log.append("board delivered")
        # then the cell tells its neighbours what it can do now, and withdraws what is no longer true
        observed = self.machine_state
        self.receiver.reconcile(self.cell_state, observed, fixture_empty=self.fixture == "empty")
        self.sender.reconcile(self.cell_state, observed, board_staged=self.fixture == "staged")
        self.receiver.set_ready(self.fixture == "empty", self.cell_state, observed, fixture_empty=self.fixture == "empty")
        self.sender.offer(self.fixture == "staged", self.cell_state, observed, board_staged=self.fixture == "staged")
        self._check_invariants()

    def _check_invariants(self) -> None:
        if self.receiver.asserted and self.fixture != "empty":
            self.violations.append("machine ready asserted with the fixture occupied")
        if self.receiver.asserted and self.machine_state is MachineState.RUNNING:
            self.violations.append("machine ready asserted while the machine runs")
        if self.sender.asserted and self.fixture != "staged":
            self.violations.append("board available asserted without a staged board")
        if (self.receiver.asserted or self.sender.asserted) and self.cell_state is not CellState.READY:
            self.violations.append("an output is up while the cell is not ready")

    def run(self, ticks: int) -> None:
        for _ in range(ticks):
            self.tick()


class SmemaLineTests(unittest.TestCase):
    def test_every_board_goes_through_in_order_and_no_invariant_breaks(self) -> None:
        line = SmemaLine(boards=4)
        line.run(60)
        self.assertEqual((line.delivered, line.upstream_boards), (4, 0))
        self.assertEqual(line.violations, [])
        self.assertEqual(line.log[:3], ["board taken", "board staged", "board delivered"])

    def test_a_downstream_machine_that_stalls_holds_the_board_and_stops_taking_more(self) -> None:
        line = SmemaLine(boards=3)
        line.downstream.machine_ready = False
        line.run(30)
        self.assertEqual(line.delivered, 0)
        self.assertEqual(line.fixture, "staged")
        self.assertEqual(line.upstream_boards, 2)  # no second board was taken while the first waits
        self.assertFalse(line.receiver.asserted)
        line.downstream.machine_ready = True
        line.run(60)
        self.assertEqual(line.delivered, 3)
        self.assertEqual(line.violations, [])

    def test_the_cell_stopping_in_the_middle_withdraws_both_outputs_and_recovery_resumes(self) -> None:
        line = SmemaLine(boards=3)
        line.run(5)
        line.cell_state = CellState.SAFE_STOP
        line.run(10)
        self.assertFalse(line.receiver.asserted or line.sender.asserted)
        taken_before = line.upstream_boards
        line.run(10)
        self.assertEqual(line.upstream_boards, taken_before)  # nothing moves while stopped
        line.cell_state = CellState.READY
        line.run(80)
        self.assertEqual(line.delivered + (1 if line.fixture != "empty" else 0) + line.upstream_boards, 3)
        self.assertEqual(line.violations, [])

    def test_a_bouncing_upstream_signal_is_never_taken_as_a_board(self) -> None:
        line = SmemaLine(boards=2)
        line.upstream.bounce = True
        line.run(20)
        self.assertEqual(line.upstream_boards, 2)
        self.assertEqual(line.delivered, 0)

    def test_an_unreadable_upstream_line_takes_nothing(self) -> None:
        line = SmemaLine(boards=2)
        line.upstream.fail_reads = True
        line.run(20)
        self.assertEqual(line.upstream_boards, 2)

    def test_an_unwritable_machine_ready_line_never_lets_a_board_in(self) -> None:
        line = SmemaLine(boards=2)
        line.upstream.fail_writes = True
        line.run(20)
        self.assertEqual(line.upstream_boards, 2)
        self.assertFalse(line.receiver.asserted)

    def test_an_unwritable_board_available_line_keeps_the_board_in_the_cell(self) -> None:
        line = SmemaLine(boards=1)
        line.downstream.fail_writes = True
        line.run(30)
        self.assertEqual(line.delivered, 0)
        self.assertEqual(line.fixture, "staged")

    def test_the_outputs_are_never_up_while_the_machine_is_running(self) -> None:
        line = SmemaLine(boards=3, placing_ticks=6)
        for _ in range(50):
            line.tick()
            if line.machine_state is MachineState.RUNNING:
                self.assertEqual((line.receiver.asserted, line.sender.asserted), (False, False))


if __name__ == "__main__":
    unittest.main()

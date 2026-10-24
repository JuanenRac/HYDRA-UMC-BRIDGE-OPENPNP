# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - SMEMA board hand-over signals
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
"""The SMEMA handshake between the cell and its neighbours on an SMT line, with the cell's safety rules on its outputs.

SMEMA (IPC-SMEMA-9851) is how SMT machines tell each other that a board can pass: the machine upstream asserts
``board available`` when it has a board to give, the machine downstream asserts ``machine ready`` when it can take one, and
the board moves when both are asserted. A HYDRA-UMC arm that loads and unloads a pick-and-place machine takes part in the same
conversation, so that it works in a real line instead of beside it:

- ``SmemaReceiver``: the cell takes boards from an upstream machine. It READS ``board available`` and DRIVES ``machine ready``.
- ``SmemaSender``: the cell gives boards to a downstream machine. It DRIVES ``board available`` and READS ``machine ready``.

Reading a signal is free of risk. DRIVING one tells another machine that a board may move, so it is a control action and goes
through the shared gate: an output is asserted only for a READY cell and a machine that was OBSERVED idle (a state nobody
read is not a state), and only while the caller states that the fixture is empty (to receive) or that a finished board is
staged (to give). Withdrawing an output is always allowed, ``reconcile`` withdraws any output whose condition has stopped
being true, and a line that cannot be written leaves the outputs withdrawn: the safe state of an SMEMA output is "not ready".

The lines are small protocols (``read`` / ``write``), so everything is tested against ``SimulatedSmemaNeighbour``; the one
place that imports libgpiod is ``open_smema_gpio``. SMEMA signals are dry contacts or opto-isolated 12 to 24 V: the CM5's
3.3 V pins need an interface board, which is a wiring matter and not decided here.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

from hydra_umc_sdk.bridge_contract import BridgeJob, CellState, JobPhase, MachineState, evaluate_job

__all__ = [
    "InputLine",
    "OutputLine",
    "SmemaDecision",
    "SmemaReceiver",
    "SmemaSender",
    "SimulatedSmemaNeighbour",
    "open_smema_gpio",
]

DEFAULT_SAMPLES = 3
DEFAULT_SAMPLE_INTERVAL_S = 0.005


class InputLine(Protocol):
    def read(self) -> bool:
        """True when the signal is ASSERTED (the polarity of the wiring is the line's business, not the logic's)."""
        ...


class OutputLine(Protocol):
    def write(self, asserted: bool) -> None: ...


@dataclass(frozen=True)
class SmemaDecision:
    """What was asked of an output, what was done and why."""

    allowed: bool
    asserted: bool
    reason: str


def stable_read(line: InputLine, samples: int = DEFAULT_SAMPLES, interval_s: float = DEFAULT_SAMPLE_INTERVAL_S, sleep: Callable[[float], None] = time.sleep) -> bool:
    """A debounced reading: asserted only when every sample says so; a line that bounces, or cannot be read, is not asserted."""

    try:
        for index in range(samples):
            if line.read() is not True:
                return False
            if index + 1 < samples:
                sleep(interval_s)
    except Exception:  # noqa: BLE001 - a line that cannot be read is a signal that is not there
        return False
    return True


def _gate(cell_state: CellState, observed: MachineState | None, phase: JobPhase) -> tuple[bool, str]:
    """The shared gate for asserting an output: a READY cell and a machine that was observed idle."""

    if observed is None:
        return False, "the state of the machine was not read: an SMEMA output is not asserted on a claim"
    job = BridgeJob("smema-output", "smema-output", "smema", phase, observed, {})
    decision = evaluate_job(job, cell_state, observed)
    return decision.allowed, decision.reason


class _Outputs:
    """The common part: an output that is only ever asserted through the gate and is withdrawn whenever it cannot be trusted."""

    def __init__(self, output: OutputLine) -> None:
        self._output = output
        self._asserted = False

    @property
    def asserted(self) -> bool:
        return self._asserted

    def _drive(self, asserted: bool) -> bool:
        """Write the line; True when it is now at the level asked for.

        A write that fails leaves the output as it was, except that a failed attempt to ASSERT tries to put the line at its
        withdrawn level; if that cannot be written either, the output is assumed asserted (it may be), never withdrawn.
        """
        try:
            self._output.write(asserted)
        except Exception:  # noqa: BLE001
            if asserted:
                try:
                    self._output.write(False)
                    self._asserted = False
                except Exception:  # noqa: BLE001 - nothing more can be done for a line that cannot be written
                    self._asserted = True
            return False
        self._asserted = asserted
        return True

    def withdraw(self) -> SmemaDecision:
        """Withdraw the output. Always allowed: not-ready is the safe state."""
        if self._drive(False):
            return SmemaDecision(True, False, "the output is withdrawn")
        return SmemaDecision(True, self._asserted, "the output could not be written and may still be asserted")


class SmemaReceiver(_Outputs):
    """The cell takes boards from an upstream machine: reads its ``board available``, drives ``machine ready``."""

    def __init__(
        self,
        board_available: InputLine,
        machine_ready: OutputLine,
        *,
        samples: int = DEFAULT_SAMPLES,
        interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(machine_ready)
        self._board_available = board_available
        self._samples, self._interval, self._sleep = samples, interval_s, sleep

    def board_waiting(self) -> bool:
        """The upstream machine has a board for the cell (debounced)."""
        return stable_read(self._board_available, self._samples, self._interval, self._sleep)

    def set_ready(self, ready: bool, cell_state: CellState, observed: MachineState | None, *, fixture_empty: bool) -> SmemaDecision:
        """Tell the upstream machine that the cell can take a board (or that it cannot).

        Asserted only for a READY cell, a machine observed idle and an empty fixture; ``ready=False`` is always honoured.
        """

        if not ready:
            return self.withdraw()
        allowed, reason = _gate(cell_state, observed, JobPhase.LOAD)
        if allowed and fixture_empty is not True:
            allowed, reason = False, "the fixture is not empty: the cell cannot take another board"
        if not allowed:
            return SmemaDecision(False, self.withdraw().asserted, reason)
        if not self._drive(True):
            return SmemaDecision(False, self._asserted, "the machine ready line could not be written; it stays withdrawn")
        return SmemaDecision(True, True, "machine ready is asserted: the cell can take a board")

    def may_take_board(self) -> bool:
        """The arm may take the board from the upstream conveyor: the cell said ready and the upstream machine has a board."""
        return self._asserted and self.board_waiting()

    def reconcile(self, cell_state: CellState, observed: MachineState | None, *, fixture_empty: bool) -> bool:
        """Withdraw the output if what allowed it is no longer true; returns True when it had to."""
        if not self._asserted:
            return False
        allowed, _ = _gate(cell_state, observed, JobPhase.LOAD)
        if allowed and fixture_empty is True:
            return False
        self.withdraw()
        return True


class SmemaSender(_Outputs):
    """The cell gives boards to a downstream machine: drives ``board available``, reads its ``machine ready``."""

    def __init__(
        self,
        board_available: OutputLine,
        machine_ready: InputLine,
        *,
        samples: int = DEFAULT_SAMPLES,
        interval_s: float = DEFAULT_SAMPLE_INTERVAL_S,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        super().__init__(board_available)
        self._machine_ready = machine_ready
        self._samples, self._interval, self._sleep = samples, interval_s, sleep

    def downstream_ready(self) -> bool:
        """The downstream machine can take a board (debounced)."""
        return stable_read(self._machine_ready, self._samples, self._interval, self._sleep)

    def offer(self, available: bool, cell_state: CellState, observed: MachineState | None, *, board_staged: bool) -> SmemaDecision:
        """Tell the downstream machine that a finished board is ready to leave (or that none is).

        Asserted only for a READY cell, a machine observed idle and a board that is staged; ``available=False`` is always honoured.
        """

        if not available:
            return self.withdraw()
        allowed, reason = _gate(cell_state, observed, JobPhase.UNLOAD)
        if allowed and board_staged is not True:
            allowed, reason = False, "no finished board is staged: there is nothing to offer"
        if not allowed:
            return SmemaDecision(False, self.withdraw().asserted, reason)
        if not self._drive(True):
            return SmemaDecision(False, self._asserted, "the board available line could not be written; it stays withdrawn")
        return SmemaDecision(True, True, "board available is asserted: a finished board can leave")

    def may_deliver_board(self) -> bool:
        """The arm may put the board on the downstream conveyor: the cell offered it and the downstream machine is ready."""
        return self._asserted and self.downstream_ready()

    def reconcile(self, cell_state: CellState, observed: MachineState | None, *, board_staged: bool) -> bool:
        if not self._asserted:
            return False
        allowed, _ = _gate(cell_state, observed, JobPhase.UNLOAD)
        if allowed and board_staged is True:
            return False
        self.withdraw()
        return True


# --- a neighbour machine that exists only in memory ---------------------------------------------------------------------


@dataclass
class SimulatedSmemaNeighbour:
    """The other side of an SMEMA cable: it holds the level of each signal and records what the cell wrote.

    ``bounce`` makes the read signal flicker the way a dirty contact does; ``fail_writes`` makes the cell's output unwritable.
    """

    board_available: bool = False  # what an upstream neighbour asserts
    machine_ready: bool = False  # what a downstream neighbour asserts
    output_level: bool = False  # what the cell last wrote to its output
    writes: list[bool] = field(default_factory=list)
    bounce: bool = False
    fail_reads: bool = False
    fail_writes: bool = False
    _toggle: bool = False

    def board_available_line(self) -> InputLine:
        return _Reader(self, "board_available")

    def machine_ready_line(self) -> InputLine:
        return _Reader(self, "machine_ready")

    def output(self) -> OutputLine:
        return _Writer(self)


class _Reader:
    def __init__(self, neighbour: SimulatedSmemaNeighbour, name: str) -> None:
        self._neighbour, self._name = neighbour, name

    def read(self) -> bool:
        if self._neighbour.fail_reads:
            raise OSError("line cannot be read")
        value = getattr(self._neighbour, self._name)
        if self._neighbour.bounce:
            self._neighbour._toggle = not self._neighbour._toggle  # noqa: SLF001
            return value and self._neighbour._toggle  # noqa: SLF001
        return value


class _Writer:
    def __init__(self, neighbour: SimulatedSmemaNeighbour) -> None:
        self._neighbour = neighbour

    def write(self, asserted: bool) -> None:
        if self._neighbour.fail_writes and asserted:
            raise OSError("line cannot be written")
        self._neighbour.writes.append(asserted)
        self._neighbour.output_level = asserted


# --- the real lines ---------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class _GpiodInput:
    request: object
    offset: int
    active_low: bool

    def read(self) -> bool:
        from gpiod.line import Value  # type: ignore[import-not-found]

        active = self.request.get_value(self.offset) == Value.ACTIVE  # type: ignore[attr-defined]
        return (not active) if self.active_low else active


@dataclass(frozen=True)
class _GpiodOutput:
    request: object
    offset: int
    active_low: bool

    def write(self, asserted: bool) -> None:
        from gpiod.line import Value  # type: ignore[import-not-found]

        level = (not asserted) if self.active_low else asserted
        self.request.set_value(self.offset, Value.ACTIVE if level else Value.INACTIVE)  # type: ignore[attr-defined]


def open_smema_gpio(
    chip_path: str,
    *,
    input_offset: int,
    output_offset: int,
    input_active_low: bool = False,
    output_active_low: bool = False,
    consumer: str = "hydra-umc-bridge-openpnp-smema",
) -> tuple[InputLine, OutputLine]:
    """Request one input line and one output line of a GPIO chip with libgpiod v2. The only place gpiod is imported, lazily.

    The output is requested already at its WITHDRAWN level, so that the cell never starts a line saying "ready". The lines
    are those of an interface board, not the 3.3 V pins of the CM5 wired straight to a 24 V cable.
    """

    try:
        import gpiod  # type: ignore[import-not-found]
        from gpiod.line import Bias, Direction, Value  # type: ignore[import-not-found]
    except ImportError as error:
        raise RuntimeError("libgpiod (python gpiod v2) is not installed - install it to use the SMEMA lines") from error
    withdrawn = Value.ACTIVE if output_active_low else Value.INACTIVE
    request = gpiod.request_lines(
        chip_path,
        consumer=consumer,
        config={
            input_offset: gpiod.LineSettings(direction=Direction.INPUT, bias=Bias.PULL_UP if input_active_low else Bias.PULL_DOWN),
            output_offset: gpiod.LineSettings(direction=Direction.OUTPUT, output_value=withdrawn),
        },
    )
    return _GpiodInput(request, input_offset, input_active_low), _GpiodOutput(request, output_offset, output_active_low)

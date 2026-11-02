# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - tests for choosing the SMEMA lines from the environment
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
#
# The real lines (libgpiod) are replaced by a recorder: nothing here has touched a GPIO chip.
# =============================================================================
import unittest

from hydra_umc_sdk.bridge_contract import CellState, MachineState
from hydra_umc_bridge_openpnp import SimulatedSmemaNeighbour, SmemaConfigError, smema_from_environment, smema_mode_from_environment

NO_SLEEP = lambda seconds: None  # noqa: E731
P = "HYDRA_UMC_OPENPNP_SMEMA"


class Recorder:
    def __init__(self):
        self.calls = []
        self.neighbour = SimulatedSmemaNeighbour()

    def __call__(self, chip, **kwargs):
        self.calls.append((chip, kwargs))
        return self.neighbour.board_available_line(), self.neighbour.output()


class ModeTests(unittest.TestCase):
    def test_it_is_off_unless_asked_for(self):
        self.assertEqual(smema_mode_from_environment({}), "off")
        self.assertEqual(smema_from_environment({}), (None, None))
        self.assertEqual(smema_from_environment({P: "off"}), (None, None))

    def test_an_unknown_mode_is_refused(self):
        with self.assertRaises(SmemaConfigError):
            smema_mode_from_environment({P: "on"})


class SimulatedTests(unittest.TestCase):
    def test_simulated_builds_both_roles_without_hardware(self):
        receiver, sender = smema_from_environment({P: "simulated"})
        self.assertIsNotNone(receiver)
        self.assertIsNotNone(sender)
        self.assertFalse(receiver.board_waiting())

    def test_a_neighbour_can_be_driven_by_the_caller(self):
        up = SimulatedSmemaNeighbour()
        receiver, sender = smema_from_environment({P: "simulated", P + "_RECEIVER_INPUT": "1", P + "_RECEIVER_OUTPUT": "2"}, simulated_neighbours={"receiver": up})
        self.assertIsNone(sender)
        up.board_available = True
        self.assertTrue(receiver.board_waiting())
        # an output only goes up through the shared gate
        self.assertFalse(receiver.set_ready(True, CellState.INHIBITED, MachineState.IDLE, fixture_empty=True).asserted)
        self.assertTrue(receiver.set_ready(True, CellState.READY, MachineState.IDLE, fixture_empty=True).asserted)
        self.assertEqual(up.writes[-1], True)


class GpioTests(unittest.TestCase):
    ENV = {P: "gpio", P + "_CHIP": "/dev/gpiochip0", P + "_RECEIVER_INPUT": "5", P + "_RECEIVER_OUTPUT": "6", P + "_SENDER_INPUT": "13", P + "_SENDER_OUTPUT": "19"}

    def test_each_role_opens_its_two_lines(self):
        opener = Recorder()
        receiver, sender = smema_from_environment({**self.ENV, P + "_OUTPUT_ACTIVE_LOW": "1"}, open_gpio=opener)
        self.assertIsNotNone(receiver)
        self.assertIsNotNone(sender)
        self.assertEqual(
            opener.calls,
            [
                ("/dev/gpiochip0", {"input_offset": 5, "output_offset": 6, "input_active_low": False, "output_active_low": True}),
                ("/dev/gpiochip0", {"input_offset": 13, "output_offset": 19, "input_active_low": False, "output_active_low": True}),
            ],
        )

    def test_one_role_alone_is_enough(self):
        opener = Recorder()
        env = {k: v for k, v in self.ENV.items() if "SENDER" not in k}
        receiver, sender = smema_from_environment(env, open_gpio=opener)
        self.assertIsNotNone(receiver)
        self.assertIsNone(sender)
        self.assertEqual(len(opener.calls), 1)

    def test_a_wiring_mistake_is_refused_before_any_line_is_opened(self):
        opener = Recorder()
        bad = [
            {k: v for k, v in self.ENV.items() if k != P + "_CHIP"},
            {k: v for k, v in self.ENV.items() if k != P + "_RECEIVER_OUTPUT"},
            {P: "gpio", P + "_CHIP": "c"},
            {**self.ENV, P + "_SENDER_INPUT": "5"},  # a line used twice
            {**self.ENV, P + "_RECEIVER_INPUT": "x"},
            {**self.ENV, P + "_RECEIVER_INPUT": "-1"},
        ]
        for env in bad:
            with self.assertRaises(SmemaConfigError, msg=str(env)):
                smema_from_environment(env, open_gpio=opener)
        self.assertEqual(opener.calls, [])


if __name__ == "__main__":
    unittest.main()

# =============================================================================
# HYDRA-UMC-BRIDGE-OPENPNP - The board event is a QoS 1 publish of the SDK
# Copyright (C) 2026 JuanenRac (Electro Hobby 3D) <electrohobby3d@gmail.com>
# GPL-3.0-or-later - see LICENSE
# =============================================================================
import unittest

from hydra_umc_sdk.bridge_transport import MqttPublish

from hydra_umc_bridge_openpnp.traceability import EventPublish


class EventPublishTests(unittest.TestCase):
    def test_an_event_is_a_qos_one_publish_of_the_sdk(self) -> None:
        event = EventPublish("t", "p")
        self.assertEqual(event.qos, 1)
        self.assertFalse(event.retain)
        self.assertEqual(event, MqttPublish("t", "p", False, 1))
        self.assertEqual(EventPublish("t", "p", qos=2).qos, 2)
        with self.assertRaises(ValueError):
            EventPublish("t", "p", qos=3)


if __name__ == "__main__":
    unittest.main()

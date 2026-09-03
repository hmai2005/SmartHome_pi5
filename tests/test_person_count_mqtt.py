import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from smart_home_ai.pipeline import ApplicationComponents, process_frame


class FakeGateway:
    def __init__(self):
        self.config = SimpleNamespace(person_count_topic="smart-home/ai/person_count")
        self.published = []

    def publish_json(self, topic, payload, *, retain):
        self.published.append((topic, payload, retain))


class PersonCountMqttTests(unittest.TestCase):
    @patch("smart_home_ai.pipeline.track_people_in_frame", return_value=[])
    def test_stable_person_count_is_published_only_when_changed(self, _track):
        gateway = FakeGateway()
        components = ApplicationComponents(
            model=None,
            capture=None,
            occupancy=SimpleNamespace(update=lambda **kwargs: 2),
            fan=SimpleNamespace(
                update=lambda **kwargs: 0,
                fuzzy_score=0.0,
                desired_fan_level=0,
                mode="auto",
            ),
            temperature_reader=SimpleNamespace(read_celsius=lambda: 25.0),
            actuator=SimpleNamespace(set_level=lambda level: None),
            gateway=gateway,
        )

        process_frame(np.zeros((10, 10, 3), dtype=np.uint8), components, {}, None)
        process_frame(np.zeros((10, 10, 3), dtype=np.uint8), components, {}, None)

        self.assertEqual(
            gateway.published,
            [("smart-home/ai/person_count", {"schema": 1, "count": 2}, True)],
        )


if __name__ == "__main__":
    unittest.main()
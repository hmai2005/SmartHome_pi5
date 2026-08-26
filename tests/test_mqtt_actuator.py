"""Kiểm thử logic actuator không cần MQTT broker thật."""
import os
import sys

# THÊM 3 DÒNG NÀY VÀO ĐẦU FILE: Tự động đưa thư mục gốc dự án vào sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

import unittest

from unittest.mock import patch

from smart_home_ai.hardware.actuator import MqttFanActuator
from smart_home_ai.config import MqttConfig
from smart_home_ai.hardware.mqtt_gateway import PublishResult


class FakeGateway:
    def __init__(self, config, on_message):
        self.config = config
        self.on_message = on_message
        self.connected = True
        self.published = []  # Lưu lại lịch sử các tin nhắn đã "gửi"

    def start(self):
        return None

    def publish_json(self, topic, payload, *, retain):
        # Giả lập gửi tin nhắn thành công mà không cần mạng Internet/Broker
        self.published.append((topic, payload, retain))
        return PublishResult(accepted=True, message_id=len(self.published))

    def stop(self):
        self.connected = False


class MqttFanActuatorTest(unittest.TestCase):
    @patch("smart_home_ai.hardware.actuator.MqttGateway", FakeGateway)
    def test_publish_and_ack(self):
        actuator = MqttFanActuator(MqttConfig(command_refresh_s=999.0))

        self.assertTrue(actuator.set_level(2))
        self.assertFalse(actuator.set_level(2))

        #Kiểm Tra Nội Dung Bản Tin MQTT Đã Gửi
        topic, payload, retained = actuator._gateway.published[0]
        self.assertEqual(topic, "smart-home/fan/command")
        self.assertEqual(payload["level"], 2)
        self.assertTrue(retained)

        #Giả Lập ESP32 Phản Hồi Trạng Thái
        actuator._handle_mqtt_message(
            actuator.config.state_topic,
            {
                "command_id": payload["command_id"],
                "applied_level": 2,
            },
        )
        #Kiểm Tra Bản Chụp Trạng Thái
        state = actuator.snapshot()
        self.assertEqual(state.requested_level, 2)
        self.assertEqual(state.applied_level, 2)
        self.assertFalse(state.acknowledgement_pending) #Xác nhận thành công, không còn trong trạng thái chờ ACK nữa


if __name__ == "__main__":
    unittest.main()

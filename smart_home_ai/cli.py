"""Tham số dòng lệnh và entry point của chương trình."""

from __future__ import annotations

import argparse
from pathlib import Path

from .application import (
    create_application_components,
    run_video_loop,
    shutdown_application,
)
from .models import VideoSource
from .vision.roi import parse_roi


def parse_source(value: str) -> VideoSource:
    try:
        return int(value)
    except ValueError:
        return value


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="YOLO11 people counting + MQTT ESP32 fan control",
    )

    camera = parser.add_argument_group("Camera và YOLO")
    camera.add_argument("--source", default="0")
    camera.add_argument("--model", default="yolo11n.pt")
    camera.add_argument("--tracker", default="bytetrack.yaml")
    camera.add_argument("--det-conf", type=float, default=0.20)
    camera.add_argument("--iou", type=float, default=0.50)
    camera.add_argument("--imgsz", type=int, default=640)
    camera.add_argument("--device", default=None)
    camera.add_argument("--show", action="store_true")

     # ========================================================
    # SENSOR + ROI
    # ========================================================
    sensor = parser.add_argument_group(
        "Sensor và ROI"
    )
    sensor.add_argument(
        "--fallback-temperature",
        type=float,
        default=25.0,
        help=(
            "Nhiệt độ tạm sử dụng trước khi nhận "
            "được dữ liệu DHT11 thật qua MQTT."
        ),
    )
    sensor.add_argument(
        "--roi",
        default=None,
        help=(
            "ROI chuẩn hóa dùng cho people counting."
        ),
    )
    # ========================================================
    # MQTT CONNECTION
    # ========================================================
    mqtt = parser.add_argument_group("MQTT tới ESP32")
    # HiveMQ Cloud: dùng hostname cluster và cổng TLS 8883.
    mqtt.add_argument(
        "--mqtt-host",
        default="caebe80fc31544bab129c40f7b5d3425.s1.eu.hivemq.cloud",
    )
    mqtt.add_argument("--mqtt-port", type=int, default=8883)
    mqtt.add_argument(
        "--mqtt-tls",
        action="store_true",
        default=True,
        help="Dùng TLS cho HiveMQ Cloud (thường là port 8883).",
    )
    mqtt.add_argument(
        "--mqtt-client-id",
        default="smart-home-ai-controller",
    )
    # Credentials được truyền vào MqttConfig để gateway xác thực với HiveMQ.
    mqtt.add_argument("--mqtt-username", default="Hien Mai")
    mqtt.add_argument("--mqtt-password", default="12345678")

    # ========================================================
    # MQTT TOPICS - FAN
    # ========================================================
    mqtt.add_argument(
        "--mqtt-command-topic",
        default="smart-home/fan/command",
        help="Python -> ESP32 fan command.",
    )
    mqtt.add_argument(
        "--mqtt-state-topic",
        default="smart-home/fan/state",
        help="ESP32 -> Python fan state / ACK.",
    )
    mqtt.add_argument(
        "--mqtt-availability-topic",
        default="smart-home/fan/availability",
        help="ESP32 availability topic.",
    )
    # ========================================================
    # MQTT TOPICS - SENSOR
    # ========================================================
    mqtt.add_argument(
        "--mqtt-temperature-topic",
        default="smart-home/sensor/temperature",
        help="ESP32 DHT11 temperature topic.",
    )
    mqtt.add_argument(
        "--mqtt-humidity-topic",
        default="smart-home/sensor/humidity",
        help="ESP32 DHT11 humidity topic.",
    )
    mqtt.add_argument(
        "--mqtt-rain-topic",
        default="smart-home/sensor/rain",
        help="ESP32 rain sensor topic.",
    )
    # ========================================================
    # MQTT TOPICS - ACTUATOR STATE
    # ========================================================
    mqtt.add_argument(
        "--mqtt-led-state-topic",
        default="smart-home/led/state",
        help="ESP32 LED state topic.",
    )
    mqtt.add_argument(
        "--mqtt-servo-retracted-topic",
        default="smart-home/servo/retracted",
        help="ESP32 servo state topic.",
    )
    mqtt.add_argument(
        "--mqtt-person-count-topic",
        default="smart-home/ai/person_count",
        help="Python AI -> ESP32 stable camera person count.",
    )
    # ========================================================
    # MQTT DELIVERY
    # ========================================================
    mqtt.add_argument("--mqtt-qos", type=int, choices=(0, 1, 2), default=1)
    mqtt.add_argument("--mqtt-refresh", type=float, default=10.0)
    mqtt.add_argument("--mqtt-ack-timeout", type=float, default=3.0)
    mqtt.add_argument("--no-mqtt-retain", action="store_true")
    return parser

def main() -> None:
    args = build_arg_parser().parse_args()
    source = parse_source(args.source)
    roi_normalized = parse_roi(args.roi)
    components = create_application_components(args, source)

    try:
        run_video_loop(args, components, roi_normalized)
    finally:
        shutdown_application(components)

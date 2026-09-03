"""Pipeline xử lý hoàn chỉnh cho một frame camera."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Dict, Optional, Sequence

import numpy as np
from ultralytics import YOLO

from .camera import PiCamera
from .hardware.actuator import MqttFanActuator
from .hardware.mqtt_gateway import MqttGateway
from .models import FrameProcessingResult, FrameShape, Point
from .processing_logic.fan_controller import ThreeSpeedFanController
from .processing_logic.temperature import TemperatureReader
from .vision.occupancy import StableOccupancyEstimator
from .vision.roi import roi_pixels
from .vision.tracking import track_people_in_frame


@dataclass
class ApplicationComponents:
    """Các đối tượng được tái sử dụng trong toàn bộ vòng lặp video."""

    model: YOLO
    capture: PiCamera
    occupancy: StableOccupancyEstimator
    fan: ThreeSpeedFanController
    temperature_reader: TemperatureReader
    actuator: MqttFanActuator
    gateway: MqttGateway
    last_published_people: Optional[int] = None


def get_frame_shape(frame: np.ndarray) -> FrameShape:
    """Trả về kích thước frame theo dạng (height, width)."""
    height, width = frame.shape[:2]
    return height, width


def create_frame_polygon(
    frame: np.ndarray,
    roi_normalized: Optional[Sequence[Point]],
) -> Optional[np.ndarray]:
    """Chuyển ROI chuẩn hóa sang tọa độ pixel."""
    height, width = get_frame_shape(frame)
    return roi_pixels(
        roi_normalized,
        width,
        height,
    )


def process_frame(
    frame: np.ndarray,
    components: ApplicationComponents,
    track_kwargs: Dict[str, object],
    roi_normalized: Optional[Sequence[Point]],
) -> FrameProcessingResult:
    # 1. ROI
    polygon = create_frame_polygon(frame, roi_normalized)

    # 2. YOLO + TRACKING
    persons = track_people_in_frame(
        model=components.model,
        frame=frame,
        track_kwargs=track_kwargs,
        polygon=polygon,
    )

    # Dùng monotonic time cho các bộ lọc thời gian
    now = time.monotonic()

    # 3. STABLE PEOPLE COUNT
    stable_people = components.occupancy.update(
        persons=persons,
        now=now,
        frame_shape=get_frame_shape(frame),
    )

    # Publish only on change; retain keeps the latest count available to ESP32.
    if stable_people != components.last_published_people:
        components.gateway.publish_json(
            components.gateway.config.person_count_topic,
            {
                "schema": 1,
                "count": stable_people,
            },
            retain=True,
        )
        components.last_published_people = stable_people

    # 4. TEMPERATURE
    temperature_c = components.temperature_reader.read_celsius()

    # 5. FUZZY FAN CONTROL
    controller_fan_level = components.fan.update(
        people=stable_people,
        temperature_c=temperature_c,
        now=now,
    )

    fuzzy_score = getattr(
        components.fan,
        "fuzzy_score",
        float(controller_fan_level),
    )
    desired_fan_level = getattr(
        components.fan,
        "desired_fan_level",
        controller_fan_level,
    )
    control_mode = getattr(
        components.fan,
        "mode",
        "auto",
    )

    # 6. MQTT ACTUATOR
    components.actuator.set_level(controller_fan_level)

    # 7. RESULT
    return FrameProcessingResult(
        persons=persons,
        polygon=polygon,
        stable_people=stable_people,
        temperature_c=temperature_c,
        fuzzy_score=fuzzy_score,
        desired_fan_level=desired_fan_level,
        fan_level=controller_fan_level,
        control_mode=str(control_mode),
        now=now,
    )
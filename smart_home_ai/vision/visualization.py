"""Vẽ kết quả nhận diện và trạng thái điều khiển lên frame."""

from __future__ import annotations

from typing import Iterable, List, Optional, Sequence

import cv2
import numpy as np
from ..hardware.actuator import FanActuatorSnapshot, MqttFanActuator
from ..processing_logic.fan_controller import ThreeSpeedFanController
from ..models import TrackedPerson
from .occupancy import StableOccupancyEstimator


def draw_roi_polygon(image: np.ndarray, polygon: Optional[np.ndarray]) -> None:
    if polygon is not None:
        cv2.polylines(image, [polygon], True, (255, 255, 255), 2) 
        #vẽ đường đa giác khép kín, màu trắng, với độ dày 2px bằng OpenCV polylines.


def draw_person(image: np.ndarray, person: TrackedPerson) -> None:
    x1, y1, x2, y2 = map(int, person.bbox_xyxy)
    center = (int(person.center_point[0]), int(person.center_point[1]))

    cv2.rectangle(image, (x1, y1), (x2, y2), (0, 255, 0), 2) #vẽ khung chữ nhật màu xanh lá
    cv2.circle(image, center, 4, (0, 255, 255), -1) #vẽ tâm hình tròn nhỏ màu vàng
    cv2.putText( #vẽ chuỗi văn bản: track ID, độ tin cậy
        image,
        f"ID {person.track_id} {person.confidence:.2f}",
        (x1, max(18, y1 - 6)),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.55,
        (0, 255, 0),
        2,
    )


def draw_people(image: np.ndarray, persons: Iterable[TrackedPerson]) -> None:
    for person in persons:
        draw_person(image, person)

#chuyển đổi trạng thái quạt thành văn bản
def fan_level_text(level: Optional[int]) -> str:
    if level is None:
        return "UNKNOWN"
    return "OFF" if level == 0 else f"LEVEL {level}"


def mqtt_status_text(state: FanActuatorSnapshot) -> str:
    if not state.mqtt_connected:
        return "DISCONNECTED"
    if not state.esp32_online:
        return "MQTT OK / ESP32 OFFLINE"
    if state.acknowledgement_timed_out:
        return "ACK TIMEOUT"
    if state.acknowledgement_pending:
        return "WAITING ACK"
    if state.last_error:
        return f"ESP32 ERROR: {state.last_error}"
    return "ONLINE / ACK OK"


def build_status_lines(
    occupancy: StableOccupancyEstimator,
    temperature_c: float,
    fan: ThreeSpeedFanController,
    actuator: MqttFanActuator,
    now: float,
) -> List[str]:
    state = actuator.snapshot(now)
    return [
        f"People: {occupancy.stable_count}",
        f"Temperature: {temperature_c:.1f} C",
        f"AI target: {fan_level_text(state.requested_level)}",
        f"ESP32 applied: {fan_level_text(state.applied_level)}",
        f"MQTT: {mqtt_status_text(state)}",
        occupancy.debug_text(now),
    ]


def draw_status_lines(image: np.ndarray, lines: Sequence[str]) -> None:
    for index, text in enumerate(lines):
        cv2.putText(
            image,
            text,
            (15, 30 + index * 27),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.68 if index < 6 else 0.50,
            (0, 255, 255),
            2,
        )


def draw_overlay(
    frame: np.ndarray,
    persons: Iterable[TrackedPerson],
    polygon: Optional[np.ndarray],
    occupancy: StableOccupancyEstimator,
    temperature_c: float,
    fan: ThreeSpeedFanController,
    actuator: MqttFanActuator,
    now: float,
) -> np.ndarray:
    output = frame.copy()
    draw_roi_polygon(output, polygon)
    draw_people(output, persons)
    draw_status_lines(
        output,
        build_status_lines(occupancy, temperature_c, fan, actuator, now),
    )
    return output

"""Các kiểu dữ liệu dùng chung trong toàn bộ hệ thống."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Deque, List, Optional, Tuple, Union

import numpy as np


# ============================================================
# COMMON TYPES
# ============================================================

Point = Tuple[float, float]

# Bounding box:
# x_min, y_min, x_max, y_max
BoundingBox = Tuple[float, float, float, float]

# height, width
FrameShape = Tuple[int, int]

# Camera index hoặc đường dẫn video.
VideoSource = Union[int, str]


# ============================================================
# TRACKED PERSON
# ============================================================

@dataclass(frozen=True)
class TrackedPerson:
    """Một người được YOLO và tracker phát hiện trong frame."""

    track_id: int

    # Confidence của detection.
    confidence: float

    # Bounding box:
    # x_min, y_min, x_max, y_max
    bbox_xyxy: BoundingBox

    # Tọa độ tâm của bounding box.
    center_point: Point


# ============================================================
# TRACK STATE
# ============================================================

@dataclass
class TrackState:
    """Trạng thái được lưu qua nhiều frame cho một track ID."""

    # Thời điểm track xuất hiện lần đầu.
    first_seen: float

    # Thời điểm track được nhìn thấy gần nhất.
    last_seen: float

    # Vị trí gần nhất.
    last_point: Point

    # Chỉ True sau khi track đủ ổn định.
    confirmed: bool = False

    # Lịch sử các detection đủ mạnh.
    strong_hit_times: Deque[float] = field(
        default_factory=deque
    )


# ============================================================
# FRAME PROCESSING RESULT
# ============================================================

@dataclass(frozen=True)
class FrameProcessingResult:
    """
    Kết quả sau khi xử lý hoàn chỉnh một frame camera.
    Phân biệt:
    desired_fan_level:
        Mức quạt Fuzzy đang yêu cầu.
    fan_level:
        Mức quạt đã được State Machine chấp nhận
        sau hysteresis và hold time.
    """

    # Những người tracker phát hiện trong frame hiện tại.
    persons: List[TrackedPerson]

    # ROI sau khi đổi sang tọa độ pixel.
    polygon: Optional[np.ndarray]

    # Số người đã qua bộ lọc ổn định.
    stable_people: int

    # Nhiệt độ đưa vào Fuzzy Controller.
    temperature_c: float

    # Đầu ra liên tục của Fuzzy Logic.
    # Ví dụ:
    # 1.0 ~ LOW
    # 2.0 ~ MEDIUM
    # 3.0 ~ HIGH
    fuzzy_score: float

    # Mức Fuzzy mong muốn:
    # 0 = OFF
    # 1 = LOW
    # 2 = MEDIUM
    # 3 = HIGH
    desired_fan_level: int

    # Mức quạt controller đã commit.
    fan_level: int

    # Chế độ điều khiển.
    control_mode: str

    # Monotonic timestamp dùng để tính khoảng thời gian.
    now: float
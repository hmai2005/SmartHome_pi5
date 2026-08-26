"""Xử lý vùng quan tâm ROI và chuyển đổi tọa độ."""

from __future__ import annotations

from typing import List, Optional, Sequence, Tuple

import cv2
import numpy as np

from ..models import Point


def parse_normalized_point(token: str) -> Point:
    """Chuyển chuỗi 'x,y' thành một điểm chuẩn hóa."""

    try:
        x_text, y_text = token.split(",", maxsplit=1)  #tách chuỗi str tại dấu ',', maxsplit: đảm bảo chỉ tách tối đa 2 thành phần x, y
        point = (float(x_text), float(y_text))
    except (ValueError, TypeError) as exc:
        raise ValueError(f"Điểm ROI không hợp lệ: {token!r}") from exc

    return point


def validate_normalized_point(point: Point) -> None:
    """Bảo đảm tọa độ chuẩn hóa nằm trong khoảng 0..1."""

    x, y = point
    if not 0.0 <= x <= 1.0 or not 0.0 <= y <= 1.0:
        raise ValueError("Tọa độ ROI phải nằm trong khoảng 0..1")


def validate_roi(points: Sequence[Point]) -> None:
    """Một polygon (đa giác) cần ít nhất ba điểm."""

    if len(points) < 3:
        raise ValueError("ROI cần ít nhất ba điểm")


def parse_roi(value: Optional[str]) -> Optional[List[Point]]:
    """Đọc polygon ROI dạng 'x1,y1;x2,y2;...'."""

    #nếu người dùng không cài đặt vùng ROI
    if not value:
        return None

    points: List[Point] = []
    for token in value.split(";"):
        point = parse_normalized_point(token)
        validate_normalized_point(point)
        points.append(point) #nếu điểm hợp lệ, thêm vào danh sách points

    validate_roi(points) #kiểm tra có ít nhất 3 điểm chưa
    return points


def normalized_point_to_pixel(
    point: Point,
    width: int,
    height: int,
) -> Tuple[int, int]:
    """Chuyển một điểm chuẩn hóa sang tọa độ pixel."""

    x, y = point
    return int(x * width), int(y * height)


def roi_pixels(
    roi_normalized: Optional[Sequence[Point]],
    width: int,
    height: int,
) -> Optional[np.ndarray]:
    """Chuyển toàn bộ polygon chuẩn hóa sang polygon OpenCV."""

    if roi_normalized is None:
        return None

    pixel_points = [
        normalized_point_to_pixel(point, width, height)  #chuyển sang tọa độ pixel
        for point in roi_normalized
    ]
    #Chuyển danh sách pixel thành một mảng NumPy có kiểu dữ liệu số nguyên 32-bit
    return np.array(pixel_points, dtype=np.int32)

def inside_roi(point: Point, polygon: Optional[np.ndarray]) -> bool:
    """Kiểm tra điểm nằm trong hoặc trên biên ROI."""

    if polygon is None:
        return True

    #kiểm tra vị trí của một điểm so với đa giác
    return cv2.pointPolygonTest(polygon, point, False) >= 0
    '''Trả về > 0: Điểm nằm bên trong đa giác.
    Trả về = 0: Điểm nằm đúng trên đường biên đa giác.
    Trả về < 0: Điểm nằm bên ngoài đa giác.
    Trả về True nếu người đó đang đứng inside (bên trong) hoặc ngay trên viền ROI, ngược lại trả về False'''
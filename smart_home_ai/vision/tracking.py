"""YOLO11 tracking và chuyển kết quả sang dữ liệu của hệ thống."""

from __future__ import annotations

import argparse
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from ultralytics import YOLO

from ..models import BoundingBox, Point, TrackedPerson
from .roi import inside_roi


def calculate_bbox_center(bbox: BoundingBox) -> Point:
    """Tính tâm bounding box xyxy."""

    x1, y1, x2, y2 = bbox
    return (x1 + x2) / 2.0, (y1 + y2) / 2.0


def result_has_tracked_boxes(result: object) -> bool:
    """Kiểm tra kết quả Ultralytics có bounding box kèm ID hay không."""

    boxes = getattr(result, "boxes", None)
    return boxes is not None and boxes.id is not None and len(boxes) > 0


def extract_tracking_arrays(
    result: object,
) -> Tuple[np.ndarray, List[int], List[float]]:
    """Đưa bbox, ID và confidence từ tensor về CPU."""

    boxes = result.boxes
    #Lấy danh sách tọa độ bounding boxes $[x_1, y_1, x_2, y_2]$, chuyển từ GPU về CPU rồi ép thành mảng NumPy
    xyxy = boxes.xyxy.cpu().numpy()
    #Lấy danh sách mã ID của từng người (ép kiểu số nguyên int) và chuyển thành Python List.
    track_ids = boxes.id.int().cpu().tolist()
    #Lấy danh sách độ tin cậy confidence (từ $0.0$ đến $1.0$) và chuyển thành Python List.
    confidences = boxes.conf.cpu().tolist()
    return xyxy, track_ids, confidences


def create_tracked_person(
#nhận dữ liệu của 1 đối tượng sau khi bóc tách ở bước trên và đóng gói thành một đối tượng TrackedPerson hoàn chỉnh
    box: Sequence[float],
    track_id: int,
    confidence: float,
) -> TrackedPerson:
    """Tạo một đối tượng TrackedPerson từ đầu ra thô của YOLO."""

    values = tuple(map(float, box))
    if len(values) != 4:
        raise ValueError(f"Bounding box cần 4 giá trị, nhận được {len(values)}")

    bbox: BoundingBox = (values[0], values[1], values[2], values[3])
    return TrackedPerson(
        track_id=int(track_id),
        confidence=float(confidence),
        bbox_xyxy=bbox,
        center_point=calculate_bbox_center(bbox),
    )

#kiểm tra xem người đó có nằm trong vùng quan tâm (ROI) hay không.
def person_is_inside_roi(
    person: TrackedPerson,
    polygon: Optional[np.ndarray],
) -> bool:
    """Lọc người bằng tâm bounding box."""

    return inside_roi(person.center_point, polygon)


def extract_tracked_people(
    result: object,
    polygon: Optional[np.ndarray],
) -> List[TrackedPerson]:
    """Chuyển kết quả YOLO thành danh sách người nằm trong ROI."""

    if not result_has_tracked_boxes(result):
        return []

    xyxy, track_ids, confidences = extract_tracking_arrays(result)
    persons: List[TrackedPerson] = []

    #ghép lại 3 danh sách thông số để duyệt từng người
    for box, track_id, confidence in zip(xyxy, track_ids, confidences):
        person = create_tracked_person(box, track_id, confidence)
        if person_is_inside_roi(person, polygon):
            persons.append(person)

    return persons


def build_track_kwargs(args: argparse.Namespace) -> Dict[str, object]:
    """Tạo tham số cho `YOLO.track()`."""

    track_kwargs: Dict[str, object] = {
        "persist": True, #Giữ lại bộ nhớ ID giữa các khung hình liên tiếp
        "classes": [0],  # COCO class 0 = person
        "conf": args.det_conf, #Ngưỡng độ tin cậy tối thiểu để nhận diện.
        "iou": args.iou, #Ngưỡng giao nhau (Intersection over Union) để lọc bớt các khung trùng lặp
        "imgsz": args.imgsz, #Kích thước hình ảnh đưa vào mô hình AI
        "tracker": args.tracker, #Thuật toán tracking được chọn
        "verbose": False, #Tắt việc in thông báo log thừa ra màn hình Console để giữ màn hình sạch sẽ.
    }

    if args.device is not None:
        track_kwargs["device"] = args.device #Chọn thiết bị chạy mô hình AI

    return track_kwargs


def track_people_in_frame(
    model: YOLO,
    frame: np.ndarray,
    track_kwargs: Dict[str, object],
    polygon: Optional[np.ndarray],
) -> List[TrackedPerson]:
    """Chạy YOLO tracking trên một frame và trả về người trong ROI."""

    results = model.track(frame, **track_kwargs)
    if not results:
        return []
    #Lấy kết quả ở khung hình đầu tiên (results[0]),
    #trích xuất dữ liệu người và lọc theo vùng ROI để trả về kết quả cuối cùng.
    return extract_tracked_people(results[0], polygon)

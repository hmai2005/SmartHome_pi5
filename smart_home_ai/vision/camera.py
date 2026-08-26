"""Raspberry Pi Camera Module V1.3 (OV5647) via Picamera2 on Raspberry Pi 5."""

from __future__ import annotations

from typing import Optional

import numpy as np
from picamera2 import Picamera2


class PiCamera:
    """Wrapper camera đơn giản dùng Picamera2 cho Raspberry Pi 5.

    Camera Module V1.3 dùng cảm biến OV5647. Frame được cấu hình RGB888;
    với Picamera2/libcamera, ndarray của định dạng này phù hợp để đưa trực tiếp
    vào OpenCV/Ultralytics mà không cần cvtColor RGB->BGR lần nữa.
    """

    def __init__(
        self,
        width: int = 640,
        height: int = 480,
        camera_num: int = 0,
        fps: float = 30.0,
    ) -> None:
        self.width = width
        self.height = height
        self.camera_num = camera_num
        self.fps = fps
        self._started = False

        self.camera = Picamera2(camera_num)

        config = self.camera.create_video_configuration(
            main={
                "size": (width, height),
                "format": "RGB888",
            },
            controls={
                "FrameRate": fps,
            },
            buffer_count=4,
        )

        self.camera.configure(config)

    def start(self) -> None:
        """Khởi động camera."""
        if not self._started:
            self.camera.start()
            self._started = True

    def read(self) -> Optional[np.ndarray]:
        """Đọc một frame và trả về ndarray HxWx3 cho OpenCV/YOLO."""
        if not self._started:
            return None

        try:
            frame = self.camera.capture_array("main")

            if frame is None or frame.size == 0:
                return None

            return frame

        except Exception as exc:
            print(f"[CAMERA] Loi doc camera: {exc}")
            return None

    def release(self) -> None:
        """Dừng camera và giải phóng tài nguyên libcamera."""
        try:
            if self._started:
                self.camera.stop()
                self._started = False
        finally:
            self.camera.close()
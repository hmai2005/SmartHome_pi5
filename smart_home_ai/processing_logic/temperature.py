"""Lưu và cung cấp nhiệt độ mới nhất nhận từ MQTT Gateway."""

from __future__ import annotations

import threading
import time
from typing import Optional

from smart_home_ai.config import MqttConfig


class TemperatureReader:
    """
    Cache nhiệt độ mới nhất.
    TemperatureReader KHÔNG tự kết nối MQTT.
    Luồng dữ liệu:

        DHT11
          ↓
        ESP32
          ↓
        MQTT
          ↓
        MqttGateway
          ↓
        update()
          ↓
        TemperatureReader
          ↓
        read_celsius()
          ↓
        Pipeline / Fuzzy
    """

    def __init__(
        self,
        mqtt_config: Optional[MqttConfig] = None,
        fallback_temperature_c: float = 25.0,
    ) -> None:

        self.cfg = mqtt_config or MqttConfig()

        if not self._temperature_is_plausible(
            fallback_temperature_c
        ):
            raise ValueError(
                "Nhiệt độ fallback nằm ngoài khoảng hợp lý"
            )

        # Giá trị dùng trước khi nhận dữ liệu thật.
        self._last_valid = float(
            fallback_temperature_c
        )

        # Đã từng nhận dữ liệu thật hay chưa.
        self._has_live_data = False

        # Thời điểm nhận nhiệt độ gần nhất.
        self._last_update_monotonic: Optional[float] = None

        # Gateway callback và Pipeline có thể chạy khác thread.
        self._lock = threading.Lock()


    # ========================================================
    # VALIDATION
    # ========================================================

    @staticmethod
    def _temperature_is_plausible(
        value: float,
    ) -> bool:
        """Kiểm tra miền nhiệt độ hợp lý."""

        return -20.0 <= value <= 80.0


    # ========================================================
    # UPDATE FROM MQTT GATEWAY
    # ========================================================

    def update(
        self,
        temperature_c: float,
    ) -> None:
        """
        Cập nhật nhiệt độ mới nhận từ MqttGateway.
        """

        value = float(
            temperature_c
        )

        if not self._temperature_is_plausible(
            value
        ):
            print(
                "[Temperature] "
                f"Out-of-range temperature: {value}"
            )

            return

        with self._lock:

            self._last_valid = value

            self._last_update_monotonic = (
                time.monotonic()
            )

            self._has_live_data = True


    # ========================================================
    # PUBLIC API
    # ========================================================

    def read_celsius(
        self,
    ) -> float:
        """
        Trả về nhiệt độ mới nhất.

        Không đọc DHT11 trực tiếp.
        Không gọi MQTT.
        """

        with self._lock:

            return self._last_valid


    def has_live_data(
        self,
    ) -> bool:
        """
        True nếu đã nhận ít nhất
        một nhiệt độ thật từ ESP32.
        """

        with self._lock:

            return self._has_live_data


    def is_stale(
        self,
    ) -> bool:
        """
        Kiểm tra dữ liệu nhiệt độ
        đã quá cũ hay chưa.
        """

        with self._lock:

            if self._last_update_monotonic is None:

                return True

            age = (
                time.monotonic()
                - self._last_update_monotonic
            )

        return (
            age
            > self.cfg.temperature_stale_timeout_s
        )


    def age_seconds(
        self,
    ) -> Optional[float]:
        """
        Trả tuổi của bản tin nhiệt độ gần nhất.
        """

        with self._lock:

            if self._last_update_monotonic is None:

                return None

            return (
                time.monotonic()
                - self._last_update_monotonic
            )
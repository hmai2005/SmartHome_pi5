"""Gửi cấp quạt tới ESP32 và nhận trạng thái áp dụng qua MQTT."""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Optional

from ..config import MqttConfig
from .mqtt_gateway import MqttGateway


# ============================================================
# FAN ACTUATOR SNAPSHOT
# ============================================================

@dataclass(frozen=True)
class FanActuatorSnapshot:
    """Ảnh chụp trạng thái liên lạc với ESP32 tại một thời điểm."""

    # MQTT Gateway hiện có kết nối Broker hay không.
    mqtt_connected: bool

    # ESP32 đang online hay offline.
    esp32_online: bool

    # Level Python gần nhất yêu cầu.
    requested_level: Optional[int]

    # Level ESP32 báo đang áp dụng thực tế.
    applied_level: Optional[int]

    # Command ID gần nhất Python gửi.
    last_command_id: Optional[int]

    # Command ID gần nhất ESP32 đã ACK.
    acknowledged_command_id: Optional[int]

    # Có command chưa được ACK hay không.
    acknowledgement_pending: bool

    # Command đã chờ ACK quá lâu hay chưa.
    acknowledgement_timed_out: bool

    # Lỗi gần nhất.
    last_error: Optional[str]


# ============================================================
# MQTT FAN ACTUATOR
# ============================================================

class MqttFanActuator:
    """
    Điều khiển quạt ESP32 thông qua MqttGateway dùng chung.

    Luồng command:

        Fuzzy Controller
              ↓
        level 0..3
              ↓
        MqttFanActuator
              ↓
        MqttGateway
              ↓
        smart-home/fan/command
              ↓
             ESP32
              ↓
             PWM

    Luồng phản hồi:

        ESP32
          ↓
        smart-home/fan/state
          ↓
        MqttGateway
          ↓
        application.py
          ↓
        handle_state()
          ↓
        MqttFanActuator

    MqttFanActuator KHÔNG:
        - tạo MQTT client
        - start MQTT
        - stop MQTT Gateway

    Quyền sở hữu vòng đời MQTT thuộc application.py.
    """

    # ========================================================
    # INITIALIZE
    # ========================================================

    def __init__(
        self,
        config: MqttConfig,
        gateway: MqttGateway,
    ) -> None:

        self.config = config

        # Gateway dùng chung của toàn application.
        self._gateway = gateway

        # Bảo vệ state vì MQTT callback chạy thread nền.
        self._lock = threading.Lock()

        # Chỉ cho một set_level() chạy tại một thời điểm.
        self._command_lock = threading.Lock()

        # Level Python gần nhất yêu cầu.
        self._requested_level: Optional[int] = None

        # Level ESP32 báo đang áp dụng.
        self._applied_level: Optional[int] = None

        # Command ID gần nhất gửi.
        self._last_command_id: Optional[int] = None

        # Command ID gần nhất được ESP32 ACK.
        self._acknowledged_command_id: Optional[int] = None

        # Thời điểm publish command gần nhất.
        self._last_publish_monotonic = -float("inf")

        # Thời điểm command gần nhất được tạo.
        self._last_command_monotonic = -float("inf")

        # ESP32 online/offline.
        self._esp32_online = False

        # Lỗi gần nhất.
        self._last_error: Optional[str] = None

        # Bộ đếm command ID.
        self._command_sequence = 0


    # ========================================================
    # VALIDATION
    # ========================================================

    @staticmethod
    def _validate_level(
        level: int,
    ) -> None:
        """Kiểm tra cấp quạt hợp lệ."""

        if level not in (0, 1, 2, 3):

            raise ValueError(
                "Cấp quạt phải là 0, 1, 2 hoặc 3"
            )


    # ========================================================
    # COMMAND ID
    # ========================================================

    def _next_command_id(
        self,
    ) -> int:
        """
        Sinh command ID tăng dần.

        Hàm được gọi khi đang giữ self._lock.
        """

        self._command_sequence += 1

        # Tránh tăng vô hạn.
        if self._command_sequence >= 2_000_000_000:
            self._command_sequence = 1

        return self._command_sequence


    # ========================================================
    # ESP32 AVAILABILITY
    # ========================================================

    def handle_availability(
        self,
        payload: dict,
    ) -> None:
        """
        Nhận availability đã được MqttGateway decode.

        Payload mong đợi:

            {"status": "online"}

        hoặc:

            {"status": "offline"}
        """

        raw_status = payload.get(
            "status"
        )

        status = str(
            raw_status
            if raw_status is not None
            else ""
        ).strip().lower()

        # Gateway hiện chuẩn hóa về online/offline.
        # Vẫn chấp nhận open/close để code chắc chắn hơn.
        if status in (
            "online",
            "open",
        ):
            online = True

        elif status in (
            "offline",
            "close",
            "ofline",
        ):
            online = False

        else:

            with self._lock:
                self._last_error = (
                    "Availability ESP32 không hợp lệ: "
                    f"{raw_status!r}"
                )

            return


        with self._lock:

            self._esp32_online = online


        print(
            "[ESP32 availability] "
            f"{'ONLINE' if online else 'OFFLINE'}"
        )


    # ========================================================
    # ESP32 FAN STATE / ACK
    # ========================================================

    def handle_state(
        self,
        payload: dict,
    ) -> None:
        """
        Nhận trạng thái quạt thực tế từ ESP32.

        ACK:

            {
                "schema": 1,
                "applied_level": 2,
                "command_id": 10
            }

        Manual Override:

            {
                "schema": 1,
                "applied_level": 1,
                "command_id": 10,
                "error": "manual_override"
            }

        Snapshot sau reconnect:

            {
                "schema": 1,
                "applied_level": 2
            }

        Snapshot không có command_id nên không được xem
        là ACK cho command hiện tại.
        """

        try:

            # ------------------------------------------------
            # SCHEMA
            # ------------------------------------------------

            schema = int(
                payload.get(
                    "schema",
                    0,
                )
            )

            if schema != 1:

                raise ValueError(
                    f"schema không hỗ trợ: {schema}"
                )


            # ------------------------------------------------
            # APPLIED LEVEL
            # ------------------------------------------------

            applied_level = int(
                payload["applied_level"]
            )

            self._validate_level(
                applied_level
            )


            # ------------------------------------------------
            # COMMAND ID
            # ------------------------------------------------

            raw_command_id = payload.get(
                "command_id"
            )

            command_id = (
                None
                if raw_command_id is None
                else int(raw_command_id)
            )


            # ------------------------------------------------
            # ERROR
            # ------------------------------------------------

            raw_error = payload.get(
                "error"
            )

            error_message = (
                None
                if raw_error is None
                else str(raw_error)
            )


        except (
            KeyError,
            TypeError,
            ValueError,
        ) as error:

            with self._lock:

                self._last_error = (
                    "State ESP32 không hợp lệ: "
                    f"{error}"
                )

            return


        # ====================================================
        # UPDATE STATE
        # ====================================================

        with self._lock:

            # Trạng thái vật lý thực tế.
            self._applied_level = (
                applied_level
            )

            # Chỉ coi là ACK nếu ESP32 gửi command_id.
            if command_id is not None:

                self._acknowledged_command_id = (
                    command_id
                )

            # Có state nghĩa là ESP32 đang hoạt động.
            self._esp32_online = True

            self._last_error = (
                error_message
            )


        print(
            "[ESP32 → MQTT] "
            f"applied_level={applied_level}, "
            f"command_id={command_id}, "
            f"error={error_message}"
        )


    # ========================================================
    # SHOULD PUBLISH?
    # ========================================================

    def _should_publish(
        self,
        level: int,
        now: float,
        force: bool,
    ) -> bool:
        """
        Quyết định có cần gửi command MQTT hay không.

        Gửi khi:
            1. force=True
            2. level thay đổi
            3. đến chu kỳ command refresh
        """

        if force:

            return True


        if level != self._requested_level:

            return True


        return (
            now
            - self._last_publish_monotonic
            >= self.config.command_refresh_s
        )


    # ========================================================
    # COMMAND PAYLOAD
    # ========================================================

    def _build_command_payload(
        self,
        level: int,
        command_id: int,
    ) -> dict:
        """
        Tạo JSON command gửi ESP32.
        """

        return {
            "schema": 1,
            "command_id": command_id,
            "level": level,
            "source": self.config.client_id,
            "sent_at_unix_ms": int(
                time.time() * 1000
            ),
        }


    # ========================================================
    # SET FAN LEVEL
    # ========================================================

    def set_level(
        self,
        level: int,
        *,
        force: bool = False,
        wait_for_publish: bool = False,
    ) -> bool:
        """
        Yêu cầu ESP32 chạy cấp quạt level.

        Returns
        -------
        True:
            MQTT client đã chấp nhận bản tin.

        False:
            - không cần gửi command mới
            - hoặc MQTT publish thất bại

        Lưu ý:
            True KHÔNG có nghĩa ESP32 đã áp dụng level.

        Trạng thái thực tế phải được xác nhận qua:

            smart-home/fan/state
        """

        self._validate_level(
            level
        )


        # Chỉ một command được xây dựng/publish tại một thời điểm.
        with self._command_lock:

            now = time.monotonic()


            # =================================================
            # DECIDE
            # =================================================

            with self._lock:

                should_publish = (
                    self._should_publish(
                        level,
                        now,
                        force,
                    )
                )


                if not should_publish:

                    return False


                command_id = (
                    self._next_command_id()
                )


                payload = (
                    self._build_command_payload(
                        level,
                        command_id,
                    )
                )


            # =================================================
            # MQTT PUBLISH
            # =================================================

            result = (
                self._gateway.publish_json(
                    self.config.command_topic,
                    payload,
                    retain=(
                        self.config.retain_command
                    ),
                    wait_for_publish=(
                        wait_for_publish
                    ),
                )
            )


            # =================================================
            # UPDATE LOCAL STATE
            # =================================================

            with self._lock:

                if not result.accepted:

                    self._last_error = (
                        "MQTT client từ chối "
                        "publish command"
                    )

                    return False


                self._requested_level = (
                    level
                )

                self._last_command_id = (
                    command_id
                )

                self._last_publish_monotonic = (
                    now
                )

                self._last_command_monotonic = (
                    now
                )

                self._last_error = None


            print(
                "[MQTT → ESP32] "
                f"level={level}, "
                f"command_id={command_id}, "
                f"mid={result.message_id}"
            )


            return True


    # ========================================================
    # SNAPSHOT
    # ========================================================

    def snapshot(
        self,
        now: Optional[float] = None,
    ) -> FanActuatorSnapshot:
        """
        Trả snapshot nhất quán cho GUI/log/Dashboard.
        """

        current_time = (
            time.monotonic()
            if now is None
            else now
        )


        with self._lock:

            # Có command đã gửi nhưng ACK gần nhất
            # chưa đúng command ID đó.
            pending = (
                self._last_command_id is not None
                and
                self._acknowledged_command_id
                != self._last_command_id
            )


            timed_out = (
                pending
                and
                current_time
                - self._last_command_monotonic
                >= self.config.acknowledgement_timeout_s
            )


            return FanActuatorSnapshot(

                mqtt_connected=(
                    self._gateway.connected
                ),

                esp32_online=(
                    self._esp32_online
                ),

                requested_level=(
                    self._requested_level
                ),

                applied_level=(
                    self._applied_level
                ),

                last_command_id=(
                    self._last_command_id
                ),

                acknowledged_command_id=(
                    self._acknowledged_command_id
                ),

                acknowledgement_pending=(
                    pending
                ),

                acknowledgement_timed_out=(
                    timed_out
                ),

                last_error=(
                    self._last_error
                ),
            )


    # ========================================================
    # CLOSE
    # ========================================================

    def close(
        self,
    ) -> None:
        """
        Yêu cầu quạt OFF khi application dừng.

        KHÔNG stop MqttGateway ở đây.

        application.py mới là nơi sở hữu Gateway
        và chịu trách nhiệm gọi gateway.stop().
        """

        self.set_level(
            0,
            force=True,
            wait_for_publish=True,
        )
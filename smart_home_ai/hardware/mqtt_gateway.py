"""Lớp giao tiếp MQTT mức thấp cho máy chạy YOLO."""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from typing import Callable

import paho.mqtt.client as mqtt

from ..config import MqttConfig


MessageHandler = Callable[
    [str, dict],
    None,
]

# ============================================================
# PUBLISH RESULT
# ============================================================
@dataclass(frozen=True)
class PublishResult:
    """Kết quả publish trả về từ MQTT client."""
    # MQTT client có nhận yêu cầu publish hay không.
    accepted: bool
    # MQTT Message ID.
    message_id: int
    # True nếu đã chờ và xác nhận publish hoàn tất.
    published: bool
# ============================================================
# MQTT GATEWAY
# ============================================================
class MqttGateway:
    """
    Quản lý kết nối MQTT mức thấp.
    Chức năng:
        - connect broker
        - reconnect
        - subscribe
        - parse message
        - publish JSON
        - network loop background
    """
    def __init__(
        self,
        config: MqttConfig,
        on_message: MessageHandler,
    ) -> None:
        self.config = config
        self._on_application_message = on_message
        self._connected = threading.Event()
        self._stopped = False
        self._lock = threading.Lock()
        self._client = self._create_client()
        self._configure_client()
    # ========================================================
    # MQTT CLIENT
    # ========================================================
    def _create_client(
        self,
    ) -> mqtt.Client:
        """
        Dùng Callback API Version 2.
        """
        return mqtt.Client(
            callback_api_version= mqtt.CallbackAPIVersion.VERSION2,
            client_id=self.config.client_id,
            protocol=mqtt.MQTTv311,
        )
    # ========================================================
    # CONFIGURE CLIENT
    # ========================================================
    def _configure_client(
        self,
    ) -> None:
        # TCP connection timeout.
        self._client.connect_timeout = self.config.connect_timeout_s
        if self.config.tls:
            self._client.tls_set()
        # Tự reconnect với exponential delay.
        self._client.reconnect_delay_set(
            min_delay=1,
            max_delay=30,
        )
        if self.config.username:
            self._client.username_pw_set(
                self.config.username,
                self.config.password,
            )
        self._client.on_connect = self._on_connect
        self._client.on_disconnect = self._on_disconnect
        self._client.on_message = self._on_message
    # ========================================================
    # CONNECT CALLBACK
    # ========================================================
    def _on_connect(
        self,
        client: mqtt.Client,
        userdata,
        connect_flags,
        reason_code,
        properties,
    ) -> None:
        del userdata
        del connect_flags
        del properties
        # Callback API v2 ReasonCode.
        if reason_code.is_failure:
            print( "[MQTT] Kết nối thất bại: " f"{reason_code}")
            return
        # ====================================================
        # SUBSCRIBE ALL ESP32 TOPICS
        # ====================================================
        topics = [
            # -----------------------------------------------
            # FAN
            # -----------------------------------------------
            self.config.state_topic,
            self.config.availability_topic, #esp32
            # -----------------------------------------------
            # SENSOR
            # -----------------------------------------------
            self.config.temperature_topic,
            self.config.humidity_topic,
            self.config.rain_topic,
            # -----------------------------------------------
            # ACTUATOR STATE
            # -----------------------------------------------
            self.config.led_state_topic,
            self.config.servo_retracted_topic,
        ]
        for topic in topics:
            result, message_id = (
                client.subscribe(topic, qos=self.config.qos,)
            )
            del message_id
            if (result == mqtt.MQTT_ERR_SUCCESS):
                print(
                    "[MQTT] Subscribe OK: "
                    f"{topic}"
                )
            else:
                print(
                    "[MQTT] Subscribe FAILED: "
                    f"{topic}"
                )
        self._connected.set()
        print(
            "[MQTT] Đã kết nối broker "
            f"{self.config.host}:"
            f"{self.config.port}"
        )
    # ========================================================
    # DISCONNECT CALLBACK
    # ========================================================
    def _on_disconnect(
        self,
        client: mqtt.Client,
        userdata,
        disconnect_flags,
        reason_code,
        properties,
    ) -> None:
        del client
        del userdata
        del disconnect_flags
        del properties
        self._connected.clear()
        if not self._stopped:
            print(
                "[MQTT] Mất kết nối: "
                f"{reason_code}"
            )
    # ========================================================
    # PARSE BOOLEAN
    # ========================================================
    @staticmethod
    def _decode_bool(
        text: str,
    ) -> bool:
        """
        ESP32 publish bool bằng:
            true  -> "1"
            false -> "0"
        Đồng thời hỗ trợ:
            true / false
            on / off
        """
        value = (
            text
            .strip()
            .lower()
        )
        if value in (
            "1",
            "true",
            "on",
        ):
            return True
        
        if value in (
            "0",
            "false",
            "off",
        ):
            return False
        raise ValueError(
            "Boolean MQTT payload "
            f"không hợp lệ: {text}"
        )

    # ========================================================
    # DECODE MQTT PAYLOAD
    # ========================================================
    def _decode_payload(
        self,
        topic: str,
        raw_payload: bytes,
    ) -> dict:
        """
        Chuẩn hóa mọi MQTT message thành dict.
        ESP32 hiện gửi:
        Temperature:  "30.25"
        Humidity:  "65.40"
        Rain:  "0"  hoặc   "1"
        LED:  "0"  hoặc   "1"
        Servo:  "0"  hoặc   "1"
        Availability:
            {"status":"online"}
            hoặc
            {"status":"offline"}
        Fan State:
            {
                "schema":1,
                "applied_level":2
            }
        Fan ACK:
            {
                "schema":1,
                "command_id":15,
                "applied_level":3
            }
        """
        text = raw_payload.decode(
            "utf-8"
        ).strip()
        # ====================================================
        # TEMPERATURE
        # ====================================================
        if ( topic == self.config.temperature_topic):
            value = float(text)
            return {"temperature_c": value,}
        # ====================================================
        # HUMIDITY
        # ====================================================
        if (topic == self.config.humidity_topic):
            value = float(text)
            return {"humidity_percent": value,  }
        # ====================================================
        # RAIN
        # ====================================================
        if (topic == self.config.rain_topic):
            value = self._decode_bool(text)
            return {"rain": value,}
        # ====================================================
        # LED STATE
        # ====================================================
        if (topic == self.config.led_state_topic):
            value = self._decode_bool(text)
            return {"led_on": value,}
        # ====================================================
        # SERVO STATE
        # ====================================================
        if (topic == self.config.servo_retracted_topic):
            value = self._decode_bool(text)
            return {"servo_retracted": value,}
        # ================================================
        # AVAILABILITY
        # ================================================
        if (topic == self.config.availability_topic):
            # Hỗ trợ ESP32 hiện tại:
            # online
            # offline
            lower_text = (text.lower())
            if lower_text == "online":
                return {
                     "status": "online",
                }
            if lower_text in ("offline","ofline",):
                return {
                    "status": "offline",
                }
            # Đồng thời hỗ trợ JSON nếu sau này đổi sang:
            #
            # {"status":"online"}
            payload = json.loads(text)

            if not isinstance(
                payload,
                dict,
            ):
                raise ValueError(
                    "Availability phải là "
                    "JSON object"
                )
            status = str(payload.get("status", "",)).strip().lower()

            if status == "online":
                return {
                    "status": "online",
                }
            # Tạm hỗ trợ cả typo hiện tại của ESP32:
            # "ofline"
            if status in (
                "offline",
                "ofline",
            ):
                return {
                    "status": "offline",
                }

            raise ValueError(
                "Availability status "
                f"không hợp lệ: {status}"
            )
        # ====================================================
        # FAN STATE / FAN ACK
        # ====================================================
        if (topic == self.config.state_topic):
            payload = json.loads(text)
            if not isinstance(payload,dict,):
                raise ValueError(
                    "Fan state phải là "
                    "JSON object"
                )
            # ------------------------------------------------
            # Kiểm tra schema tối thiểu.
            # ------------------------------------------------
            schema = payload.get("schema")
            if schema != 1:
                raise ValueError(
                    "Fan state schema "
                    f"không hỗ trợ: {schema}"
                )
            # ------------------------------------------------
            # applied_level bắt buộc phải có.
            # ------------------------------------------------
            applied_level = payload.get("applied_level")
            if not isinstance(
                applied_level,
                int,
            ):
                raise ValueError(
                    "Fan state thiếu "
                    "applied_level hợp lệ"
                )
            if not (0  <= applied_level <= 3):
                raise ValueError(
                    "Fan applied_level "
                    f"không hợp lệ: "
                    f"{applied_level}"
                )
            # command_id và error là optional.
            # Snapshot reconnect:
            # {
            #     "schema":1,
            #     "applied_level":2
            # }
            # không có command_id.
            return payload
        # ====================================================
        # UNKNOWN TOPIC
        # ====================================================
        raise ValueError(
            "Topic MQTT chưa được hỗ trợ: "
            f"{topic}"
        )
    # =======================================================
    # MESSAGE CALLBACK
    # ========================================================
    def _on_message(
        self,
        client: mqtt.Client,
        userdata,
        message: mqtt.MQTTMessage,
    ) -> None:

        del client
        del userdata

        try:

            payload = self._decode_payload(
                message.topic,
                message.payload,
            )

        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            ValueError,
        ) as error:

            print(
                "[MQTT] Bỏ qua payload "
                f"không hợp lệ trên "
                f"{message.topic}: {error}"
            )

            return

        self._on_application_message(
            message.topic,
            payload,
        )

    # ========================================================
    # CONNECTED
    # ========================================================

    @property
    def connected(
        self,
    ) -> bool:

        return self._connected.is_set()

    # ========================================================
    # START
    # ========================================================

    def start(
        self,
    ) -> None:
        """
        Kết nối Broker và khởi động network loop nền.
        """

        self._stopped = False

        # Async connection:
        # network thread xử lý connect/reconnect.
        self._client.connect_async(
            self.config.host,
            self.config.port,
            self.config.keepalive_s,
        )

        self._client.loop_start()

        if not self._connected.wait(
            self.config.connect_timeout_s
        ):

            self.stop()

            raise TimeoutError(
                "Không kết nối được MQTT broker trong "
                f"{self.config.connect_timeout_s:.1f} giây"
            )

    # ========================================================
    # PUBLISH JSON
    # ========================================================

    def publish_json(
        self,
        topic: str,
        payload: dict,
        *,
        retain: bool,
        wait_for_publish: bool = False,
    ) -> PublishResult:
        """
        Publish JSON.

        QoS lấy từ MqttConfig.

        accepted:
            publish() được MQTT client chấp nhận.

        published:
            packet đã hoàn tất publish nếu
            wait_for_publish=True.
        """

        body = json.dumps(
            payload,
            separators=(",", ":"),
            ensure_ascii=False,
        )

        with self._lock:

            info = self._client.publish(
                topic,
                body,
                qos=self.config.qos,
                retain=retain,
            )

        accepted = (
            info.rc
            == mqtt.MQTT_ERR_SUCCESS
        )

        published = False

        if (
            accepted
            and wait_for_publish
        ):

            try:

                info.wait_for_publish(
                    timeout=(
                        self.config
                        .acknowledgement_timeout_s
                    )
                )

                published = (
                    info.is_published()
                )

            except (
                RuntimeError,
                ValueError,
            ):

                published = False

        return PublishResult(
            accepted=accepted,
            message_id=int(
                info.mid
            ),
            published=published,
        )

    # ========================================================
    # STOP
    # ========================================================

    def stop(
        self,
    ) -> None:
        """Dừng MQTT client. Có thể gọi nhiều lần."""

        if self._stopped:
            return

        self._stopped = True

        try:

            if self._client.is_connected():

                self._client.disconnect()

        finally:

            self._client.loop_stop()

            self._connected.clear()
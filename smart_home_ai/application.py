"""Khởi tạo hệ thống và vận hành vòng lặp camera."""

from __future__ import annotations

import argparse
import threading
from dataclasses import dataclass
from typing import Optional, Sequence

import cv2
import numpy as np
from ultralytics import YOLO

from .camera import PiCamera
from .config import MqttConfig

from .hardware.actuator import (
    MqttFanActuator,
)

from .hardware.mqtt_gateway import (
    MqttGateway,
)

from .models import (
    Point,
    VideoSource,
)

from .pipeline import (
    ApplicationComponents,
    process_frame,
)

from .processing_logic.fan_controller import (
    ThreeSpeedFanController,
)

from .processing_logic.temperature import (
    TemperatureReader,
)

from .vision.occupancy import (
    StableOccupancyEstimator,
)

from .vision.tracking import (
    build_track_kwargs,
)

from .vision.visualization import (
    draw_overlay,
)


# ============================================================
# MQTT SYSTEM STATE
# ============================================================

@dataclass(frozen=True)
class MqttSystemSnapshot:
    """
    Snapshot trạng thái mới nhất nhận từ ESP32.
    """

    temperature_c: Optional[float]

    humidity_percent: Optional[float]

    rain: Optional[bool]

    led_on: Optional[bool]

    servo_retracted: Optional[bool]

    esp32_online: bool


class MqttSystemState:
    """
    Lưu trạng thái mới nhất của sensor và actuator
    được MqttGateway nhận từ ESP32.

    MqttGateway chạy background thread nên dữ liệu
    được bảo vệ bằng Lock.
    """

    def __init__(self) -> None:

        self._lock = threading.Lock()

        self._temperature_c: Optional[float] = None

        self._humidity_percent: Optional[float] = None

        self._rain: Optional[bool] = None

        self._led_on: Optional[bool] = None

        self._servo_retracted: Optional[bool] = None

        self._esp32_online = False


    # ========================================================
    # UPDATE TEMPERATURE
    # ========================================================

    def update_temperature(
        self,
        value: float,
    ) -> None:

        with self._lock:

            self._temperature_c = float(
                value
            )


    # ========================================================
    # UPDATE HUMIDITY
    # ========================================================

    def update_humidity(
        self,
        value: float,
    ) -> None:

        with self._lock:

            self._humidity_percent = float(
                value
            )


    # ========================================================
    # UPDATE RAIN
    # ========================================================

    def update_rain(
        self,
        value: bool,
    ) -> None:

        with self._lock:

            self._rain = bool(
                value
            )


    # ========================================================
    # UPDATE LED
    # ========================================================

    def update_led(
        self,
        value: bool,
    ) -> None:

        with self._lock:

            self._led_on = bool(
                value
            )


    # ========================================================
    # UPDATE SERVO
    # ========================================================

    def update_servo(
        self,
        value: bool,
    ) -> None:

        with self._lock:

            self._servo_retracted = bool(
                value
            )


    # ========================================================
    # UPDATE AVAILABILITY
    # ========================================================

    def update_availability(
        self,
        online: bool,
    ) -> None:

        with self._lock:

            self._esp32_online = bool(
                online
            )


    # ========================================================
    # SNAPSHOT
    # ========================================================

    def snapshot(
        self,
    ) -> MqttSystemSnapshot:

        with self._lock:

            return MqttSystemSnapshot(

                temperature_c=(
                    self._temperature_c
                ),

                humidity_percent=(
                    self._humidity_percent
                ),

                rain=(
                    self._rain
                ),

                led_on=(
                    self._led_on
                ),

                servo_retracted=(
                    self._servo_retracted
                ),

                esp32_online=(
                    self._esp32_online
                ),
            )


# ============================================================
# VIDEO CAPTURE
# ============================================================

def open_video_capture(
    source: Optional[VideoSource] = None,
) -> PiCamera:
    """Mở Camera Module V1.3 qua Picamera2.

    ``source`` được giữ lại chỉ để không phá API cũ của chương trình.
    Khi chạy trên Raspberry Pi 5, nguồn video luôn là camera CSI/Picamera2.
    """

    del source  # Không còn dùng cv2.VideoCapture/webcam source.

    capture = PiCamera(
        width=640,
        height=480,
        camera_num=0,
        fps=30.0,
    )

    capture.start()

    return capture


# ============================================================
# MQTT CONFIG
# ============================================================

def build_mqtt_config(
    args: argparse.Namespace,
) -> MqttConfig:
    """
    Tạo cấu hình MQTT từ CLI.
    """

    return MqttConfig(

        # ----------------------------------------------------
        # BROKER
        # ----------------------------------------------------

        host=args.mqtt_host,

        port=args.mqtt_port,

        # HiveMQ Cloud yêu cầu kết nối MQTT có mã hóa TLS.
        tls=args.mqtt_tls,

        client_id=args.mqtt_client_id,

        username=args.mqtt_username,

        password=args.mqtt_password,


        # ----------------------------------------------------
        # FAN
        # ----------------------------------------------------

        command_topic=(
            args.mqtt_command_topic
        ),

        state_topic=(
            args.mqtt_state_topic
        ),

        availability_topic=(
            args.mqtt_availability_topic
        ),


        # ----------------------------------------------------
        # SENSOR
        # ----------------------------------------------------

        temperature_topic=(
            args.mqtt_temperature_topic
        ),

        humidity_topic=(
            args.mqtt_humidity_topic
        ),

        rain_topic=(
            args.mqtt_rain_topic
        ),


        # ----------------------------------------------------
        # ACTUATOR STATE
        # ----------------------------------------------------

        led_state_topic=(
            args.mqtt_led_state_topic
        ),

        servo_retracted_topic=(
            args.mqtt_servo_retracted_topic
        ),


        # ----------------------------------------------------
        # MQTT DELIVERY
        # ----------------------------------------------------

        qos=args.mqtt_qos,

        retain_command=(
            not args.no_mqtt_retain
        ),

        command_refresh_s=(
            args.mqtt_refresh
        ),

        acknowledgement_timeout_s=(
            args.mqtt_ack_timeout
        ),
    )


# ============================================================
# CREATE APPLICATION COMPONENTS
# ============================================================

def create_application_components(
    args: argparse.Namespace,
    source: VideoSource,
) -> ApplicationComponents:
    """
    Khởi tạo toàn bộ hệ thống.

    MQTT architecture:

        ESP32
          │
          ▼
       Mosquitto
          │
          ▼
     MqttGateway
          │
          ▼
    on_mqtt_message()
          │
          ├── Temperature
          │       ↓
          │  TemperatureReader
          │       ↓
          │     Fuzzy
          │
          ├── Humidity
          │       ↓
          │  MqttSystemState
          │
          ├── Rain
          │       ↓
          │  MqttSystemState
          │
          ├── LED
          │       ↓
          │  MqttSystemState
          │
          ├── Servo
          │       ↓
          │  MqttSystemState
          │
          ├── Fan State
          │       ↓
          │  MqttFanActuator
          │
          └── Availability
                  ↓
             MqttFanActuator
             MqttSystemState
    """

    # ========================================================
    # CAMERA
    # ========================================================

    capture = open_video_capture(
        source
    )


    gateway: Optional[MqttGateway] = None


    try:

        # ====================================================
        # MQTT CONFIG
        # ====================================================

        mqtt_config = (
            build_mqtt_config(
                args
            )
        )


        # ====================================================
        # SENSOR / SYSTEM STATE
        # ====================================================

        mqtt_state = (
            MqttSystemState()
        )


        # ====================================================
        # TEMPERATURE READER
        # ====================================================
        #
        # TemperatureReader không tự kết nối MQTT.
        #
        # Nó chỉ cache nhiệt độ để Pipeline/Fuzzy đọc.
        #
        # ====================================================

        temperature_reader = (
            TemperatureReader(
                mqtt_config=mqtt_config,
                fallback_temperature_c=(
                    args.fallback_temperature
                ),
            )
        )


        # ====================================================
        # ACTUATOR HOLDER
        # ====================================================
        #
        # Callback phải tồn tại trước khi Gateway được tạo.
        #
        # Nhưng actuator lại cần Gateway.
        #
        # Do đó dùng holder.
        #
        # ====================================================

        actuator_holder: dict[
            str,
            MqttFanActuator,
        ] = {}


        # ====================================================
        # MQTT APPLICATION CALLBACK
        # ====================================================

        def on_mqtt_message(
            topic: str,
            payload: dict,
        ) -> None:
            """
            Nhận dữ liệu đã được MqttGateway decode
            và chuyển đến module phù hợp.

            KHÔNG decode MQTT lần nữa ở đây.
            """

            # ================================================
            # TEMPERATURE
            # ================================================

            if (
                topic
                == mqtt_config.temperature_topic
            ):

                value = payload.get(
                    "temperature_c"
                )


                if value is None:
                    return


                # Cache chung.
                mqtt_state.update_temperature(
                    value
                )


                # Cache dành riêng cho Fuzzy/Pipeline.
                temperature_reader.update(
                    value
                )


                return


            # ================================================
            # HUMIDITY
            # ================================================

            if (
                topic
                == mqtt_config.humidity_topic
            ):

                value = payload.get(
                    "humidity_percent"
                )


                if value is not None:

                    mqtt_state.update_humidity(
                        value
                    )


                return


            # ================================================
            # RAIN
            # ================================================

            if (
                topic
                == mqtt_config.rain_topic
            ):

                value = payload.get(
                    "rain"
                )


                if value is not None:

                    mqtt_state.update_rain(
                        value
                    )


                return


            # ================================================
            # LED STATE
            # ================================================

            if (
                topic
                == mqtt_config.led_state_topic
            ):

                value = payload.get(
                    "led_on"
                )


                if value is not None:

                    mqtt_state.update_led(
                        value
                    )


                return


            # ================================================
            # SERVO STATE
            # ================================================

            if (
                topic
                == mqtt_config.servo_retracted_topic
            ):

                value = payload.get(
                    "servo_retracted"
                )


                if value is not None:

                    mqtt_state.update_servo(
                        value
                    )


                return


            # ================================================
            # FAN STATE / ACK
            # ================================================

            if (
                topic
                == mqtt_config.state_topic
            ):

                actuator = (
                    actuator_holder.get(
                        "fan"
                    )
                )


                if actuator is not None:

                    actuator.handle_state(
                        payload
                    )


                return


            # ================================================
            # ESP32 AVAILABILITY
            # ================================================

            if (
                topic
                == mqtt_config.availability_topic
            ):

                status = str(
                    payload.get(
                        "status",
                        "",
                    )
                ).lower()


                online = (
                    status == "online"
                )


                # Lưu vào state chung.
                mqtt_state.update_availability(
                    online
                )


                # Đồng thời cập nhật actuator.
                actuator = (
                    actuator_holder.get(
                        "fan"
                    )
                )


                if actuator is not None:

                    actuator.handle_availability(
                        payload
                    )


                return


        # ====================================================
        # MQTT GATEWAY
        # ====================================================
        #
        # Chỉ có MỘT Gateway cho toàn chương trình.
        #
        # ====================================================

        gateway = MqttGateway(
            config=mqtt_config,
            on_message=on_mqtt_message,
        )


        # ====================================================
        # FAN ACTUATOR
        # ====================================================

        actuator = MqttFanActuator(
            config=mqtt_config,
            gateway=gateway,
        )


        actuator_holder[
            "fan"
        ] = actuator


        # ====================================================
        # YOLO MODEL
        # ====================================================

        model = YOLO(
            args.model
        )


        # ====================================================
        # OCCUPANCY
        # ====================================================

        occupancy = (
            StableOccupancyEstimator()
        )


        # ====================================================
        # FUZZY FAN CONTROLLER
        # ====================================================

        fan_controller = (
            ThreeSpeedFanController()
        )


        # ====================================================
        # START MQTT
        # ====================================================
        #
        # Start sau khi:
        #
        # - callback đã sẵn sàng
        # - TemperatureReader đã có
        # - actuator đã có
        #
        # MQTT retained message có thể đến ngay sau subscribe.
        #
        # ====================================================

        gateway.start()


        # ====================================================
        # RETURN
        # ====================================================

        return ApplicationComponents(

            model=model,

            capture=capture,

            occupancy=occupancy,

            fan=fan_controller,

            temperature_reader=(
                temperature_reader
            ),

            actuator=actuator,

            gateway=gateway,
        )


    # ========================================================
    # INITIALIZATION ERROR
    # ========================================================

    except Exception:

        if gateway is not None:

            try:

                gateway.stop()

            except Exception:

                pass


        capture.release()

        raise


# ============================================================
# READ NEXT FRAME
# ============================================================

def read_next_frame(
    capture: PiCamera,
) -> Optional[np.ndarray]:
    """Đọc frame tiếp theo từ Picamera2."""

    return capture.read()


# ============================================================
# USER EXIT
# ============================================================

def user_requested_exit() -> bool:
    """
    Nhấn ESC hoặc Q để thoát.
    """

    key = (
        cv2.waitKey(1)
        & 0xFF
    )


    return key in (
        27,
        ord("q"),
    )


# ============================================================
# SHOW RESULT
# ============================================================

def show_result(
    frame: np.ndarray,
    components: ApplicationComponents,
    result,
) -> bool:
    """
    Vẽ overlay và hiển thị kết quả AI.
    """

    display = draw_overlay(

        frame=frame,

        persons=result.persons,

        polygon=result.polygon,

        occupancy=(
            components.occupancy
        ),

        temperature_c=(
            result.temperature_c
        ),

        fan=(
            components.fan
        ),

        actuator=(
            components.actuator
        ),

        now=result.now,
    )


    cv2.imshow(
        "Smart Home Occupancy + MQTT Fan",
        display,
    )


    return user_requested_exit()


# ============================================================
# RUN VIDEO LOOP
# ============================================================

def run_video_loop(
    args: argparse.Namespace,
    components: ApplicationComponents,
    roi_normalized: Optional[
        Sequence[Point]
    ],
) -> None:
    """
    Vòng lặp camera / YOLO chính.
    """

    track_kwargs = (
        build_track_kwargs(
            args
        )
    )


    while True:

        # ====================================================
        # READ FRAME
        # ====================================================

        frame = read_next_frame(
            components.capture
        )


        if frame is None:

            break


        # ====================================================
        # PROCESS AI
        # ====================================================

        result = process_frame(

            frame=frame,

            components=components,

            track_kwargs=track_kwargs,

            roi_normalized=(
                roi_normalized
            ),
        )


        # ====================================================
        # DISPLAY
        # ====================================================

        if (
            args.show
            and show_result(
                frame,
                components,
                result,
            )
        ):

            break


# ============================================================
# SHUTDOWN APPLICATION
# ============================================================

def shutdown_application(
    components: ApplicationComponents,
) -> None:
    """
    Dừng hệ thống theo thứ tự:

        1. Yêu cầu quạt OFF
        2. Dừng MQTT
        3. Release camera
        4. Đóng cửa sổ OpenCV
    """

    try:

        # Gateway vẫn phải còn hoạt động
        # khi actuator gửi lệnh OFF.
        components.actuator.close()


    finally:

        try:

            components.gateway.stop()


        finally:

            components.capture.release()

            cv2.destroyAllWindows()
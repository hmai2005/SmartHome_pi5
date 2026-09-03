"""Cấu hình thuật toán, MQTT và điều khiển quạt."""

from dataclasses import dataclass
from typing import Optional


# ============================================================
# OCCUPANCY / YOLO
# ============================================================
@dataclass(frozen=True)
class OccupancyConfig:
    """Các tham số xác nhận track và ổn định số người."""
    # Bounding box phải xuất hiện ít nhất 2 frame
    # mới xác nhận là một người.
    confirm_hits: int = 2
    # Khoảng thời gian tối đa để tích lũy đủ số frame xác nhận.
    confirm_window_s: float = 0.35
    # Confidence tối thiểu của detection.
    confirm_confidence: float = 0.30
    # Khi track bị mất tạm thời, vẫn giữ người trong 0.8 giây.
    missing_grace_s: float = 0.80
    # Số người phải ổn định 0.15 giây trước khi tăng.
    rise_hold_s: float = 0.15
    # Số người phải ổn định 0.45 giây trước khi giảm.
    fall_hold_s: float = 0.45
    # Track mất quá 3 giây sẽ bị xóa khỏi bộ nhớ.
    stale_track_ttl_s: float = 3.0
    # Cho phép liên kết lại track cũ trong vòng 1 giây.
    relink_max_age_s: float = 1.0
    # Khoảng cách tối đa để xem detection mới là người cũ.
    relink_distance_ratio: float = 0.08

# ============================================================
# FAN STATE MACHINE
# ============================================================
@dataclass(frozen=True)
class FanConfig:
    """
    Cấu hình máy trạng thái của quạt.
    Mức quạt mong muốn được quyết định bởi Fuzzy Logic.
    FanConfig chỉ chịu trách nhiệm về timing và chống đổi cấp quá nhanh.
    """
    # Khi Fuzzy yêu cầu tăng cấp, yêu cầu đó phải tồn tại ít nhất 0.5 giây.
    increase_hold_s: float = 0.50
    # Khi Fuzzy yêu cầu giảm cấp, yêu cầu đó phải tồn tại ít nhất 3 giây.
    decrease_hold_s: float = 3.0
    # Khi không còn người trong phòng, chờ 8 giây rồi mới tắt quạt.
    vacancy_off_delay_s: float = 8.0
    # Khoảng thời gian tối thiểu giữa hai lần đổi cấp.
    min_switch_interval_s: float = 1.0
# ============================================================
# FUZZY FAN CONTROLLER
# ============================================================
@dataclass(frozen=True)
class FuzzyFanConfig:
    """
    Cấu hình bộ điều khiển Fuzzy.
    Inputs:
        1. Temperature
        2. People Count
    Output:
        Fuzzy Fan Score
    """
    # ========================================================
    # TEMPERATURE MEMBERSHIP FUNCTIONS
    # ========================================================
    # COOL:
    # μ = 1 khi T <= 24°C
    # giảm tuyến tính về 0 tại 27°C.
    temp_cool_full_until_c: float = 24.0
    temp_cool_zero_at_c: float = 27.0
    # COMFORTABLE:
    # Hàm tam giác:
    # 24°C ------ 27.5°C ------ 31°C
    #  0             1            0
    temp_comfortable_left_c: float = 24.0
    temp_comfortable_peak_c: float = 27.5
    temp_comfortable_right_c: float = 31.
    # WARM:
    # Hàm tam giác:
    # 28.5°C ----- 31.5°C ----- 34.5°C
    #   0             1            0
    temp_warm_left_c: float = 28.5
    temp_warm_peak_c: float = 31.5
    temp_warm_right_c: float = 34.5
    # HOT:
    # μ = 0 khi T <= 32°C
    # μ = 1 khi T >= 35°C.
    temp_hot_zero_until_c: float = 32.0
    temp_hot_full_from_c: float = 35.0
    # ========================================================
    # PEOPLE MEMBERSHIP FUNCTIONS
    # ========================================================
    # FEW:
    # <= 2 người: μ = 1
    # từ 2 -> 4: μ giảm dần về 0.
    people_few_full_until: float = 2.0
    people_few_zero_at: float = 4.0
    # MEDIUM:
    # Hàm tam giác:
    # 2 -------- 4 -------- 6
    # 0          1          0
    people_medium_left: float = 2.0
    people_medium_peak: float = 4.0
    people_medium_right: float = 6.0
    # MANY:
    # <= 4: μ = 0
    # >= 6: μ = 1
    people_many_zero_until: float = 4.0
    people_many_full_from: float = 6.0
    # ========================================================
    # SUGENO OUTPUT: 
    # ========================================================
    # Singleton outputs.
    low_output: float = 1.0
    medium_output: float = 2.0
    high_output: float = 3.0
    # ========================================================
    # FUZZY SCORE -> PHYSICAL FAN LEVEL
    # ========================================================
    # Score dưới 1.5: Level 1.
    # Score từ 1.5 đến dưới 2.5: Level 2.
    # Score >= 2.5: Level 3.
    level_1_to_2_boundary: float = 1.5
    level_2_to_3_boundary: float = 2.5
    # ========================================================
    # OUTPUT HYSTERESIS
    # ========================================================
    # Hysteresis được áp dụng trực tiếp lên Fuzzy Score để tránh quạt nhảy liên tục giữa hai cấp.
    level_hysteresis: float = 0.10 #được thêm vào các mức score
# ============================================================
# MQTT
# ============================================================
@dataclass(frozen=True)
class MqttConfig:
    """Cấu hình MQTT giữa máy AI, broker và ESP32."""
    # HiveMQ Cloud: chỉ dùng hostname, không thêm mqtt:// vào trước URL.
    host: str = "caebe80fc31544bab129c40f7b5d3425.s1.eu.hivemq.cloud"
    # HiveMQ Cloud yêu cầu MQTT over TLS trên cổng 8883.
    port: int = 8883
    tls: bool = True
    # Client ID của chương trình AI.
    client_id: str = "smart-home-ai-controller"
    # Tài khoản HiveMQ Cloud dùng để xác thực kết nối.
    username: Optional[str] = "SmartHomeApp"
    password: Optional[str] = "12345678"
    # Gửi ping để giữ kết nối MQTT.
    keepalive_s: int = 60  #60s
    # Timeout khi kết nối Broker.
    connect_timeout_s: float = 5.0
    # ========================================================
    # MQTT TOPICS
    # ========================================================
    # AI -> ESP32: gửi lệnh điều khiển quạt.
    command_topic: str = "smart-home/fan/command"
    # ESP32 -> AI: trạng thái thực tế của quạt.
    state_topic: str = "smart-home/fan/state"
    # ESP32 availability.
    availability_topic: str = "smart-home/fan/availability"
    # ========================================================
    # SENSOR DATA: ESP32 -> MQTT
    # ========================================================
    temperature_topic: str = "smart-home/sensor/temperature"
    humidity_topic: str = "smart-home/sensor/humidity"
    rain_topic: str = "smart-home/sensor/rain"
    # ----------------------------
    # MQTT TOPICS - ACTUATOR STATE
    # ----------------------------
    led_state_topic: str = "smart-home/led/state"
    servo_retracted_topic: str = "smart-home/servo/retracted"
    # AI -> ESP32: số người ổn định từ camera.
    person_count_topic: str = "smart-home/ai/person_count"
    # ========================================================
    # MQTT DELIVERY
    # ========================================================
    # QoS 1:
    # bản tin được đảm bảo gửi ít nhất một lần.
    qos: int = 1

    # Broker giữ command gần nhất.
    retain_command: bool = True

    # Nếu cấp quạt không thay đổi,
    # vẫn gửi lại định kỳ để ESP32 biết controller còn hoạt động.
    command_refresh_s: float = 10.0

    # Nếu gửi command nhưng không nhận được state tương ứng
    # trong 3 giây -> ACK TIMEOUT.
    acknowledgement_timeout_s: float = 3.0
# Smart Home AI – YOLO11, MQTT và ESP32 điều khiển quạt 3 cấp

Hệ thống được chia thành hai thiết bị:

1. **Máy AI** chạy YOLO11, ổn định số người, đọc nhiệt độ và quyết định cấp quạt.
2. **ESP32** nhận cấp quạt bằng MQTT, điều khiển relay/PWM và gửi phản hồi trạng thái đã áp dụng.

## Kiến trúc

```text
Camera → YOLO11/Tracker → Stable occupancy → Fan controller
                                              │
                                              │ MQTT command
                                              ▼
Broker MQTT ───────────────────────────────► ESP32 → Relay/PWM → Quạt
    ▲                                           │
    └────────────── MQTT state/ACK ─────────────┘
```

## Cấu trúc dự án

```text
smart_home_ai_mqtt/
├── run.py
├── requirements.txt
├── README.md
├── smart_home_ai/
│   ├── config.py              # OccupancyConfig, FanConfig, MqttConfig
│   ├── mqtt_gateway.py        # Kết nối/publish/subscribe MQTT
│   ├── actuator.py            # Gửi command và nhận ACK từ ESP32
│   ├── tracking.py            # YOLO11 + ByteTrack/BoT-SORT
│   ├── occupancy.py           # Lọc ổn định số người
│   ├── fan_controller.py      # Quyết định cấp quạt mục tiêu
│   ├── temperature.py         # Đọc nhiệt độ
│   ├── pipeline.py            # Ghép pipeline một frame
│   ├── application.py         # Vòng lặp camera và khởi tạo MQTT
│   ├── visualization.py       # Hiển thị target/applied/ACK
│   └── cli.py                 # Tham số camera và MQTT
├── esp32/
│   └── esp32_fan_mqtt.ino     # Firmware mẫu ESP32
└── tests/
    ├── test_occupancy.py
    ├── test_fan_controller.py
    └── test_mqtt_actuator.py
```

## MQTT topics

| Topic | Hướng | Nội dung |
|---|---|---|
| `smart-home/fan/command` | AI → ESP32 | Cấp quạt mục tiêu và `command_id` |
| `smart-home/fan/state` | ESP32 → AI | Cấp thực sự đã áp dụng và `command_id` ACK |
| `smart-home/fan/availability` | ESP32 → AI | `online` hoặc Last Will `offline` |

### Command

```json
{
  "schema": 1,
  "command_id": 42,
  "level": 2,
  "source": "smart-home-ai-controller",
  "sent_at_unix_ms": 1785722400000
}
```

### State/ACK

```json
{
  "schema": 1,
  "command_id": 42,
  "applied_level": 2,
  "device": "esp32-fan-controller"
}
```

Máy AI chỉ coi lệnh thành công khi `state.command_id` bằng command gần nhất và `applied_level` được ESP32 phản hồi sau khi điều khiển relay.

## Cài đặt máy AI

```bash
pip install -r requirements.txt
```

Có thể dùng broker MQTT trong LAN hoặc HiveMQ Cloud. Với HiveMQ Cloud,
Pi5 phải dùng TLS trên port `8883` và tài khoản của cluster.

## Chạy

```bash
python run.py \
  --source 0 \
  --model yolo11n.pt \
  --temperature 29 \
  --mqtt-host 192.168.1.10 \
  --show
```

Chạy Pi5 với HiveMQ Cloud (đây cũng là cấu hình mặc định của Pi5):

```bash
python run.py \
  --source 0 \
  --mqtt-host caebe80fc31544bab129c40f7b5d3425.s1.eu.hivemq.cloud \
  --mqtt-port 8883 \
  --mqtt-tls \
  --mqtt-username "Hien Mai" \
  --mqtt-password "12345678" \
  --show
```

`YOUR_CLUSTER_URL` là hostname trong HiveMQ Cloud, không thêm `mqtt://`.

Có tài khoản MQTT:

```bash
python run.py \
  --source 0 \
  --mqtt-host 192.168.1.10 \
  --mqtt-username smart_home \
  --mqtt-password YOUR_PASSWORD \
  --show
```

## ESP32

Mở `esp32/esp32_fan_mqtt.ino` trong Arduino IDE và cài:

- ESP32 board package
- PubSubClient
- ArduinoJson

Sau đó sửa:

- `WIFI_SSID`, `WIFI_PASSWORD`
- `MQTT_HOST`
- Các chân relay
- `RELAY_ACTIVE_LOW`

## Cơ chế an toàn

- Chỉ một relay tốc độ được bật tại một thời điểm.
- ESP32 tắt tất cả relay trước khi chuyển cấp (`break-before-make`).
- AI phát lại cấp quạt định kỳ 10 giây như heartbeat.
- ESP32 tắt quạt nếu 30 giây không nhận command mới.
- MQTT QoS 1 và `command_id` giúp phát hiện ACK thiếu hoặc sai lệnh.
- ESP32 dùng Last Will để broker báo `offline` khi mất kết nối bất thường.

## Kiểm thử

```bash
python -m unittest discover -s tests -v
```

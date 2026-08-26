#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>

// ===================== CẤU HÌNH WIFI / MQTT =====================
const char* WIFI_SSID = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";

const char* MQTT_HOST = "192.168.1.10";  // IP máy chạy Mosquitto
const uint16_t MQTT_PORT = 1883;
const char* MQTT_USERNAME = nullptr;
const char* MQTT_PASSWORD = nullptr;

const char* COMMAND_TOPIC = "smart-home/fan/command";
const char* STATE_TOPIC = "smart-home/fan/state";
const char* AVAILABILITY_TOPIC = "smart-home/fan/availability";

// ===================== PHẦN CỨNG QUẠT 3 CẤP =====================
// Ví dụ điều khiển ba relay. Chỉnh chân theo mạch thực tế.
constexpr uint8_t RELAY_LEVEL_1_PIN = 25;
constexpr uint8_t RELAY_LEVEL_2_PIN = 26;
constexpr uint8_t RELAY_LEVEL_3_PIN = 27;

// Nhiều module relay kích mức LOW. Đổi thành false nếu relay kích HIGH.
constexpr bool RELAY_ACTIVE_LOW = true;
constexpr uint32_t BREAK_BEFORE_MAKE_MS = 150;

// Máy AI phát lại command mỗi 10 giây. Nếu quá 30 giây không nhận command,
// ESP32 tắt quạt để tránh chạy mãi khi máy AI hoặc mạng gặp sự cố.
constexpr uint32_t COMMAND_WATCHDOG_MS = 30000;

WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

int currentFanLevel = 0;
uint32_t lastCommandId = 0;
uint32_t lastCommandReceivedMs = 0;

void writeRelay(uint8_t pin, bool enabled) {
  bool physicalLevel = RELAY_ACTIVE_LOW ? !enabled : enabled;
  digitalWrite(pin, physicalLevel ? HIGH : LOW);
}

void allRelaysOff() {
  writeRelay(RELAY_LEVEL_1_PIN, false);
  writeRelay(RELAY_LEVEL_2_PIN, false);
  writeRelay(RELAY_LEVEL_3_PIN, false);
}

bool applyFanLevel(int level) {
  if (level < 0 || level > 3) {
    return false;
  }

  // Không cho hai relay tốc độ đóng đồng thời.
  allRelaysOff();
  delay(BREAK_BEFORE_MAKE_MS);

  if (level == 1) writeRelay(RELAY_LEVEL_1_PIN, true);
  if (level == 2) writeRelay(RELAY_LEVEL_2_PIN, true);
  if (level == 3) writeRelay(RELAY_LEVEL_3_PIN, true);

  currentFanLevel = level;
  return true;
}

void publishAvailability(const char* status, bool retained = true) {
  StaticJsonDocument<96> document;
  document["status"] = status;

  char payload[96];
  serializeJson(document, payload, sizeof(payload));
  mqttClient.publish(AVAILABILITY_TOPIC, payload, retained);
}

void publishFanState(uint32_t commandId, const char* error = nullptr) {
  StaticJsonDocument<192> document;
  document["schema"] = 1;
  document["command_id"] = commandId;
  document["applied_level"] = currentFanLevel;
  document["device"] = "esp32-fan-controller";

  if (error != nullptr) {
    document["error"] = error;
  }

  char payload[192];
  serializeJson(document, payload, sizeof(payload));
  mqttClient.publish(STATE_TOPIC, payload, true);
}

void handleFanCommand(const byte* payload, unsigned int length) {
  StaticJsonDocument<256> document;
  DeserializationError error = deserializeJson(document, payload, length);

  if (error) {
    publishFanState(lastCommandId, "invalid_json");
    return;
  }

  if (!document["command_id"].is<uint32_t>() || !document["level"].is<int>()) {
    publishFanState(lastCommandId, "missing_command_id_or_level");
    return;
  }

  uint32_t commandId = document["command_id"].as<uint32_t>();
  int requestedLevel = document["level"].as<int>();

  if (!applyFanLevel(requestedLevel)) {
    publishFanState(commandId, "invalid_level");
    return;
  }

  lastCommandId = commandId;
  lastCommandReceivedMs = millis();

  // Chỉ ACK sau khi relay đã được điều khiển.
  publishFanState(commandId);
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  if (strcmp(topic, COMMAND_TOPIC) == 0) {
    handleFanCommand(payload, length);
  }
}

void connectWifi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}

void connectMqtt() {
  while (!mqttClient.connected()) {
    String clientId = "esp32-fan-" + String((uint32_t)ESP.getEfuseMac(), HEX);

    // Last Will: broker tự công bố offline nếu ESP32 mất kết nối bất thường.
    const char* willPayload = "{\"status\":\"offline\"}";

    bool connected;
    if (MQTT_USERNAME != nullptr) {
      connected = mqttClient.connect(
        clientId.c_str(),
        MQTT_USERNAME,
        MQTT_PASSWORD,
        AVAILABILITY_TOPIC,
        1,
        true,
        willPayload
      );
    } else {
      connected = mqttClient.connect(
        clientId.c_str(),
        AVAILABILITY_TOPIC,
        1,
        true,
        willPayload
      );
    }

    if (connected) {
      mqttClient.subscribe(COMMAND_TOPIC, 1);
      publishAvailability("online");
      publishFanState(lastCommandId);
    } else {
      delay(2000);
    }
  }
}

void setup() {
  pinMode(RELAY_LEVEL_1_PIN, OUTPUT);
  pinMode(RELAY_LEVEL_2_PIN, OUTPUT);
  pinMode(RELAY_LEVEL_3_PIN, OUTPUT);
  allRelaysOff();

  connectWifi();
  mqttClient.setServer(MQTT_HOST, MQTT_PORT);
  mqttClient.setCallback(mqttCallback);
  mqttClient.setBufferSize(512);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWifi();
  }

  if (!mqttClient.connected()) {
    connectMqtt();
  }

  mqttClient.loop();

  if (
    currentFanLevel != 0 &&
    millis() - lastCommandReceivedMs > COMMAND_WATCHDOG_MS
  ) {
    applyFanLevel(0);
    publishFanState(lastCommandId, "command_watchdog_timeout");
  }
}

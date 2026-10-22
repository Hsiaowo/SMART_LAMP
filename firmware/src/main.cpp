#include <Arduino.h>
#include <ArduinoJson.h>
#include <ESP8266HTTPClient.h>
#include <ESP8266WiFi.h>
#include <LittleFS.h>

#if __has_include("config.h")
#include "config.h"
#else
#include "config.example.h"
#endif
#include "wake_engine.h"

namespace {
constexpr uint32_t POLL_MS = 2000;
constexpr size_t MAX_JSON = 4096;
lamp::Plan plan;
std::string snapshotJson;
std::string completed;
uint32_t snapshotCrc = 0;
uint32_t generation = 0;
bool storageOk = false;
bool clockValid = false;
int64_t clockEpoch = 0;
uint32_t clockAnchor = 0;
uint32_t lastClockSync = 0;
uint32_t lastPoll = 0;
uint32_t lastReconnect = 0;
int activeSlot = 1;
String bootId;
String lastError;
String previousState;
lamp::Output output{"needs_time", 0};

int64_t nowMs() {
    return clockEpoch + static_cast<uint32_t>(millis() - clockAnchor);
}

bool parsePlan(const std::string& text, lamp::Plan& result) {
    StaticJsonDocument<1024> doc;
    if (deserializeJson(doc, text.c_str()) || doc["schema_version"].as<int>() != 1 ||
        !doc["version"].is<uint32_t>() || !doc["enabled"].is<bool>()) return false;
    result.version = doc["version"].as<uint32_t>();
    result.enabled = doc["enabled"].as<bool>();
    result.occurrence = doc["occurrence_id"].as<std::string>();
    result.rampStart = doc["ramp_start_ms"].as<int64_t>();
    result.wakeAt = doc["wake_at_ms"].as<int64_t>();
    result.holdUntil = doc["hold_until_ms"].as<int64_t>();
    result.peak = doc["peak_percent"].as<float>();
    return lamp::valid(result);
}

std::string journalInput(uint32_t gen, const std::string& raw, const std::string& done) {
    return std::string(String(gen).c_str()) + "\n" + raw + "\n" + done;
}

bool readSlot(int slot, uint32_t& gen, std::string& raw, std::string& done) {
    File file = LittleFS.open(slot == 0 ? "/state0.json" : "/state1.json", "r");
    if (!file || file.size() > MAX_JSON) return false;
    DynamicJsonDocument doc(MAX_JSON * 2);
    const auto error = deserializeJson(doc, file);
    file.close();
    if (error) return false;
    gen = doc["generation"].as<uint32_t>();
    raw = doc["snapshot_json"].as<std::string>();
    done = doc["completed"].as<std::string>();
    lamp::Plan candidate;
    return !raw.empty() && done.size() <= 100 && parsePlan(raw, candidate) &&
           doc["journal_crc32"].as<uint32_t>() == lamp::crc32(journalInput(gen, raw, done));
}

bool persist(const std::string& raw, const std::string& done) {
    if (!storageOk) return false;
    const int next = 1 - activeSlot;
    const uint32_t nextGeneration = generation + 1;
    StaticJsonDocument<2048> doc;
    doc["generation"] = nextGeneration;
    doc["snapshot_json"] = raw;
    doc["completed"] = done;
    doc["journal_crc32"] = lamp::crc32(journalInput(nextGeneration, raw, done));
    File file = LittleFS.open(next == 0 ? "/state0.json" : "/state1.json", "w");
    if (!file) return false;
    const size_t written = serializeJson(doc, file);
    file.flush();
    file.close();
    uint32_t checkedGen = 0;
    std::string checkedRaw, checkedDone;
    if (!written || !readSlot(next, checkedGen, checkedRaw, checkedDone) ||
        checkedGen != nextGeneration || checkedRaw != raw || checkedDone != done) return false;
    activeSlot = next;
    generation = nextGeneration;
    return true;
}

void loadStorage() {
    storageOk = LittleFS.begin();
    if (!storageOk) { lastError = "filesystem_mount_failed"; return; }
    for (int slot = 0; slot < 2; ++slot) {
        uint32_t gen = 0;
        std::string raw, done;
        if (readSlot(slot, gen, raw, done) && (snapshotJson.empty() || gen > generation)) {
            generation = gen;
            activeSlot = slot;
            snapshotJson = raw;
            completed = done;
            snapshotCrc = lamp::crc32(raw);
            parsePlan(raw, plan);
        }
    }
}

void tick() {
    output = storageOk ? lamp::evaluate(plan, nowMs(), clockValid, completed)
                       : lamp::Output{"fault", 0};
    if (String(output.state) == "done" && plan.enabled && completed != plan.occurrence) {
        if (persist(snapshotJson, plan.occurrence)) completed = plan.occurrence;
        else { storageOk = false; lastError = "completion_save_failed"; output = {"fault", 0}; }
    }
    const int pwm = constrain(static_cast<int>(output.brightness * 1023.0f / 100.0f), 0, 1023);
    analogWrite(LAMP_LED_PIN, LAMP_LED_ACTIVE_LOW ? 1023 - pwm : pwm);
    if (previousState != output.state) {
        previousState = output.state;
        Serial.printf("state=%s brightness=%.1f version=%lu\n", output.state,
                      output.brightness, static_cast<unsigned long>(plan.version));
    }
}

void syncDevice() {
    if (WiFi.status() != WL_CONNECTED) return;
    StaticJsonDocument<512> report;
    report["boot_id"] = bootId;
    report["ack_version"] = plan.version;
    report["ack_crc32"] = snapshotCrc;
    report["state"] = output.state;
    report["brightness"] = output.brightness;
    report["clock_valid"] = clockValid;
    report["storage_ok"] = storageOk;
    report["completed_occurrence_id"] = completed;
    report["last_error"] = lastError;
    String body;
    serializeJson(report, body);
    WiFiClient client;
    HTTPClient http;
    http.setTimeout(500);
    if (!http.begin(client, String(SERVER_URL) + "/api/v1/devices/" + DEVICE_ID + "/sync")) return;
    http.addHeader("Content-Type", "application/json");
    http.addHeader("Authorization", String("Bearer ") + DEVICE_TOKEN);
    const uint32_t started = millis();
    const int code = http.POST(body);
    if (code != 200) {
        lastError = String("http_") + code;
        http.end();
        return;
    }
    if (http.getSize() > static_cast<int>(MAX_JSON)) {
        lastError = "response_too_large";
        http.end();
        return;
    }
    String text = http.getString();
    http.end();
    if (text.length() > MAX_JSON) { lastError = "response_too_large"; return; }
    DynamicJsonDocument reply(MAX_JSON * 2);
    if (deserializeJson(reply, text)) { lastError = "invalid_response"; return; }
    const int64_t serverTime = reply["server_time_ms"].as<int64_t>();
    if (serverTime < 1700000000000LL || serverTime > 4102444800000LL) {
        lastError = "invalid_server_time";
        return;
    }
    const bool running = String(output.state) == "ramping" || String(output.state) == "holding";
    if (!clockValid || (!running && millis() - lastClockSync > 600000)) {
        clockEpoch = serverTime + static_cast<uint32_t>(millis() - started) / 2;
        clockAnchor = millis();
        lastClockSync = millis();
        clockValid = true;
    }
    const std::string raw = reply["snapshot_json"].as<std::string>();
    const uint32_t crc = reply["snapshot_crc32"].as<uint32_t>();
    lamp::Plan candidate;
    if (lamp::crc32(raw) != crc || !parsePlan(raw, candidate)) {
        lastError = "snapshot_validation_failed";
        return;
    }
    if (candidate.version < plan.version ||
        (candidate.version == plan.version && !snapshotJson.empty() && crc != snapshotCrc)) {
        lastError = "server_version_conflict";
        return;
    }
    if (snapshotJson.empty() || candidate.version > plan.version) {
        if (!persist(raw, completed)) { lastError = "snapshot_save_failed"; return; }
        plan = candidate;
        snapshotJson = raw;
        snapshotCrc = crc;
    }
    lastError = "";
}
}  // namespace

void setup() {
    // Active-low built-in LEDs must be driven HIGH before enabling the output.
    digitalWrite(LAMP_LED_PIN, LAMP_LED_ACTIVE_LOW ? HIGH : LOW);
    pinMode(LAMP_LED_PIN, OUTPUT);
    analogWriteRange(1023);
    analogWriteFreq(1000);  // Test diode, not the future TPS923611 driver.
    Serial.begin(115200);
    bootId = String(ESP.getChipId(), HEX) + "-" + String(ESP.getCycleCount(), HEX);
    loadStorage();
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoReconnect(true);
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
    Serial.println("Smart Lamp MVP: Wi-Fi connecting; output remains off until time is valid.");
    tick();
}

void loop() {
    tick();
    const uint32_t current = millis();
    if (current - lastPoll >= POLL_MS) {
        lastPoll = current;
        syncDevice();
        tick();
    }
    if (WiFi.status() != WL_CONNECTED && current - lastReconnect >= 15000) {
        lastReconnect = current;
        WiFi.reconnect();
    }
    delay(20);
}

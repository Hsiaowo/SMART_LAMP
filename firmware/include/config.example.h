#pragma once

// Copy to config.h, or run python -m scripts.bootstrap to generate a local copy.
// Never publish config.h: it contains Wi-Fi credentials and the device token.
constexpr char WIFI_SSID[] = "YOUR_2_4_GHZ_WIFI";
constexpr char WIFI_PASSWORD[] = "YOUR_WIFI_PASSWORD";
constexpr char SERVER_URL[] = "http://192.168.1.100:8765";
constexpr char DEVICE_ID[] = "lamp-a";
constexpr char DEVICE_TOKEN[] = "REPLACE_WITH_DEVICE_TOKEN";

// Most NodeMCU / D1 mini boards: built-in LED is GPIO2, active LOW.
// An external LED needs its own series resistor; use GPIO14 and active LOW=false.
constexpr uint8_t LAMP_LED_PIN = 2;
constexpr bool LAMP_LED_ACTIVE_LOW = true;


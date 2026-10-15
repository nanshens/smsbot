#pragma once

// Copy to config.local.h. Never commit real credentials.
static const char WIFI_SSID[] = "REPLACE_WIFI_SSID";
static const char WIFI_PASSWORD[] = "REPLACE_WIFI_PASSWORD";
static const char PLATFORM_URL[] = "https://sms.example.com"; // no trailing slash or /api
static const char PHONE_API_KEY[] = "REPLACE_PHONE_API_KEY";
static const char DEVICE_NAME[] = "LILYGO SIM 01";
// PEM CA certificate for PLATFORM_URL. Never disable TLS verification.
static const char ROOT_CA[] = R"PEM(
-----BEGIN CERTIFICATE-----
REPLACE_WITH_CA_CERTIFICATE
-----END CERTIFICATE-----
)PEM";

// Ordinary T-SIM7670G-S3 only, NOT the Standard board.
static constexpr int MODEM_TX = 11; // ESP TX -> modem RX
static constexpr int MODEM_RX = 10; // ESP RX <- modem TX
static constexpr int MODEM_PWRKEY = 18;
static constexpr int MODEM_RESET = 17;
static constexpr int MODEM_DTR = 9;

#pragma once
#include <Arduino.h>
#include <vector>

// Always use UCS2 so part boundaries and estimated costs match the web UI.
bool ucs2Parts(const String &text, std::vector<String> &hexParts);
String submitPdu(const String &number, const String &ucs2hex, int reference, int total, int part);
String smsTimestamp(const String &pdu);

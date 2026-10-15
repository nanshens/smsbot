#include "sms_codec.h"

static String byteHex(unsigned value) { char b[3]; snprintf(b, sizeof(b), "%02X", value & 255); return String(b); }
static int byteAt(const String &s, int offset) { return strtol(s.substring(offset, offset + 2).c_str(), nullptr, 16); }

bool ucs2Parts(const String &text, std::vector<String> &parts) {
  std::vector<unsigned> chars;
  for (size_t i = 0; i < text.length();) {
    unsigned c = (uint8_t)text[i++];
    if (c >= 0xC2 && c <= 0xDF) {
      if (i >= text.length() || ((uint8_t)text[i] & 0xC0) != 0x80) return false;
      c = ((c & 31) << 6) | ((uint8_t)text[i++] & 63);
    } else if (c >= 0xE0 && c <= 0xEF) {
      if (i + 1 >= text.length() || ((uint8_t)text[i] & 0xC0) != 0x80 || ((uint8_t)text[i+1] & 0xC0) != 0x80) return false;
      c = ((c & 15) << 12) | (((uint8_t)text[i] & 63) << 6) | ((uint8_t)text[i+1] & 63); i += 2;
      if (c < 0x800) return false;
    } else if (c >= 0x80) return false;
    if (!c || (c >= 0xD800 && c <= 0xDFFF)) return false;
    chars.push_back(c);
  }
  if (chars.empty() || chars.size() > 670) return false;
  const size_t chunk = chars.size() <= 70 ? 70 : 67;
  for (size_t i = 0; i < chars.size(); i += chunk) {
    String hex;
    for (size_t j = i; j < chars.size() && j < i + chunk; ++j) hex += byteHex(chars[j] >> 8) + byteHex(chars[j]);
    parts.push_back(hex);
  }
  return true;
}

String submitPdu(const String &number, const String &ucs2, int reference, int total, int part) {
  bool international = number.startsWith("+");
  String digits = international ? number.substring(1) : number;
  if (digits.length() < 3 || digits.length() > 20) return "";
  for (size_t i=0; i<digits.length(); ++i) if (!isDigit(digits[i])) return "";
  unsigned length = digits.length();
  if (length % 2) digits += 'F';
  String address;
  for (size_t i=0; i<digits.length(); i+=2) { address += digits[i+1]; address += digits[i]; }
  String header = total > 1 ? "050003" + byteHex(reference) + byteHex(total) + byteHex(part) : "";
  return "00" + String(total > 1 ? "41" : "01") + "00" + byteHex(length) +
         (international ? "91" : "81") + address + "0008" + byteHex((header.length()+ucs2.length())/2) + header + ucs2;
}

String smsTimestamp(const String &pdu) {
  if (pdu.length() < 6) return "";
  int pos = 2 + byteAt(pdu,0)*2;
  if (pos+6 >= (int)pdu.length() || (byteAt(pdu,pos)&3) != 0) return "";
  int digits = byteAt(pdu,pos+2);
  pos += 6 + ((digits+1)/2)*2 + 4; // first octet, address, PID, DCS
  if (pos+14 > (int)pdu.length()) return "";
  int values[6];
  for (int i=0;i<6;i++) { int b=byteAt(pdu,pos+i*2); values[i]=(b&15)*10+(b>>4); }
  int zone=byteAt(pdu,pos+12), quarters=(zone&7)*10+(zone>>4);
  char output[40];
  snprintf(output,sizeof(output),"20%02d-%02d-%02dT%02d:%02d:%02d%c%02d:%02d",values[0],values[1],values[2],values[3],values[4],values[5],zone&8?'-':'+',quarters/4,(quarters%4)*15);
  return String(output);
}

#include <Arduino.h>
#include <ArduinoJson.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>
#include <LittleFS.h>
#include <Preferences.h>
#include <pdulib.h>
#include <time.h>
#include <mbedtls/sha256.h>
#include "sms_codec.h"
#if __has_include("config.local.h")
#include "config.local.h"
#define SMSBOT_CONFIG_SOURCE "config.local.h"
#else
#include "config.example.h"
#define SMSBOT_CONFIG_SOURCE "config.example.h (template)"
#endif

HardwareSerial modem(1);
Preferences preferences;
PDU decoder(2048);
JsonDocument inbox, outgoing, identity;
String iccid, lastError;
bool storageFault = false, ready = false;
unsigned long nextNetwork = 0, nextScan = 0, nextHeartbeat = 0, nextPoll = 0, nextModem = 0;
unsigned pollMs = 1000, heartbeatMs = 30000, backoff = 1000;
int lastHttpStatus = 0;

void printStatus() {
  static unsigned long previous=0;
  if(millis()-previous<5000 || !Serial) return;
  previous=millis();
  Serial.println("[config] " SMSBOT_CONFIG_SOURCE);
  Serial.printf("[status] uptime=%lus storage=%s modem=%s wifi=%s ntp=%s activated=%s http=%d\n",
      millis()/1000, storageFault?"ERROR":"ok", ready?"ready":"waiting",
      WiFi.status()==WL_CONNECTED?"connected":"disconnected",
      time(nullptr)>=1700000000?"ready":"waiting",
      identity["device_id"].is<String>()?"yes":"no",lastHttpStatus);
  if(lastError.length()) Serial.println("[last-error] "+lastError);
}

// Use the SMS service-centre clock: NTP may jump after an offline boot.
time_t messageTime(const String &stamp) {
  int y,m,d,h,n,s,zh,zm; char sign;
  if(sscanf(stamp.c_str(),"%d-%d-%dT%d:%d:%d%c%d:%d",&y,&m,&d,&h,&n,&s,&sign,&zh,&zm)!=9 ||
     y<2000 || m<1 || m>12 || d<1 || d>31 || h>23 || n>59 || s>59 ||
     (sign!='+' && sign!='-') || zh>23 || zm>59) return 0;
  struct tm value={}; value.tm_year=y-1900; value.tm_mon=m-1; value.tm_mday=d;
  value.tm_hour=h; value.tm_min=n; value.tm_sec=s;
  return mktime(&value)-(sign=='+'?1:-1)*(zh*3600+zm*60);
}

bool sameMessageWindow(const String &a,const String &b) {
  time_t first=messageTime(a),second=messageTime(b);
  return first>0 && second>0 && llabs((long long)first-second)<600;
}

String uuid() {
  char output[37]; uint8_t bytes[16]; esp_fill_random(bytes, sizeof(bytes));
  bytes[6] = (bytes[6]&15)|64; bytes[8] = (bytes[8]&63)|128;
  snprintf(output,sizeof(output),"%02x%02x%02x%02x-%02x%02x-%02x%02x-%02x%02x-%02x%02x%02x%02x%02x%02x",bytes[0],bytes[1],bytes[2],bytes[3],bytes[4],bytes[5],bytes[6],bytes[7],bytes[8],bytes[9],bytes[10],bytes[11],bytes[12],bytes[13],bytes[14],bytes[15]);
  return String(output);
}

String hash(const String &value) {
  unsigned char digest[32]; mbedtls_sha256_ret((const unsigned char*)value.c_str(),value.length(),digest,0);
  String result; char b[3]; for(unsigned char v:digest) { snprintf(b,sizeof(b),"%02x",v); result+=b; } return result;
}

bool save(const char *path, JsonDocument &doc) {
  if (storageFault) return false;
  String tmp=String(path)+".tmp";
  File file=LittleFS.open(tmp,"w");
  size_t expected=measureJson(doc);
  if (!file || serializeJson(doc,file)!=expected) { storageFault=true; lastError="Persistent queue write failed"; return false; }
  file.flush(); file.close();
  if (!LittleFS.rename(tmp,path)) { storageFault=true; lastError="Persistent queue commit failed"; return false; }
  return true;
}

bool load(const char *path, JsonDocument &doc) {
  if (!LittleFS.exists(path)) return true;
  File file=LittleFS.open(path,"r");
  if (!file || deserializeJson(doc,file)) { storageFault=true; lastError="Queue is corrupt; preserve filesystem for recovery"; return false; }
  return true;
}

String response(unsigned timeout=3000, bool prompt=false) {
  String result; unsigned long start=millis();
  while (millis()-start<timeout) {
    while(modem.available()) {
      char c=modem.read(); result+=c;
      if (prompt && c=='>') return result;
      if (result.endsWith("\r\nOK\r\n") || result.endsWith("\r\nERROR\r\n") ||
          ((result.indexOf("+CMS ERROR:")>=0 || result.indexOf("+CME ERROR:")>=0) && result.endsWith("\r\n"))) return result;
      if (result.length()>32768) { lastError="Modem listing truncated; remaining SMS retained for next scan"; return result; }
    }
    delay(2);
  }
  return result;
}

String command(const String &cmd, unsigned timeout=3000, bool prompt=false) {
  while(modem.available()) modem.read(); // URCs aren't relied on; scan persistent SIM storage.
  modem.print(cmd); modem.print("\r"); return response(timeout,prompt);
}

String readIccid() {
  // SIM767XX documents AT+CICCID; retain alternatives for modem revisions.
  const char *queries[]={"AT+CICCID","AT+ICCID","AT+CCID"};
  for(const char *query:queries) {
    String answer=command(query,6000); // Manual allows up to 5 seconds.
    if(answer.indexOf("\r\nOK\r\n")<0) continue;
    String digits;
    for(size_t i=0;i<=answer.length();++i) {
      char c=i<answer.length()?answer[i]:'\n';
      if(isDigit(c)) digits+=c;
      else { if(digits.length()>=10 && digits.length()<=32) return digits; digits=""; }
    }
  }
  return "";
}

bool initializeModem() {
  if (command("AT",1000).indexOf("OK")<0) {
    digitalWrite(MODEM_PWRKEY,LOW); delay(100); digitalWrite(MODEM_PWRKEY,HIGH); delay(1000); digitalWrite(MODEM_PWRKEY,LOW);
    delay(5000);
    if (command("AT",2000).indexOf("OK")<0) { lastError="Modem did not respond to AT"; return false; }
  }
  command("ATE0"); command("AT+CMEE=2"); command("AT+CSCLK=0");
  if (command("AT+CPIN?").indexOf("READY")<0) { lastError="SIM not ready (check PIN/card)"; return false; }
  if (command("AT+CMGF=0").indexOf("OK")<0 || command("AT+CPMS=\"SM\",\"SM\",\"SM\"").indexOf("OK")<0) { lastError="Modem SMS mode/storage setup failed"; return false; }
  command("AT+CNMI=2,1,0,0,0");
  iccid=readIccid();
  if(iccid.length()<10) lastError="Cannot read SIM ICCID";
  else lastError="";
  return iccid.length()>=10;
}

int api(const String &path, JsonDocument &body, JsonDocument &result, bool authenticated=true) {
  if (WiFi.status()!=WL_CONNECTED || time(nullptr)<1700000000) return -1;
  WiFiClientSecure client; client.setCACert(ROOT_CA);
  HTTPClient http; http.setConnectTimeout(5000); http.setTimeout(8000);
  if (!http.begin(client,String(PLATFORM_URL)+"/api"+path)) return -1;
  http.addHeader("Content-Type","application/json");
  if(authenticated) http.addHeader("Authorization","Bearer "+identity["api_key"].as<String>());
  String payload; serializeJson(body,payload); int status=http.POST(payload);
  if(status>=200 && status<300 && status!=204) {
    if (deserializeJson(result,http.getStream())) status=-2;
  }
  http.end();
  lastHttpStatus=status;
  if (status>=200 && status<300) backoff=1000;
  else { backoff=min(backoff*2,60000U); nextNetwork=millis()+backoff+esp_random()%500; }
  if(status==401 || status==409) lastError="Platform rejected device identity/SIM; check phone API key";
  return status;
}

bool persistIdentity() {
  String serialized; serializeJson(identity,serialized);
  if(preferences.putString("identity",serialized)!=serialized.length()) { storageFault=true; lastError="NVS credential write failed"; return false; }
  return true;
}

bool registerDevice() {
  JsonDocument body,result;
  body["hardware_id"]=WiFi.macAddress(); body["iccid"]=iccid;
  body["firmware_version"]="0.2.0"; body["modem_version"]="SIM7670G";
  identity["api_key"]=PHONE_API_KEY;
  if(api("/device/activate",body,result)!=200) return false;
  identity["device_id"]=result["device_id"]; identity["iccid"]=iccid;
  identity["configured_key_hash"]=hash(PHONE_API_KEY); identity.remove("registration");
  pollMs=max(1000U,result["poll_interval_ms"].as<unsigned>());
  heartbeatMs=max(10000U,result["heartbeat_interval_ms"].as<unsigned>());
  Serial.println("Device activated with permanent phone API key");
  return persistIdentity();
}

bool validPdu(String &raw) {
  raw.trim(); raw.toUpperCase();
  if(raw.length()<30 || raw.length()>512 || raw.length()%2) return false;
  for(size_t i=0;i<raw.length();i++) if(!isxdigit(raw[i])) return false;
  return true;
}

void ingest(int slot, String raw) {
  if(!validPdu(raw) || storageFault) return;
  JsonArray groups=inbox["groups"].as<JsonArray>();
  for(JsonObject group:groups) for(JsonObject part:group["parts"].as<JsonArray>()) {
    if(part["slot"].as<int>()==slot && part["raw"].as<String>()==raw && group["iccid"].as<String>()==iccid) return;
  }
  if(!decoder.decodePDU(raw.c_str()) || decoder.getOverflow()) { lastError="Unsupported or malformed SMS retained on SIM"; return; }
  int *concat=decoder.getConcatInfo(); int number=concat[1],total=concat[2],reference=concat[0];
  if(number==0 || total==0) { number=1; total=1; }
  if(total>32 || number>total || number<1) { lastError="SMS multipart count unsupported; retained on SIM"; return; }
  String sender=decoder.getSender(), stamp=smsTimestamp(raw), text=decoder.getText();
  JsonObject target;
  for(JsonObject group:groups) {
    // Reference numbers can wrap. Limit the grouping window and never overwrite an occupied part.
    if(total>1 && !group["acked"].as<bool>() && group["sender"].as<String>()==sender && group["iccid"].as<String>()==iccid &&
        group["reference"].as<int>()==reference && group["total"].as<int>()==total && sameMessageWindow(stamp,group["timestamp"].as<String>())) {
      bool occupied=false;
      for(JsonObject part:group["parts"].as<JsonArray>()) if(part["number"].as<int>()==number) occupied=true;
      if(!occupied) { target=group; break; }
    }
  }
  if(target.isNull()) {
    if(groups.size()>=64 || LittleFS.totalBytes()-LittleFS.usedBytes()<65536) { lastError="Local inbox full; messages retained on SIM"; return; }
    target=groups.add<JsonObject>(); target["event_id"]=uuid(); target["iccid"]=iccid;
    target["sender"]=sender; target["timestamp"]=stamp; target["reference"]=reference; target["total"]=total;
    target["seen"]=(long)time(nullptr); target["parts"].to<JsonArray>(); target["acked"]=false;
  }
  JsonObject part=target["parts"].as<JsonArray>().add<JsonObject>();
  part["slot"]=slot; part["raw"]=raw; part["text"]=text; part["number"]=number;
  save("/inbox.json",inbox);
}

void scanInbox() {
  String answer=command("AT+CMGL=4",10000);
  int cursor=0, slot=-1;
  while(cursor<(int)answer.length()) {
    int end=answer.indexOf('\n',cursor); if(end<0) break;
    String line=answer.substring(cursor,end); line.trim(); cursor=end+1;
    if(line.startsWith("+CMGL:")) slot=line.substring(6).toInt();
    else if(slot>=0 && line.length()) { ingest(slot,line); slot=-1; }
  }
}

String rawAt(int slot) {
  String answer=command("AT+CMGR="+String(slot)); int header=answer.indexOf("+CMGR:");
  if(header<0) return answer.indexOf("+CMS ERROR: 321")>=0 ? "" : "!retry";
  int start=answer.indexOf('\n',header)+1, end=answer.indexOf('\n',start);
  if(start<1 || end<0) return "!retry";
  String raw=answer.substring(start,end); raw.trim(); raw.toUpperCase(); return raw;
}

void uploadInbox() {
  JsonArray groups=inbox["groups"].as<JsonArray>();
  for(size_t i=0;i<groups.size();++i) {
    JsonObject group=groups[i]; if(group["iccid"].as<String>()!=iccid) continue;
    if(group["parts"].size()!=group["total"].as<size_t>()) {
      if(time(nullptr)-group["seen"].as<long>()>600) lastError="Incomplete multipart SMS retained for recovery";
      continue;
    }
    if(!group["acked"].as<bool>()) {
      JsonDocument body,result; body["event_id"]=group["event_id"]; body["iccid"]=iccid; body["sender"]=group["sender"];
      String content;
      for(int n=1;n<=group["total"].as<int>();n++) for(JsonObject part:group["parts"].as<JsonArray>()) if(part["number"].as<int>()==n) content+=part["text"].as<String>();
      if(content.length()>16000) { lastError="Multipart SMS exceeds platform limit"; continue; }
      body["body"]=content;
      String stamp=group["timestamp"].as<String>(); if(stamp.length()) body["modem_received_at"]=stamp;
      if(api("/device/incoming",body,result)!=200) return;
      group["acked"]=true; if(!save("/inbox.json",inbox)) return;
    }
    bool cleaned=true;
    for(JsonObject part:group["parts"].as<JsonArray>()) {
      // Avoid deleting a new SMS that reused the old storage index.
      String current=rawAt(part["slot"].as<int>());
      if(current=="!retry") { cleaned=false; continue; }
      if(current==part["raw"].as<String>()) {
        if(command("AT+CMGD="+String(part["slot"].as<int>())).indexOf("OK")<0) cleaned=false;
      }
    }
    if(cleaned) { groups.remove(i); save("/inbox.json",inbox); }
    return; // one message per loop, keep polling responsive
  }
}

void reportOutgoing() {
  if(!outgoing["result"].is<JsonObject>()) return;
  if(outgoing["iccid"].as<String>()!=iccid) { lastError="Old SIM has pending send result; restore card before re-pairing"; return; }
  JsonDocument body,result; body.set(outgoing["result"]);
  body["iccid"]=iccid; body["attempt_id"]=outgoing["attempt_id"]; body["lease_token"]=outgoing["lease_token"];
  int status=api("/device/outgoing/"+outgoing["id"].as<String>()+"/result",body,result);
  if(status==200) { outgoing.clear(); save("/outgoing.json",outgoing); }
}

void performSend() {
  std::vector<String> parts;
  JsonObject result=outgoing["result"].to<JsonObject>();
  result["segment_results"].to<JsonArray>();
  if(!ucs2Parts(outgoing["body"].as<String>(),parts)) { result["status"]="failed"; result["error_code"]="INVALID_TEXT"; outgoing["stage"]="result"; save("/outgoing.json",outgoing); return; }
  int reference=esp_random()%255+1;
  String number=outgoing["recipient"].as<String>();
  // Persist intent before sending ANY bytes. A reboot after this is ambiguous, never auto-retry.
  outgoing["stage"]="submitting";
  if(!save("/outgoing.json",outgoing)) return;
  for(size_t i=0;i<parts.size();++i) {
    String pdu=submitPdu(number,parts[i],reference,parts.size(),i+1);
    if(pdu.isEmpty()) { result["status"]="failed"; result["error_code"]="INVALID_NUMBER"; break; }
    String prompt=command("AT+CMGS="+String(pdu.length()/2-1),5000,true);
    if(prompt.indexOf('>')<0) {
      modem.write(27); // leave SMS entry mode if the prompt was lost
      result["status"]= i==0 && prompt.indexOf("ERROR")>=0 ? "failed" : "unknown";
      result["error_code"]="NO_PROMPT"; break;
    }
    modem.print(pdu); modem.write(26);
    String answer=response(60000);
    JsonObject segment=result["segment_results"].as<JsonArray>().add<JsonObject>(); segment["part"]=i+1;
    if(answer.indexOf("+CMGS:")>=0 && answer.indexOf("OK")>=0) {
      segment["status"]="sent";
      int start=answer.indexOf("+CMGS:")+6; segment["reference"]=answer.substring(start).toInt();
      result["status"]="sent";
    } else {
      bool rejected=answer.indexOf("+CMS ERROR:")>=0;
      segment["status"]=rejected?"failed":"unknown";
      result["status"]=(i==0 && rejected)?"failed":"unknown";
      result["error_code"]=rejected?"MODEM_REJECTED":"MODEM_TIMEOUT";
      result["error_message"]="Modem did not confirm all SMS segments; no automatic resend";
      break;
    }
    if(!save("/outgoing.json",outgoing)) return;
  }
  outgoing["stage"]="result"; save("/outgoing.json",outgoing);
}

void pollOutgoing() {
  if(!outgoing["id"].isNull()) { reportOutgoing(); return; }
  JsonDocument body,result;
  if(api("/device/outgoing/claim?iccid="+iccid,body,result)!=200) return;
  outgoing.set(result); outgoing["stage"]="claimed";
  if(!save("/outgoing.json",outgoing)) return;
  if(readIccid()!=iccid) {
    lastError="SIM changed before sending";
    outgoing["result"]["status"]="not_sent";
    outgoing["result"]["error_code"]="SIM_CHANGED";
    outgoing["stage"]="result"; save("/outgoing.json",outgoing);
    ready=false; return;
  }
  performSend(); reportOutgoing();
}

void heartbeat() {
  JsonDocument body,result;
  body["iccid"]=iccid; body["sim_status"]=command("AT+CPIN?").indexOf("READY")>=0?"ready":"not_ready";
  String network=command("AT+CEREG?"); int comma=network.indexOf(','); int state=comma>=0?network.substring(comma+1).toInt():-1;
  body["network_status"]=(state==1 || state==5)?"registered":"searching";
  String operatorResponse=command("AT+COPS?"); int first=operatorResponse.indexOf('"'),last=operatorResponse.indexOf('"',first+1);
  if(first>=0 && last>first) body["operator_name"]=operatorResponse.substring(first+1,last);
  String csq=command("AT+CSQ"); int colon=csq.indexOf("+CSQ:"); int signal=colon>=0?csq.substring(colon+5).toInt():99;
  if(signal>=0 && signal<=31) body["signal_dbm"]=-113+signal*2;
  body["queue_depth"]=inbox["groups"].size(); if(lastError.length()) body["last_error"]=lastError;
  if(api("/device/heartbeat",body,result)==200) {
    pollMs=max(1000U,result["poll_interval_ms"].as<unsigned>()); heartbeatMs=max(10000U,result["heartbeat_interval_ms"].as<unsigned>());
  }
}

void setup() {
  Serial.begin(115200);
  unsigned long serialStart=millis();
  while(!Serial && millis()-serialStart<3000) delay(10);
  Serial.println("SMSBot 0.2.1 boot");
  preferences.begin("smsbot",false);
  String saved=preferences.getString("identity","");
  if(saved.length() && deserializeJson(identity,saved)) { storageFault=true; lastError="NVS identity corrupt; stop"; Serial.println(lastError); return; }
  if(!LittleFS.begin(false)) { storageFault=true; lastError="Filesystem missing. First install: pio run -t uploadfs. Never format an existing queue."; Serial.println(lastError); return; }
  load("/inbox.json",inbox); load("/outgoing.json",outgoing);
  if(inbox["groups"].isNull()) inbox["groups"].to<JsonArray>();
  if(outgoing["id"].is<String>() && outgoing["stage"].as<String>()!="result") {
    String prior=outgoing["stage"].as<String>(); outgoing["stage"]="result";
    outgoing["result"]["status"]=prior=="claimed"?"not_sent":"unknown";
    outgoing["result"]["error_code"]="REBOOT_RECOVERY";
    outgoing["result"]["error_message"]="Device rebooted; persisted state determines safe recovery";
    save("/outgoing.json",outgoing);
  }
  if(identity["configured_key_hash"].as<String>()!=hash(PHONE_API_KEY)) {
    identity.remove("device_id"); identity["api_key"]=PHONE_API_KEY;
    if(!persistIdentity()) return;
  }
  pinMode(MODEM_DTR,OUTPUT); digitalWrite(MODEM_DTR,LOW);
  pinMode(MODEM_RESET,OUTPUT); digitalWrite(MODEM_RESET,HIGH);
  pinMode(MODEM_PWRKEY,OUTPUT); digitalWrite(MODEM_PWRKEY,LOW);
  modem.setRxBufferSize(32768); modem.begin(115200,SERIAL_8N1,MODEM_RX,MODEM_TX);
  WiFi.mode(WIFI_STA); WiFi.setAutoReconnect(true); WiFi.begin(WIFI_SSID,WIFI_PASSWORD);
  configTime(0,0,"pool.ntp.org","time.cloudflare.com");
}

void loop() {
  printStatus();
  if(storageFault) { delay(1000); return; }
  // A physical serial console may reset identity only when no local work is pending.
  if(Serial.available()) {
    String input=Serial.readStringUntil('\n'); input.trim();
    if(input=="PAIR RESET") {
      if(inbox["groups"].size() || !outgoing["id"].isNull()) Serial.println("Pending records exist; restore original SIM and sync first");
      else { identity.clear(); persistIdentity(); Serial.println("Identity reset; configure the phone API key and reboot"); }
    }
  }
  unsigned long now=millis();
  if(!ready && (long)(now-nextModem)>=0) { ready=initializeModem(); nextModem=millis()+30000; }
  if(!ready) { delay(20); return; }
  if(identity["iccid"].is<String>() && identity["iccid"].as<String>()!=iccid) { lastError="SIM changed. Restore card or re-pair after clearing pending work"; delay(1000); return; }
  if((long)(now-nextScan)>=0) {
    if(readIccid()!=iccid) { ready=false; return; }
    scanInbox(); nextScan=millis()+5000;
  }
  if(WiFi.status()!=WL_CONNECTED || time(nullptr)<1700000000) { delay(20); return; }
  if(!identity["device_id"].is<String>()) {
    if((long)(now-nextNetwork)>=0) {
      if(registerDevice()) backoff=1000; else backoff=min(backoff*2,60000U);
      nextNetwork=millis()+backoff+esp_random()%500;
    }
    delay(20); return;
  }
  if((long)(now-nextNetwork)<0) { delay(20); return; }
  if((long)(now-nextHeartbeat)>=0) { heartbeat(); nextHeartbeat=millis()+heartbeatMs; }
  if((long)(now-nextPoll)>=0) { pollOutgoing(); uploadInbox(); nextPoll=millis()+pollMs; }
  delay(5);
}

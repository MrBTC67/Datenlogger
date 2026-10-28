import machine, time, math, gc, network, urequests, ntptime

# --- KONFIGURATION ---
WLAN_SSID = "Starlink1"
WLAN_PASS = "astroman"
FIREBASE_BASE = "https://wetterdaten-98f0f-default-rtdb.europe-west1.firebasedatabase.app/"

SDA_PIN, SCL_PIN = 21, 22
PIN_R, PIN_G, PIN_B = 25, 26, 27
PIN_BAT = 34
MEASURE_INTERVAL = 600000  # Aufwachen, messen und senden alle 10 Minuten
LED_ON_TIME      = 3000   # LED leuchtet 3 Sek.
LED_BRIGHTNESS   = 0.15   # LED-Helligkeit (0.0 bis 1.0), spart Strom
DEW_WARN_GAP     = 1.5    # Abstand Temperatur/Taupunkt für Warnung in °C
DEW_ALARM_GAP    = 1.0    # darunter kann die Optik beschlagen
FROST_WARN_TEMP  = 2.0    # ab dieser Temperatur in °C Frost-Frühwarnung (LED rot)

# --- HARDWARE SETUP ---
led_r = machine.PWM(machine.Pin(PIN_R), freq=1000)
led_g = machine.PWM(machine.Pin(PIN_G), freq=1000)
led_b = machine.PWM(machine.Pin(PIN_B), freq=1000)

adc = machine.ADC(machine.Pin(PIN_BAT))
adc.atten(machine.ADC.ATTN_11DB)

i2c = machine.I2C(0, scl=machine.Pin(SCL_PIN), sda=machine.Pin(SDA_PIN))

def get_battery_voltage():
    try:
        avg = sum([adc.read() for _ in range(20)]) / 20
        voltage = (avg / 4095) * 3.3 * 2.13
        return round(voltage, 2)
    except:
        return 0.0

def set_rgb(r, g, b):
    led_r.duty(int((1 - r * LED_BRIGHTNESS) * 1023))
    led_g.duty(int((1 - g * LED_BRIGHTNESS) * 1023))
    led_b.duty(int((1 - b * LED_BRIGHTNESS) * 1023))

def leds_off():
    set_rgb(0, 0, 0)

class SHT3x:
    def __init__(self, i2c):
        self.i2c = i2c
    def read(self):
        try:
            self.i2c.writeto(0x44, b'\x2C\x06')
            time.sleep_ms(50)
            d = self.i2c.readfrom(0x44, 6)
            t = -45.0 + (175.0 * ((d[0] << 8 | d[1]) / 65535.0))
            h = 100.0 * ((d[3] << 8 | d[4]) / 65535.0)
            return t, h
        except: return None, None

def get_dew(t, h):
    a, b = 17.625, 243.04
    v = math.log(h / 100.0) + (a * t) / (b + t)
    return (b * v) / (a - v)

def connect_wifi():
    wlan = network.WLAN(network.STA_IF)
    if not wlan.isconnected():
        try:
            wlan.active(False)
            time.sleep_ms(100)
            wlan.active(True)
            wlan.connect(WLAN_SSID, WLAN_PASS)
            for _ in range(30):
                if wlan.isconnected(): return True
                time.sleep_ms(500)
        except OSError:
            machine.reset()
        return False
    return True

def disconnect_wifi():
    wlan = network.WLAN(network.STA_IF)
    wlan.active(False)
    time.sleep_ms(100)

def get_berlin_time():
    try:
        ntptime.settime()
    except: pass
    t = time.time()
    tm = time.localtime(t)
    year = tm[0]
    dst_start = time.mktime((year, 3, (31 - (int(5 * year / 4 + 4) % 7)), 1, 0, 0, 0, 0))
    dst_end = time.mktime((year, 10, (31 - (int(5 * year / 4 + 1) % 7)), 1, 0, 0, 0, 0))
    if dst_start <= t < dst_end:
        return time.localtime(t + 7200)
    else:
        return time.localtime(t + 3600)

def send_to_firebase(url, data):
    try:
        res = urequests.post(url, json=data, timeout=10)
        sc = res.status_code
        res.close()
        return sc == 200
    except: return False

def rtc_load_session():
    """Liest die Session-ID aus dem RTC-Speicher (überlebt Deep Sleep)."""
    try:
        saved = machine.RTC().memory()
        if saved and saved.startswith(b"DL1:"):
            saved_id = saved[4:].decode()
            if len(saved_id) == 13 and saved_id[8] == '_':
                return saved_id
    except:
        pass
    return None

def rtc_save_session(sid):
    try:
        machine.RTC().memory(("DL1:" + sid).encode())
    except:
        pass

def get_session_id():
    """Erzeugt eine neue Session-ID aus der Berliner Zeit."""
    now = get_berlin_time()
    return "{:04d}{:02d}{:02d}_{:02d}{:02d}".format(
        now[0], now[1], now[2], now[3], now[4]
    )

# --- INITIALISIERUNG ---
sensor = SHT3x(i2c)

# Nach jedem Deep Sleep startet das Skript neu. WLAN wird nur gebraucht,
# wenn noch keine Session im RTC-Speicher steht.
session_id = rtc_load_session()
if session_id is None:
    if connect_wifi():
        session_id = get_session_id()
        rtc_save_session(session_id)
        disconnect_wifi()

if session_id is None:
    current_session_url = FIREBASE_BASE + "Datenlogger/offline.json"
else:
    # Geänderter Pfad: Datenlogger/session_id
    current_session_url = FIREBASE_BASE + "Datenlogger/" + session_id + ".json"
    print("Sitzung im Datenlogger gestartet:", session_id)

# --- MAIN LOOP ---
while True:
    t_loop_start = time.ticks_ms()
    temp, hum = sensor.read()
    v_batt = get_battery_voltage()

    if temp is not None:
        dew = get_dew(temp, hum)
        diff = temp - dew

        if temp <= FROST_WARN_TEMP and dew <= 0 and diff <= DEW_WARN_GAP: status = "REIF"
        elif diff <= DEW_ALARM_GAP: status = "ALARM"
        elif temp <= FROST_WARN_TEMP: status = "FROST"
        elif diff <= DEW_WARN_GAP: status = "WARN"
        else: status = "OK"
        print("T: {:.1f}C | V: {:.2f}V | {}".format(temp, v_batt, status))

        if status == "OK": set_rgb(0, 0, 1)          # Blau
        elif status == "WARN": set_rgb(1, 0.4, 0)    # Orange
        else: set_rgb(1, 0, 0)                        # Rot: Tau-, Reif- oder Frostgefahr

        try:
            if connect_wifi():
                now = get_berlin_time()
                ts = "{:02d}:{:02d}:{:02d}".format(now[3], now[4], now[5])
                # Session nachholen, falls beim Start noch kein WLAN war
                if session_id is None:
                    session_id = get_session_id()
                    rtc_save_session(session_id)
                    current_session_url = FIREBASE_BASE + "Datenlogger/" + session_id + ".json"

                payload = {
                    "t": round(temp, 2), "h": round(hum, 2), "d": round(diff, 2),
                    "v": v_batt, "s": status, "ts": ts
                }
                send_to_firebase(current_session_url, payload)
                disconnect_wifi()
        except OSError:
            machine.reset()

    time.sleep_ms(LED_ON_TIME)
    leds_off()
    gc.collect()

    elapsed = time.ticks_diff(time.ticks_ms(), t_loop_start)
    # Deep-Sleep: Nach dem Aufwachen startet das Programm neu.
    machine.deepsleep(max(0, MEASURE_INTERVAL - elapsed))

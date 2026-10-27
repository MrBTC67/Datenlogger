import machine, time, math, gc, network, urequests, ntptime, os

# --- KONFIGURATION ---
WLAN_SSID = "Starlink1"
WLAN_PASS = "astroman"
FIREBASE_BASE = "https://wetterdaten-98f0f-default-rtdb.europe-west1.firebasedatabase.app/"

SDA_PIN, SCL_PIN = 21, 22
PIN_R, PIN_G, PIN_B = 25, 26, 27
PIN_BAT = 34
# SD-Karte am VSPI (siehe SD_Karte_Konfiguration.txt)
SD_CS, SD_MOSI, SD_MISO, SD_SCK = 5, 23, 19, 18
SD_MOUNT = "/sd"
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

# --- SD-KARTE ---
def sd_mount():
    """Hängt die SD-Karte ein. Gibt False zurück, wenn keine Karte gefunden wird."""
    try:
        sd = machine.SDCard(slot=3, sck=SD_SCK, mosi=SD_MOSI, miso=SD_MISO, cs=SD_CS)
        os.mount(sd, SD_MOUNT)
        return True
    except OSError:
        return False

def sd_umount():
    """Hängt die SD-Karte vor dem Deep Sleep sauber aus."""
    try:
        os.umount(SD_MOUNT)
    except OSError:
        pass

def sd_log_csv(sid, ts, temp, hum, dew, v_batt, status):
    """Hängt eine Messzeile an die CSV-Datei der Session an. Kopfzeile wird bei neuer Datei geschrieben."""
    path = SD_MOUNT + "/" + sid + ".csv"
    try:
        try:
            os.stat(path)
            new_file = False
        except OSError:
            new_file = True
        with open(path, "a") as f:
            if new_file:
                f.write("zeit,temp_c,feuchte_pct,taupunkt_c,akku_v,status\n")
            f.write("{},{:.2f},{:.2f},{:.2f},{:.2f},{}\n".format(
                ts, temp, hum, dew, v_batt, status))
        return True
    except OSError:
        return False

def sd_read_all():
    """Gibt alle CSV-Dateien der SD-Karte über die serielle Schnittstelle aus."""
    try:
        files = sorted(f for f in os.listdir(SD_MOUNT) if f.endswith(".csv"))
    except OSError:
        print("SD-Karte konnte nicht gelesen werden.")
        return
    if not files:
        print("Keine CSV-Dateien auf der SD-Karte.")
        return
    print("Gefundene Dateien:", files)
    for name in files:
        print("----- " + name + " -----")
        with open(SD_MOUNT + "/" + name, "r") as f:
            for line in f:
                print(line.rstrip())
        print("----- Ende " + name + " -----")

# --- SD-BEFEHLE ÜBER FIREBASE ---
# Die HTML schreibt Befehle nach SD_Befehl (aktion: lesen/loeschen, status: offen).
# Der ESP32 führt sie nach einer WLAN-Verbindung aus und meldet status und ergebnis zurück.
# Gelesene Zeilen landen unter SD_Daten/<session>, damit die HTML sie wie Live-Daten zeichnet.
SD_BEFEHL_URL = FIREBASE_BASE + "SD_Befehl.json"
SD_DATEN_URL = FIREBASE_BASE + "SD_Daten/"
SD_CHUNK = 50  # Zeilen pro Firebase-Anfrage, spart RAM

def sd_patch(url, data):
    res = urequests.request("PATCH", url, json=data, timeout=15)
    res.close()

def sd_hochladen(name):
    """Lädt eine CSV-Datei zeilenweise nach SD_Daten hoch. Gibt die Zeilenzahl zurück."""
    url = SD_DATEN_URL + name[:-4] + ".json"
    res = urequests.delete(url, timeout=15)
    res.close()
    anzahl = 0
    chunk = {}
    with open(SD_MOUNT + "/" + name, "r") as f:
        f.readline()  # Kopfzeile überspringen
        for line in f:
            teile = line.strip().split(",")
            if len(teile) != 6:
                continue
            chunk[teile[0]] = {"t": float(teile[1]), "h": float(teile[2]), "d": float(teile[3]),
                               "v": float(teile[4]), "s": teile[5], "ts": teile[0]}
            anzahl += 1
            if len(chunk) >= SD_CHUNK:
                sd_patch(url, chunk)
                chunk = {}
                gc.collect()
    if chunk:
        sd_patch(url, chunk)
    return anzahl

def sd_session_von_firebase(session):
    """Schreibt eine komplette Firebase-Session als CSV (FB_<session>.csv) auf die SD-Karte. Gibt die Zeilenzahl zurück."""
    basis = FIREBASE_BASE + "Datenlogger/" + session + ".json"
    res = urequests.get(basis + "?shallow=true", timeout=15)
    vorhanden = res.json()
    res.close()
    if not vorhanden:
        return 0
    # Datum steht im Session-Namen (JJJJMMTT_HHMM), die Firebase-Zeilen nur als HH:MM:SS
    datum = session[0:4] + "-" + session[4:6] + "-" + session[6:8] + " "
    anzahl = 0
    letzter = None
    with open(SD_MOUNT + "/FB_" + session + ".csv", "w") as f:
        f.write("zeit,temp_c,feuchte_pct,taupunkt_c,akku_v,status\n")
        while True:
            url = basis + '?orderBy="$key"&limitToFirst=' + str(SD_CHUNK)
            if letzter is not None:
                url += '&startAt="' + letzter + '"'
            res = urequests.get(url, timeout=15)
            seite = res.json()
            res.close()
            if not seite:
                break
            neu = 0
            for k in sorted(seite.keys()):
                e = seite[k]
                if (letzter is not None and k <= letzter) or not isinstance(e, dict):
                    continue
                ts = str(e.get("ts") or k)
                zeit = ts if " " in ts else datum + ts
                f.write("{},{:.2f},{:.2f},{:.2f},{:.2f},{}\n".format(
                    zeit, e.get("t", 0), e.get("h", 0), e.get("d", 0), e.get("v", 0), e.get("s", "")))
                letzter = k
                anzahl += 1
                neu += 1
            gc.collect()
            if neu == 0 or len(seite) < SD_CHUNK:
                break
    return anzahl

def sd_befehl_ausfuehren():
    """Prüft SD_Befehl in Firebase und führt einen offenen Befehl aus. Läuft nur bei bestehendem WLAN."""
    try:
        res = urequests.get(SD_BEFEHL_URL, timeout=10)
        befehl = res.json()
        res.close()
    except Exception:
        return
    if not befehl or befehl.get("status") != "offen":
        return
    aktion = befehl.get("aktion")
    try:
        dateien = sorted(f for f in os.listdir(SD_MOUNT) if f.endswith(".csv"))
        if aktion == "lesen":
            zeilen = 0
            for name in dateien:
                zeilen += sd_hochladen(name)
                gc.collect()
            ergebnis = "{} Dateien, {} Zeilen".format(len(dateien), zeilen)
        elif aktion == "loeschen":
            for name in dateien:
                os.remove(SD_MOUNT + "/" + name)
            ergebnis = "{} Dateien gelöscht".format(len(dateien))
        elif aktion == "speichern":
            session = befehl.get("session")
            zeilen = sd_session_von_firebase(session)
            ergebnis = "Session {}: {} Zeilen auf SD".format(session, zeilen)
        else:
            ergebnis = "Unbekannte Aktion: " + str(aktion)
        status = "erledigt"
    except Exception as e:
        status = "fehler"
        ergebnis = str(e)
    try:
        sd_patch(SD_BEFEHL_URL, {"status": status, "ergebnis": ergebnis})
    except Exception:
        pass

# Lesemodus: Liegt die Datei LESEN.txt auf der SD-Karte, werden die Daten
# nur ausgegeben und keine Messungen gestartet. Datei danach löschen
# (am PC) und den ESP32 neu starten, um wieder normal zu messen.
SD_LESE_DATEI = "/sd/LESEN.txt"

def sd_lesemodus_aktiv():
    try:
        os.stat(SD_LESE_DATEI)
        return True
    except OSError:
        return False

# --- INITIALISIERUNG ---
sensor = SHT3x(i2c)

sd_ok = sd_mount()
if not sd_ok:
    print("Keine SD-Karte gefunden, es wird nur ueber WLAN gesendet.")

if sd_ok and sd_lesemodus_aktiv():
    print("Lesemodus: Daten der SD-Karte werden ausgegeben.")
    sd_read_all()
    sd_umount()
    raise SystemExit

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
            wlan_ok = connect_wifi()
            # Mit WLAN NTP-Zeit, ohne WLAN lokale Uhr
            now = get_berlin_time()
            ts = "{:04d}-{:02d}-{:02d} {:02d}:{:02d}:{:02d}".format(now[0], now[1], now[2], now[3], now[4], now[5])
            # Session nachholen, falls beim Start noch kein WLAN war
            if session_id is None and wlan_ok:
                session_id = get_session_id()
                rtc_save_session(session_id)
                current_session_url = FIREBASE_BASE + "Datenlogger/" + session_id + ".json"

            # Entweder SD-Karte oder Firebase, nie beides: SD-Karte steckt, sonst Firebase
            if sd_ok:
                if session_id is not None:
                    sd_log_csv(session_id, ts, temp, hum, dew, v_batt, status)
                if wlan_ok:
                    sd_befehl_ausfuehren()
            elif wlan_ok:
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
    # Deep-Sleep: SD vorher sauber aushängen, danach startet das Programm neu.
    if sd_ok:
        sd_umount()
    machine.deepsleep(max(0, MEASURE_INTERVAL - elapsed))

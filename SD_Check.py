import machine, os, sys

# Pins wie in Datenlogger_SD.py
SD_CS, SD_MOSI, SD_MISO, SD_SCK = 5, 23, 19, 18
SD_MOUNT = "/sd"
TESTDATEI = SD_MOUNT + "/SD_CHECK.txt"

print("1. SD-Karte einhaengen ...")
# Alter Mount (z. B. von einem noch laufenden Datenlogger) stoerzt sonst mit ESP_ERR_INVALID_STATE
try:
    os.umount(SD_MOUNT)
    print("   Alter Mount ausgehaengt")
except OSError:
    pass
try:
    sd = machine.SDCard(slot=3, sck=SD_SCK, mosi=SD_MOSI, miso=SD_MISO, cs=SD_CS)
    os.mount(sd, SD_MOUNT)
    print("   OK, eingehaengt unter", SD_MOUNT)
    print("   Pins: CS", SD_CS, "MOSI", SD_MOSI, "MISO", SD_MISO, "SCK", SD_SCK)
except OSError as e:
    print("   FEHLER:", e)
    print("   Keine Karte, Verkabelung oder Format (FAT32) pruefen.")
    sys.print_exception(e)
    raise SystemExit

print("2. Schreiben ...")
try:
    with open(TESTDATEI, "w") as f:
        f.write("SD-Check OK\n")
    print("   OK, Datei:", TESTDATEI)
except OSError as e:
    print("   FEHLER:", e)
    sys.print_exception(e)
    raise SystemExit

print("3. Lesen ...")
with open(TESTDATEI, "r") as f:
    inhalt = f.read()
print("   Inhalt:", repr(inhalt))
if inhalt == "SD-Check OK\n":
    print("   OK, Inhalt stimmt")
else:
    print("   FEHLER, Inhalt stimmt nicht")

print("4. Dateien auf der Karte:")
for name in sorted(os.listdir(SD_MOUNT)):
    try:
        groesse = os.stat(SD_MOUNT + "/" + name)[6]
    except OSError:
        groesse = "?"
    print("   ", name, groesse, "Bytes")

print("5. Aufraeumen ...")
os.remove(TESTDATEI)
os.umount(SD_MOUNT)
print("   Testdatei entfernt, Karte ausgehaengt.")
print("Fertig.")

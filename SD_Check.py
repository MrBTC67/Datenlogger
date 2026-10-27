import machine, os

# Pins wie in Datenlogger_SD.py
SD_CS, SD_MOSI, SD_MISO, SD_SCK = 5, 23, 19, 18
SD_MOUNT = "/sd"
TESTDATEI = SD_MOUNT + "/SD_CHECK.txt"

print("1. SD-Karte einhaengen ...")
try:
    sd = machine.SDCard(slot=3, sck=SD_SCK, mosi=SD_MOSI, miso=SD_MISO, cs=SD_CS)
    os.mount(sd, SD_MOUNT)
    print("   OK")
except OSError as e:
    print("   FEHLER:", e)
    print("   Keine Karte, Verkabelung oder Format (FAT32) pruefen.")
    raise SystemExit

print("2. Schreiben ...")
try:
    with open(TESTDATEI, "w") as f:
        f.write("SD-Check OK\n")
    print("   OK")
except OSError as e:
    print("   FEHLER:", e)
    raise SystemExit

print("3. Lesen ...")
with open(TESTDATEI, "r") as f:
    inhalt = f.read()
if inhalt == "SD-Check OK\n":
    print("   OK, Inhalt stimmt")
else:
    print("   FEHLER, Inhalt:", inhalt)

print("4. Dateien auf der Karte:")
for name in os.listdir(SD_MOUNT):
    print("  ", name)

os.remove(TESTDATEI)
os.umount(SD_MOUNT)
print("Fertig. Testdatei wieder entfernt, Karte ausgehaengt.")

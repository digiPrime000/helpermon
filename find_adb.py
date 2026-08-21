"""Show which ADB is found, which devices answer and whether a frame arrives."""
import subprocess, capture
path = capture.find_adb()
print("ADB path:", path or "NOT FOUND")
if not path:
    print('Setze  $env:DGUP_ADB = "C:\\LDPlayer\\LDPlayer9\\adb.exe"')
    raise SystemExit
print(subprocess.run([path, "devices"], capture_output=True, text=True).stdout)
cap = capture.AdbCapture()
devs = cap.devices()
if not devs:
    print("kein Geraet. Im LDPlayer ADB debugging einschalten, dann")
    print("  & $env:DGUP_ADB connect 127.0.0.1:5555")
    raise SystemExit
for serial in devs:
    cap.serial = serial
    if cap.works():
        img = cap.grab()
        print("%-22s OK, Bild %d x %d" % (serial, img.shape[1], img.shape[0]))
    else:
        print("%-22s liefert kein Bild, alte TCP Verbindung?" % serial)
print()
print("Falls mehrere OK sind, das richtige festlegen mit")
print('  $env:DGUP_SERIAL = "<serial>"')

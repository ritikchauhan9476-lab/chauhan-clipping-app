#!/usr/bin/env bash
# Installs the APK on the emulator, opens it in self-test mode and waits for "SELFTEST OK" in the log.
set -u
APK="$(ls apk/*.apk | head -1)"
adb install -r "$APK" || exit 1
adb shell pm grant com.chauhan.clipping android.permission.POST_NOTIFICATIONS 2>/dev/null || true
adb logcat -c
adb shell am start -n com.chauhan.clipping/.MainActivity --ez selftest true
for i in $(seq 1 150); do
  if adb logcat -d -s CCJS:I | grep -q "SELFTEST OK\|SELFTEST FAIL"; then break; fi
  sleep 2
done
echo "------ app log ------"
adb logcat -d -s CCJS:I | tail -80
adb shell ls -la /data/app/*/com.chauhan.clipping*/lib/x86_64/ 2>/dev/null || true
adb logcat -d -s CCJS:I | grep -q "SELFTEST OK"

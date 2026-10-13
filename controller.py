#!/usr/bin/env python3
"""
ARACHNE capture controller - headless raspygotchi engine driver
Manages capture threads on wlan1, exposes state for web UI
"""
import sys, types, threading, subprocess, time

# --- Stub hardware imports ---
_lcd = types.ModuleType('LCD_1in44')
_lcd.LCD_WIDTH = 128
_lcd.LCD_HEIGHT = 128
_lcd.SCAN_DIR_DFT = 1
class _FakeLCD:
    def __init__(self, *a, **k): pass
    def LCD_Init(self, *a, **k): pass
    def LCD_Clear(self, *a, **k): pass
    def LCD_ShowImage(self, *a, **k): pass
_lcd.LCD = _FakeLCD
sys.modules['LCD_1in44'] = _lcd

_cfg = types.ModuleType('LCD_Config')
_cfg.GPIO_Init = lambda *a, **k: None
sys.modules['LCD_Config'] = _cfg

_rpi = types.ModuleType('RPi')
_gpio = types.ModuleType('RPi.GPIO')
for attr in ['BCM', 'OUT', 'IN', 'PUD_UP']:
    setattr(_gpio, attr, 1)
_gpio.setup = lambda *a, **k: None
_gpio.output = lambda *a, **k: None
_gpio.input = lambda *a, **k: 1
_gpio.cleanup = lambda *a, **k: None
_gpio.setmode = lambda *a, **k: None
_rpi.GPIO = _gpio
sys.modules['RPi'] = _rpi
sys.modules['RPi.GPIO'] = _gpio


# --- Activity feed ---
_feed = []
_feed_max = 100
_hunt_start = None
_deauth_count = 0

def _log(msg, typ="info"):
    import datetime
    _feed.append({
        "time": datetime.datetime.now().strftime("%H:%M:%S"),
        "msg": msg,
        "type": typ
    })
    while len(_feed) > _feed_max:
        _feed.pop(0)

# --- Load engine ---
import importlib.util
_spec = importlib.util.spec_from_file_location(
    'rg', '/opt/raspyjack/payloads/wifi/raspygotchi.py')
rg = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(rg)

# --- Controller state ---
IFACE = "wlan1"
_running = False
_threads = []

def _run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                          text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

def _set_monitor(iface):
    """Put interface in monitor mode"""
    _run(f"sudo nmcli device set {iface} managed no 2>/dev/null")
    _run(f"sudo ip link set {iface} down")
    _run(f"sudo iw {iface} set monitor control")
    _run(f"sudo ip link set {iface} up")
    import time; time.sleep(1)
    mode = _run(f"iwconfig {iface} 2>/dev/null | grep -o 'Mode:[A-Za-z]*'")
    return "Monitor" in mode

def start_capture():
    """Start the capture engine threads"""
    global _running, _threads
    if _running:
        return {"ok": False, "msg": "already running"}

    # Set interface in rg globals
    rg.mon_iface = IFACE
    if hasattr(rg, 'mon_iface2'):
        rg.mon_iface2 = None

    # Monitor mode
    if not _set_monitor(IFACE):
        return {"ok": False, "msg": "monitor mode failed"}

    # Start activity sampler (once)
    try:
        t = threading.Thread(target=rg._activity_sampler, daemon=True)
        t.start()
        _threads.append(t)
    except Exception as e:
        pass

    # Set capture event and start scan threads
    rg._capture_event.set()
    rg._scan_threads.clear()
    for target in [rg._channel_hopper, rg._sniffer, rg._half_hs_checker]:
        try:
            t = threading.Thread(target=target, daemon=True)
            t.start()
            rg._scan_threads.append(t)
            _threads.append(t)
        except Exception as e:
            print(f"Thread {target.__name__} failed: {e}")

    # Start attack hopper if deauth enabled
    try:
        t = threading.Thread(target=rg._attack_hopper, daemon=True)
        t.start()
        _threads.append(t)
    except:
        pass

    _running = True
    import datetime
    global _hunt_start
    _hunt_start = datetime.datetime.now()
    _log("Hunt started on " + IFACE + " - scanning for targets", "scan")
    return {"ok": True, "threads": len(_threads)}

def stop_capture():
    """Stop the capture engine"""
    global _running, _threads
    rg._capture_event.clear()
    # Threads are daemon, they'll exit on event clear
    _running = False
    _threads = []
    _log("Hunt stopped", "info")
    # Restore managed mode
    _run(f"sudo ip link set {IFACE} down")
    _run(f"sudo iw {IFACE} set type managed")
    _run(f"sudo ip link set {IFACE} up")
    return {"ok": True}

def get_status():
    """Get current engine status for web UI"""
    mood = "awake"
    try:
        # Try to get mood via _update_mood if it stores state
        if hasattr(rg, '_current_mood'):
            mood = rg._current_mood
        # Fallback: infer from AP count
        aps = getattr(rg, 'session_aps', {})
        if _running and aps:
            mood = "cool" if len(aps) > 5 else "awake"
        elif _running:
            mood = "bored"
    except:
        pass

    aps = {}
    try:
        aps = getattr(rg, 'session_aps', {})
    except:
        pass

    handshakes = []
    try:
        handshakes = list(getattr(rg, 'session_handshakes', {}).keys())
    except:
        pass

    # Find primary target (AP with most clients, not yet captured)
    primary = None
    try:
        best_score = -1
        for bssid, info in aps.items():
            if bssid in getattr(rg, 'captured_bssids', set()):
                continue
            clients = len(info.get("clients", []))
            if clients > best_score:
                best_score = clients
                primary = {"bssid": bssid, "essid": info.get("essid", "?"),
                          "channel": info.get("channel", "?"),
                          "clients": clients}
    except:
        pass

    # Build mood detail
    detail = ""
    if _running:
        if len(aps) == 0:
            detail = f"Scanning channels... {_deauth_count} deauths sent<br>No targets yet. Keep hunting."
        else:
            detail = f"Tracking {len(aps)} networks<br>{_deauth_count} deauths sent | {len(handshakes)} handshakes"
    else:
        detail = "Idle. Hit HUNT to start scanning."

    # Detect allied ESP32 deauth devices (CSticks) by MAC OUI
    allies = []
    try:
        esp32_ouis = ["24:6F:28", "24:0A:C4", "30:AE:A4", "3C:71:BF", "7C:DF:A1",
                      "54:43:B2", "EC:64:C9", "A4:CF:12", "94:B9:7E", "C8:2E:18",
                      "DC:4F:22", "E8:68:E7", "08:3A:F2", "10:52:1C", "60:01:94"]
        seen_macs = set()
        # Check AP clients for ESP32 devices
        for bssid, info in aps.items():
            for client_mac in info.get("clients", []):
                oui = client_mac.upper()[:8]
                if oui in esp32_ouis and client_mac not in seen_macs:
                    seen_macs.add(client_mac)
                    allies.append({
                        "name": f"CStick ({client_mac[-5:]})",
                        "mac": client_mac,
                        "status": "detected - likely deauth ally"
                    })
        # Also check for ESP32 APs (Marauder management APs)
        for bssid, info in aps.items():
            oui = bssid.upper()[:8]
            if oui in esp32_ouis and bssid not in seen_macs:
                seen_macs.add(bssid)
                allies.append({
                    "name": f"ESP32 AP ({info.get('essid', '?')})",
                    "mac": bssid,
                    "status": "ESP32 access point in range"
                })
    except Exception as e:
        pass

    # Uptime
    uptime_str = "0m"
    try:
        if _hunt_start and _running:
            import datetime
            delta = datetime.datetime.now() - _hunt_start
            mins = int(delta.total_seconds() / 60)
            uptime_str = f"{mins}m"
    except:
        pass

    # wlan1 mode
    wlan1_mode = "?"
    try:
        m = _run("iwconfig wlan1 2>/dev/null | grep -o 'Mode:[A-Za-z]*'")
        wlan1_mode = m.replace("Mode:", "") if m else "?"
    except:
        pass

    return {
        "running": _running,
        "mood": mood,
        "mood_detail": detail,
        "feed": _feed[-30:],
        "deauth_count": _deauth_count,
        "uptime": uptime_str,
        "allies": allies,
        "wlan1_mode": wlan1_mode,
        "primary_target": primary,
        "ap_count": len(aps),
        "aps": [{"bssid": k, "essid": v.get("essid", "?"),
                 "channel": v.get("channel", "?"),
                 "signal": v.get("signal"),
                 "clients": len(v.get("clients", []))}
                for k, v in list(aps.items())[:30]],
        "handshake_count": len(handshakes),
        "threads": len([t for t in _threads if t.is_alive()]),
    }

if __name__ == "__main__":
    import json
    print(json.dumps({"engine": "loaded", "faces": list(rg.FACES.keys())}))

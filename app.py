#!/usr/bin/env python3
import os, sys, subprocess
sys.path.insert(0, '/opt/arachne')
from flask import Flask, jsonify, send_from_directory
import controller as ctrl

app = Flask(__name__)
BASE = os.path.dirname(os.path.abspath(__file__))

MOOD_MAP = {
    'stealth': 'bored', 'happy': 'success', 'intense': 'attacking',
    'friend': 'idle', 'grateful': 'success', 'excited': 'scanning',
    'cool': 'scanning', 'awake': 'idle', 'lonely': 'bored',
    'bored': 'bored', 'sleeping': 'bored', 'sad': 'bored',
}
MOOD_TEXT = {
    'stealth': 'Ghost mode...', 'happy': 'PWNED!', 'intense': 'Attacking!',
    'friend': 'Peers nearby', 'grateful': 'PMKID captured!',
    'excited': 'Targets everywhere!', 'cool': 'Hunting...',
    'awake': 'Watching...', 'lonely': 'No targets...',
    'bored': 'Zzz...', 'sleeping': 'Sleeping', 'sad': ':(',
}

def run(cmd, timeout=10):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True,
                          text=True, timeout=timeout)
        return r.stdout.strip()
    except:
        return ""

@app.route("/")
def index():
    return send_from_directory(BASE, "index.html")

@app.route("/arachne.png")
def img():
    return send_from_directory(BASE, "arachne.png")

@app.route("/api/status")
def api_status():
    hs = run("systemctl is-active hostapd") == "active"
    s = ctrl.get_status()
    mood = s["mood"]
    return jsonify({
        "mood": MOOD_MAP.get(mood, 'idle'),
        "mood_text": MOOD_TEXT.get(mood, mood),
        "mood_detail": s.get("mood_detail", ""),
        "engine_mood": mood,
        "capture_active": s["running"],
        "ap_count": s["ap_count"],
        "aps": s["aps"],
        "handshake_count": s["handshake_count"],
        "feed": s.get("feed", []),
        "deauth_count": s.get("deauth_count", 0),
        "uptime": s.get("uptime", "0m"),
        "allies": s.get("allies", []),
        "wlan1_mode": s.get("wlan1_mode", "?"),
        "hotspot": hs,
        "wlan0_mode": ("AP" if hs else "CLI"),
        "wlan0_ip": run("ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1"),
        "raspyjack": run("systemctl is-active raspyjack-webui") == "active",
    })

@app.route("/api/capture/start", methods=["POST"])
def cap_start():
    return jsonify(ctrl.start_capture())

@app.route("/api/capture/stop", methods=["POST"])
def cap_stop():
    return jsonify(ctrl.stop_capture())

@app.route("/api/hotspot/toggle", methods=["POST"])
def hs_toggle():
    hs = run("systemctl is-active hostapd") == "active"
    if hs:
        run("sudo systemctl stop hostapd; sudo systemctl stop dnsmasq")
    else:
        run("sudo systemctl start dnsmasq; sudo systemctl start hostapd")
    return jsonify({"ok": True})


@app.route("/api/wlan0/toggle", methods=["POST"])
def wlan0_toggle():
    import subprocess
    subprocess.run(["/usr/local/bin/wlan0-switch", "toggle"], timeout=30)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

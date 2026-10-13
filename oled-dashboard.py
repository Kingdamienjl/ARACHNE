#!/usr/bin/env python3
"""OLED dashboard for AltMobileKali - network info + animated meters"""
import time, subprocess, random
from luma.core.interface.serial import i2c
from luma.oled.device import ssd1306
from luma.core.render import canvas
from PIL import ImageFont

def run(cmd):
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=5)
        return r.stdout.strip()
    except:
        return ""

def get_ssid():
    hs = run("systemctl is-active hostapd 2>/dev/null") == "active"
    if hs:
        s = run("grep '^ssid=' /etc/hostapd/hostapd.conf 2>/dev/null | cut -d= -f2")
        return s if s else "Hotspot"
    return run("iwgetid -r 2>/dev/null") or "No WiFi"

def get_ip():
    return run("ip addr show wlan0 2>/dev/null | grep 'inet ' | awk '{print $2}' | cut -d/ -f1") or "No IP"

def get_temp():
    t = run("cat /sys/class/thermal/thermal_zone0/temp 2>/dev/null")
    return int(t)//1000 if t else 0

def get_cpu():
    c = run("top -bn1 | grep 'Cpu(s)' | awk '{print $2}' | cut -d. -f1")
    return int(c) if c.isdigit() else 0

def get_mem():
    m = run("free | grep Mem | awk '{print $3/$2*100}'")
    try: return int(float(m))
    except: return 0

def bar(draw, x, y, w, pct, label):
    draw.text((x, y), label, font=font, fill=255)
    draw.rectangle((x+28, y+2, x+28+w, y+8), outline=255, fill=0)
    fw = int(w * min(pct,100) / 100)
    # animated shimmer on the fill
    draw.rectangle((x+28, y+2, x+28+fw, y+8), outline=255, fill=255)

serial = i2c(port=1, address=0x3C)
device = ssd1306(serial, width=128, height=64)
font = ImageFont.load_default()

screen = 0
frame = 0
# Matrix rain state: list of (x, y, speed)
import random
drops = [(random.randint(0, 120), random.randint(-20, 0), random.randint(1, 3)) for _ in range(15)]
# Spider animation state
spider_x = 0
spider_dir = 1
# Skull rotation state
skull_frame = 0

while True:
    ssid = get_ssid()
    ip = get_ip()
    hs = run("systemctl is-active hostapd 2>/dev/null") == "active"
    rj = run("systemctl is-active raspyjack-webui 2>/dev/null") == "active"
    has_ap_ip = "192.168.4.1" in run("ip addr show wlan0 2>/dev/null")
    mode = "AP" if (hs and has_ap_ip) else "CLI"
    cpu = get_cpu()
    temp = get_temp()
    mem = get_mem()

    with canvas(device) as draw:
        if screen == 0:
            draw.text((0, 0), f"AltMobileKali [{mode}]", font=font, fill=255)
            draw.text((0, 10), f"Net:{ssid[:17]}", font=font, fill=255)
            draw.text((0, 20), f"IP:{ip[:15]}", font=font, fill=255)
            hs_txt = "HS:ON " if hs else "HS:OFF"
            rj_txt = "RJ:ON" if rj else "RJ:OFF"
            draw.text((0, 30), f"{hs_txt} {rj_txt}", font=font, fill=255)
            bar(draw, 0, 42, 70, cpu, "CPU")
            draw.text((102, 42), f"{temp}C", font=font, fill=255)
        elif screen == 1:
            # Animated matrix rain - updates every frame
            for i, (x, y, spd) in enumerate(drops):
                draw.text((x, y), random.choice("01"), font=font, fill=255)
                y += spd
                if y > 64:
                    y = -10
                    x = random.randint(0, 120)
                drops[i] = (x, y, spd)
            draw.text((35, 28), "SCANNING", font=font, fill=255)
        elif screen == 2:
            up = run("uptime -p 2>/dev/null") or "up?"
            draw.text((0, 0), f"Up:{up[:18]}", font=font, fill=255)
            bar(draw, 0, 14, 70, mem, "MEM")
            draw.text((102, 14), f"{mem}%", font=font, fill=255)
            disk = run("df / | tail -1 | awk '{print $5}' | tr -d %")
            try: dpct = int(disk)
            except: dpct = 0
            bar(draw, 0, 28, 70, dpct, "DSK")
            draw.text((102, 28), f"{dpct}%", font=font, fill=255)
            draw.text((0, 42), f"Net:{ssid[:17]}", font=font, fill=255)
            draw.text((0, 54), time.strftime("%H:%M:%S"), font=font, fill=255)
        elif screen == 3:
            # Mechanical spider walking
            # Body
            bx = spider_x
            draw.ellipse((bx+50, 26, bx+78, 38), outline=255, fill=0)
            # Legs (animated)
            leg_off = (frame % 2) * 3
            for i in range(4):
                lx = bx + 52 + i*8
                # Top legs
                draw.line((lx, 28, lx-8, 18+leg_off if i%2==0 else 18-leg_off), fill=255)
                # Bottom legs
                draw.line((lx, 36, lx-8, 46-leg_off if i%2==0 else 46+leg_off), fill=255)
            # Eyes
            draw.ellipse((bx+68, 30, bx+72, 34), fill=255)
            draw.text((30, 50), "ARACHNE", font=font, fill=255)
            # Move spider
            spider_x += spider_dir * 4
            if spider_x > 50 or spider_x < -50:
                spider_dir *= -1
        elif screen == 4:
            # Spinning skull (RaspyJack)
            cx, cy = 64, 28
            # Skull circle (rotating effect via frame)
            r = 18
            draw.ellipse((cx-r, cy-r, cx+r, cy+r), outline=255)
            # Eyes (rotate position)
            import math
            ang = skull_frame * 0.3
            ex1 = cx + int(8 * math.cos(ang))
            ey1 = cy + int(6 * math.sin(ang))
            ex2 = cx - int(8 * math.cos(ang))
            ey2 = cy - int(6 * math.sin(ang))
            draw.ellipse((ex1-3, ey1-3, ex1+3, ey1+3), fill=255)
            draw.ellipse((ex2-3, ey2-3, ex2+3, ey2+3), fill=255)
            # Teeth
            for i in range(5):
                tx = cx - 10 + i*5
                draw.line((tx, cy+12, tx, cy+16), fill=255)
            draw.text((35, 50), "RASPYJACK", font=font, fill=255)
            skull_frame += 1

    frame += 1
    # Stay longer on animated screens
    if screen in (1, 3, 4):
        time.sleep(0.15)
        # Don't advance screen every frame for animations
        if frame % 20 == 0:
            screen = (screen + 1) % 5
    else:
        time.sleep(2)
        screen = (screen + 1) % 5

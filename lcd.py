#!/usr/bin/python3

import os
import sys
import struct
import fcntl
import socket
import time
import base64
import io
from select import select

from PIL import Image, ImageFont, ImageDraw

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False

try:
    import evdev
    from evdev import InputDevice, categorize, ecodes
    HAS_EVDEV = True
except ImportError:
    HAS_EVDEV = False

# ICH9 GPIO button polling
ICH9_GPIOBASE = 0x0480
ICH9_GP_LVL_OFF = 0x00C
BTN_SELECT_BIT = 1 << 4   # GPIO4
BTN_SCROLL_BIT = 1 << 5   # GPIO5


class GpioButtons:
    """Poll ICH9 GPIO pins 4 (SELECT) and 5 (SCROLL) via /dev/port."""

    def __init__(self):
        self.fd = None
        self.prev_select = True
        self.prev_scroll = True

    def open(self):
        self.fd = os.open('/dev/port', os.O_RDONLY)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def read_buttons(self):
        """Return (select_pressed, scroll_pressed) booleans."""
        os.lseek(self.fd, ICH9_GPIOBASE + ICH9_GP_LVL_OFF, os.SEEK_SET)
        lvl = struct.unpack('<I', os.read(self.fd, 4))[0]
        return (not bool(lvl & BTN_SELECT_BIT),
                not bool(lvl & BTN_SCROLL_BIT))

    def poll(self):
        """Return edge events: ('select_down'|'select_up'|'scroll_down'|'scroll_up') or None."""
        sel, scr = self.read_buttons()
        events = []
        if sel and not self.prev_select:
            events.append('select_down')
        elif not sel and self.prev_select:
            events.append('select_up')
        if scr and not self.prev_scroll:
            events.append('scroll_down')
        elif not scr and self.prev_scroll:
            events.append('scroll_up')
        self.prev_select = sel
        self.prev_scroll = scr
        return events

LCD_WIDTH = 128
LCD_HEIGHT = 64
LCD_PAGES = 8
LCD_FB_SIZE = LCD_WIDTH * LCD_HEIGHT // 8  # 1024 bytes

FONT = ImageFont.load_default()

# ioctl constants for /dev/lcm (ums8485md / lpc-ich legacy interface)
# _IOWR(0xF4, 0, lcm_member_t) where lcm_member_t = 144 bytes
IOCTL_DISPLAY_COMMAND = (3 << 30) | (144 << 16) | (0xF4 << 8) | 0  # 0xC090F400

WIX_LCM_CMD_PON = 0x01
WIX_LCM_CMD_POFF = 0x02
WIX_LCM_CMD_RESET = 0x03
WIX_LCM_CMD_DISP_NORMAL = 0x04
WIX_LCM_CMD_WRITE_DATA = 0x0c

# lcm_member_t struct: int ctrl, int page, int column, int size, unsigned char data[128]
LCM_STRUCT_FMT = 'iiii128s'

logo = """Qk02JAAAAAAAADYEAAAoAAAAgAAAAEAAAAABAAgAAAAAAAAgAAAjLgAAIy4AAAABAAAAAQAAAAAAAAEBAQACAgIAAwMDAAQEBAAFBQUABgYGAAcHBwAICAgACQkJAAoKCgALCwsADAwMAA0NDQAODg
          4ADw8PABAQEAAREREAEhISABMTEwAUFBQAFRUVABYWFgAXFxcAGBgYABkZGQAaGhoAGxsbABwcHAAdHR0AHh4eAB8fHwAgICAAISEhACIiIgAjIyMAJCQkACUlJQAmJiYAJycnACgoKAApKSkAKioq
          ACsrKwAsLCwALS0tAC4uLgAvLy8AMDAwADExMQAyMjIAMzMzADQ0NAA1NTUANjY2ADc3NwA4ODgAOTk5ADo6OgA7OzsAPDw8AD09PQA+Pj4APz8/AEBAQABBQUEAQkJCAENDQwBEREQARUVFAEZGRg
          BHR0cASEhIAElJSQBKSkoAS0tLAExMTABNTU0ATk5OAE9PTwBQUFAAUVFRAFJSUgBTU1MAVFRUAFVVVQBWVlYAV1dXAFhYWABZWVkAWlpaAFtbWwBcXFwAXV1dAF5eXgBfX18AYGBgAGFhYQBiYmIA
          Y2NjAGRkZABlZWUAZmZmAGdnZwBoaGgAaWlpAGpqagBra2sAbGxsAG1tbQBubm4Ab29vAHBwcABxcXEAcnJyAHNzcwB0dHQAdXV1AHZ2dgB3d3cAeHh4AHl5eQB6enoAe3t7AHx8fAB9fX0Afn5+AH
          9/fwCAgIAAgYGBAIKCggCDg4MAhISEAIWFhQCGhoYAh4eHAIiIiACJiYkAioqKAIuLiwCMjIwAjY2NAI6OjgCPj48AkJCQAJGRkQCSkpIAk5OTAJSUlACVlZUAlpaWAJeXlwCYmJgAmZmZAJqamgCb
          m5sAnJycAJ2dnQCenp4An5+fAKCgoAChoaEAoqKiAKOjowCkpKQApaWlAKampgCnp6cAqKioAKmpqQCqqqoAq6urAKysrACtra0Arq6uAK+vrwCwsLAAsbGxALKysgCzs7MAtLS0ALW1tQC2trYAt7
          e3ALi4uAC5ubkAurq6ALu7uwC8vLwAvb29AL6+vgC/v78AwMDAAMHBwQDCwsIAw8PDAMTExADFxcUAxsbGAMfHxwDIyMgAycnJAMrKygDLy8sAzMzMAM3NzQDOzs4Az8/PANDQ0ADR0dEA0tLSANPT
          0wDU1NQA1dXVANbW1gDX19cA2NjYANnZ2QDa2toA29vbANzc3ADd3d0A3t7eAN/f3wDg4OAA4eHhAOLi4gDj4+MA5OTkAOXl5QDm5uYA5+fnAOjo6ADp6ekA6urqAOvr6wDs7OwA7e3tAO7u7gDv7+
          8A8PDwAPHx8QDy8vIA8/PzAPT09AD19fUA9vb2APf39wD4+PgA+fn5APr6+gD7+/sA/Pz8AP39/QD+/v4A////AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAyNFXVM9HgMAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAANV/PkC4HAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAJOT//2AEAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAE3L//3JPAQAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAADbB/50vAAEAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAVh///3KwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAMjP//wyAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAADJ7//3UkAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAyb//9xAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAFf///9xEAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAGL///82AAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAA2////QwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAFNv//4EBAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAB8////IwAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAANP///4IFAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAU3////UgAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA
          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"""


class FramebufferBackend:
    """Write to /dev/fb* — lpc-ich driver handles 1bpp-to-ST7565 conversion."""

    def __init__(self, path='/dev/fb0'):
        self.path = path
        self.fd = None

    def open(self):
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def init_display(self):
        pass

    def write_image(self, pil_image):
        bmp = pil_image.convert('1')
        raw = bmp.tobytes()
        fb = bytearray(LCD_FB_SIZE)
        for y in range(LCD_HEIGHT):
            for x in range(LCD_WIDTH):
                src_byte = y * ((LCD_WIDTH + 7) // 8) + x // 8
                src_bit = 7 - (x % 8)
                if src_byte < len(raw) and raw[src_byte] & (1 << src_bit):
                    dst_byte = y * (LCD_WIDTH // 8) + x // 8
                    dst_bit = 7 - (x % 8)
                    fb[dst_byte] |= (1 << dst_bit)
        os.lseek(self.fd, 0, os.SEEK_SET)
        os.write(self.fd, bytes(fb))


class IoctlBackend:
    """Write to /dev/lcm via ioctl — ums8485md or lpc-ich legacy interface."""

    def __init__(self, path='/dev/lcm'):
        self.path = path
        self.fd = None

    def open(self):
        self.fd = os.open(self.path, os.O_RDWR)

    def close(self):
        if self.fd is not None:
            os.close(self.fd)
            self.fd = None

    def _ioctl_cmd(self, ctrl, page, column, size, data):
        padded = data.ljust(128, b'\x00')[:128]
        buf = struct.pack(LCM_STRUCT_FMT, ctrl, page, column, size, padded)
        fcntl.ioctl(self.fd, IOCTL_DISPLAY_COMMAND, buf)

    def init_display(self):
        self._ioctl_cmd(WIX_LCM_CMD_RESET, 0, 0, 0, b'\x00' * 128)
        self._ioctl_cmd(WIX_LCM_CMD_PON, 0, 0, 0, b'\x00' * 128)
        self._ioctl_cmd(WIX_LCM_CMD_DISP_NORMAL, 0, 0, 0, b'\x00' * 128)

    def write_image(self, pil_image):
        pixels = pil_image.convert('L').load()
        for page in range(LCD_PAGES):
            page_data = bytearray(LCD_WIDTH)
            for col in range(LCD_WIDTH):
                val = 0
                for bit in range(8):
                    row = page * 8 + bit
                    if row < LCD_HEIGHT and pixels[col, row] != 0:
                        val |= (1 << bit)
                page_data[col] = val
            self._ioctl_cmd(WIX_LCM_CMD_WRITE_DATA, page, 0, LCD_WIDTH, bytes(page_data))


def find_lcd_framebuffer():
    """Scan /sys/class/graphics/fb*/name for the px300d-lcd device."""
    graphics_path = '/sys/class/graphics'
    if not os.path.isdir(graphics_path):
        return None
    for entry in sorted(os.listdir(graphics_path)):
        if not entry.startswith('fb'):
            continue
        name_path = os.path.join(graphics_path, entry, 'name')
        try:
            with open(name_path, 'r') as f:
                name = f.read().strip()
            if name == 'px300d-lcd':
                return '/dev/' + entry
        except OSError:
            continue
    return None


def detect_backend(timeout=60):
    deadline = time.time() + timeout
    attempt = 0
    while True:
        fb_path = find_lcd_framebuffer()
        if fb_path:
            try:
                b = FramebufferBackend(fb_path)
                b.open()
                print(f"Using framebuffer backend: {fb_path}")
                return b
            except OSError:
                pass
        if os.path.exists('/dev/lcm'):
            try:
                b = IoctlBackend('/dev/lcm')
                b.open()
                print("Using ioctl backend: /dev/lcm")
                return b
            except OSError:
                pass
        if time.time() >= deadline:
            break
        attempt += 1
        if attempt == 1:
            print("Waiting for LCD kernel module...", flush=True)
        time.sleep(2)
    print("ERROR: No LCD device found (px300d-lcd fb or /dev/lcm)", file=sys.stderr)
    sys.exit(1)


def get_local_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('192.255.255.255', 1))
        IP = s.getsockname()[0]
    except Exception:
        IP = '127.0.0.1'
    finally:
        s.close()
    return IP


def get_load_avg():
    try:
        with open('/proc/loadavg', 'r') as f:
            load_avg = f.readline().split()[:3]
        return [float(x) for x in load_avg]
    except Exception:
        return [0.0, 0.0, 0.0]


def get_cpu_count():
    try:
        with open('/proc/cpuinfo', 'r') as f:
            cpu_info = f.read()
        return max(cpu_info.count('processor\t:'), 1)
    except Exception:
        return 2


def cpu_usage():
    load_avg = get_load_avg()
    cpu_count = get_cpu_count()
    return (load_avg[0] / cpu_count) * 100


def get_memory_info():
    try:
        meminfo = {}
        with open('/proc/meminfo', 'r') as f:
            for line in f:
                parts = line.split()
                key = parts[0].rstrip(':')
                value = int(parts[1])
                meminfo[key] = value
        return meminfo
    except Exception:
        return {}


def memory_usage():
    try:
        meminfo = get_memory_info()
        mem_total = meminfo['MemTotal']
        mem_free = meminfo['MemFree']
        buffers = meminfo['Buffers']
        cached = meminfo['Cached']
        mem_used = mem_total - (mem_free + buffers + cached)
        return (mem_used / mem_total) * 100
    except Exception:
        return 0


def find_hwmon_by_name(name):
    """Return /sys/class/hwmon/hwmonN path for a given driver name."""
    import glob
    for path in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(path, 'name'), 'r') as f:
                if f.read().strip() == name:
                    return path
        except OSError:
            continue
    return None


def find_all_hwmon_by_name(name):
    """Return all hwmon paths matching a driver name."""
    import glob
    results = []
    for path in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        try:
            with open(os.path.join(path, 'name'), 'r') as f:
                if f.read().strip() == name:
                    results.append(path)
        except OSError:
            continue
    return results


def read_sensor(file_path):
    try:
        with open(file_path, 'r') as f:
            return f.read().strip()
    except Exception:
        return "0"


def get_cpu_temp():
    path = find_hwmon_by_name('coretemp')
    if not path:
        return 0
    for f in ['temp1_input', 'temp2_input', 'temp3_input']:
        val = read_sensor(os.path.join(path, f))
        if val != "0":
            return int(val) / 1000
    return 0


def get_fan_speeds():
    import glob
    speeds = []
    for path in sorted(glob.glob('/sys/class/hwmon/hwmon*')):
        for pattern in ['fan*_input', 'device/fan*_input']:
            for fan in sorted(glob.glob(os.path.join(path, pattern))):
                val = int(read_sensor(fan))
                if val > 0:
                    speeds.append(val)
    return speeds


def get_drive_temps():
    temps = []
    for path in find_all_hwmon_by_name('drivetemp'):
        val = read_sensor(os.path.join(path, 'temp1_input'))
        temps.append(int(int(val) / 1000))
    return temps


def read_fanmode():
    try:
        with open('/tmp/fanmode.txt', 'r') as f:
            return f.read().strip()
    except Exception:
        return ''


def display_home(backend):
    try:
        im = Image.new(mode="1", size=(LCD_WIDTH, LCD_HEIGHT), color=0)
        drw = ImageDraw.Draw(im)
        f = FONT
        lh = 10

        cpu_temp = get_cpu_temp()
        hd_temps = get_drive_temps()
        fans = get_fan_speeds()
        mode = read_fanmode()

        drw.text((0, 0), "Host: " + socket.gethostname(), font=f, fill=1)
        drw.text((0, lh), "IP: " + get_local_ip(), font=f, fill=1)
        drw.text((0, lh * 2), f"CPU: {cpu_temp:.0f}C", font=f, fill=1)
        if hd_temps:
            drw.text((0, lh * 3), "HDD: " + " ".join(str(t) for t in hd_temps) + "C", font=f, fill=1)
        else:
            drw.text((0, lh * 3), "HDD: N/A", font=f, fill=1)
        if fans:
            drw.text((0, lh * 4), "Fan: " + " ".join(str(r) for r in fans) + " " + mode, font=f, fill=1)
        else:
            drw.text((0, lh * 4), "Fan: no sensor", font=f, fill=1)
        drw.text((0, lh * 5), f"CPU:{int(cpu_usage())}%  RAM:{int(memory_usage())}%", font=f, fill=1)

        backend.write_image(im)
    except Exception as e:
        print(f"Error in display_home: {e}")


def get_md_array_status(md_device):
    try:
        with open('/proc/mdstat', 'r') as f:
            mdstat_content = f.read()
        device_section = next(
            (s for s in mdstat_content.split('\n\n') if md_device in s), None)
        if not device_section:
            return "N/A"
        status_line = next(
            (line for line in device_section.split('\n') if 'U' in line), None)
        if status_line:
            return ''.join([c for c in status_line if c in 'U_'])
        return "N/A"
    except Exception:
        return "N/A"


def display_disk_usage(backend):
    if not HAS_PSUTIL:
        return
    try:
        mountpoint1 = '/boot'
        mountpoint2 = '/'
        mountpoint3 = '/srv'

        disk_usage1 = psutil.disk_usage(mountpoint1)
        disk_usage2 = psutil.disk_usage(mountpoint2)
        disk_usage3 = psutil.disk_usage(mountpoint3)

        image = Image.new(mode="1", size=(LCD_WIDTH, LCD_HEIGHT), color=0)
        draw = ImageDraw.Draw(image)
        f = FONT

        bbox1 = [2, 2, 41, 41]
        bbox2 = [44, 2, 83, 41]
        bbox3 = [86, 2, 125, 41]

        draw.ellipse(bbox1, outline=1)
        draw.ellipse(bbox2, outline=1)
        draw.ellipse(bbox3, outline=1)

        for usage, bbox in [(disk_usage1, bbox1), (disk_usage2, bbox2), (disk_usage3, bbox3)]:
            angle = int(360 * (usage.percent / 100))
            if angle > 0:
                draw.pieslice(bbox, start=0, end=angle, fill=1)

        for usage, offset in [(disk_usage1, 0), (disk_usage2, 44), (disk_usage3, 86)]:
            pct = f"{int(usage.percent)}%"
            tw = draw.textlength(pct, font=f)
            y_pos = 10 if usage.percent < 50 else 23
            color = 1 if usage.percent < 50 else 0
            draw.text((offset + (42 - tw) / 2, y_pos), pct, font=f, fill=color)

        for mp, offset in [(mountpoint1, 0), (mountpoint2, 44), (mountpoint3, 86)]:
            tw = draw.textlength(mp, font=f)
            draw.text((offset + (42 - tw) / 2, 43), mp, font=f, fill=1)

        status = get_md_array_status('md0')
        tw = draw.textlength(status, font=f)
        draw.text((44 + (42 - tw) / 2, 53), status, font=f, fill=1)
        status = get_md_array_status('md1')
        tw = draw.textlength(status, font=f)
        draw.text((86 + (42 - tw) / 2, 53), status, font=f, fill=1)

        backend.write_image(image)
    except Exception as e:
        print(f"Error in display_disk_usage: {e}")


def draw_logo(backend):
    try:
        im = Image.open(io.BytesIO(base64.b64decode(logo)))
        backend.write_image(im)
    except Exception as e:
        print(f"Error in draw_logo: {e}")


def cycle_backlight(backlight_index=[2]):
    backlight_values = [0, 50, 100, 150, 200, 250]
    backlight_index[0] = (backlight_index[0] + 1) % len(backlight_values)
    set_backlight(backlight_values[backlight_index[0]])


def find_backlight_pwm():
    """Find the PWM file for the LCD backlight on the Fintek Super I/O hwmon."""
    import glob
    for pattern in [
        '/sys/class/i2c-adapter/i2c-*/0-002e/hwmon/hwmon*/pwm3',
        '/sys/class/hwmon/hwmon*/device/pwm3',
        '/sys/class/hwmon/hwmon*/pwm3',
    ]:
        matches = glob.glob(pattern)
        if matches:
            return matches[0]
    return None


_backlight_pwm = find_backlight_pwm()


def set_backlight(value):
    if _backlight_pwm is None:
        return
    try:
        with open(_backlight_pwm, 'w') as f:
            f.write(str(value))
    except IOError as e:
        print(f"Failed to write {_backlight_pwm}: {e}")


def run_with_gpio_buttons(backend, screens):
    """Main loop using ICH9 GPIO polling for front panel buttons."""
    LONG_PRESS_THRESHOLD = 2
    CYCLE_BACKLIGHT_INTERVAL = 0.5
    POLL_INTERVAL = 0.05

    buttons = GpioButtons()
    try:
        buttons.open()
    except OSError as e:
        print(f"Cannot open /dev/port for buttons: {e}")
        print("Running in display-only mode")
        index = 0
        try:
            while True:
                screens[index]()
                time.sleep(60)
                index = (index + 1) % len(screens)
        except KeyboardInterrupt:
            pass
        return

    print("Using ICH9 GPIO buttons (SELECT=GPIO4, SCROLL=GPIO5)")

    select_press_time = None
    last_backlight_cycle = None
    long_press_detected = False
    index = 0

    try:
        while True:
            screens[index]()
            next_time = time.time() + 60

            while time.time() < next_time:
                time.sleep(POLL_INTERVAL)
                for ev in buttons.poll():
                    if ev == 'select_down':
                        select_press_time = time.time()
                        last_backlight_cycle = select_press_time
                        long_press_detected = False
                    elif ev == 'select_up':
                        if select_press_time is not None:
                            duration = time.time() - select_press_time
                            if duration < LONG_PRESS_THRESHOLD and not long_press_detected:
                                next_time = time.time()
                        select_press_time = None
                        last_backlight_cycle = None
                        long_press_detected = False
                    elif ev == 'scroll_down':
                        index = -1
                        next_time = time.time()

                if select_press_time is not None:
                    duration = time.time() - select_press_time
                    if duration >= LONG_PRESS_THRESHOLD:
                        long_press_detected = True
                        now = time.time()
                        if now - last_backlight_cycle >= CYCLE_BACKLIGHT_INTERVAL:
                            cycle_backlight()
                            last_backlight_cycle = now

            index = (index + 1) % len(screens)
    except KeyboardInterrupt:
        pass
    finally:
        buttons.close()


def main():
    backend = detect_backend()
    backend.init_display()

    screens = [
        lambda: display_home(backend),
        lambda: display_disk_usage(backend),
    ]

    cycle_backlight()
    draw_logo(backend)
    time.sleep(5)

    try:
        run_with_gpio_buttons(backend, screens)
    finally:
        backend.close()


if __name__ == '__main__':
    main()

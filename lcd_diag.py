#!/usr/bin/python3
"""Probe ICH9 GPIO pins used for the ST7565R front-panel LCD and verify hardware health."""
import os, sys, struct, glob, time, argparse

LCD_PINS = {
    'SI':  {'bit': 6,  'desc': 'SPI data (MOSI)'},
    'SCL': {'bit': 7,  'desc': 'SPI clock'},
    'RS':  {'bit': 16, 'desc': 'LCD reset'},
    'A0':  {'bit': 19, 'desc': 'Data/Command select'},
    'CS1': {'bit': 21, 'desc': 'Chip select'},
}
BUTTON_PINS = {
    'SELECT': {'bit': 4, 'desc': 'Front panel SELECT (active-LOW)'},
    'SCROLL': {'bit': 5, 'desc': 'Front panel SCROLL (active-LOW)'},
}

ICH9_GPIO_USE_SEL = 0x000
ICH9_GP_IO_SEL    = 0x004
ICH9_GP_LVL       = 0x00C

ST7565R_INIT = [0xA0, 0x2F, 0xA2, 0xC8, 0x27, 0x81, 0x17, 0xAF]


class PortIO:
    def __init__(self):
        self.fd = os.open('/dev/port', os.O_RDWR)

    def close(self):
        os.close(self.fd)

    def inl(self, port):
        os.lseek(self.fd, port, os.SEEK_SET)
        return struct.unpack('<I', os.read(self.fd, 4))[0]

    def outl(self, port, val):
        os.lseek(self.fd, port, os.SEEK_SET)
        os.write(self.fd, struct.pack('<I', val))


def find_lpc_bridge():
    for dev_path in sorted(glob.glob('/sys/bus/pci/devices/*')):
        try:
            vendor = int(open(f'{dev_path}/vendor').read().strip(), 16)
            cls = int(open(f'{dev_path}/class').read().strip(), 16)
            if vendor == 0x8086 and (cls >> 8) == 0x0601:
                device = int(open(f'{dev_path}/device').read().strip(), 16)
                return dev_path, device
        except (OSError, ValueError):
            continue
    return None, None


def read_gpiobase(dev_path):
    with open(f'{dev_path}/config', 'rb') as f:
        cfg = f.read(256)
    gpio_base = struct.unpack_from('<I', cfg, 0x48)[0] & 0xFFC0
    gpio_ctrl = struct.unpack_from('<I', cfg, 0x4C)[0]
    return gpio_base, gpio_ctrl


def check_pin_config(io, gpio_base, name, bit):
    mask = 1 << bit
    use_sel = io.inl(gpio_base + ICH9_GPIO_USE_SEL)
    io_sel = io.inl(gpio_base + ICH9_GP_IO_SEL)
    lvl = io.inl(gpio_base + ICH9_GP_LVL)

    is_gpio = bool(use_sel & mask)
    is_output = not bool(io_sel & mask)
    level = bool(lvl & mask)
    return is_gpio, is_output, level


def toggle_test(io, gpio_base, bit):
    mask = 1 << bit

    orig = io.inl(gpio_base + ICH9_GP_LVL)
    io.outl(gpio_base + ICH9_GP_LVL, orig | mask)
    time.sleep(0.005)
    hi = bool(io.inl(gpio_base + ICH9_GP_LVL) & mask)

    io.outl(gpio_base + ICH9_GP_LVL, orig & ~mask)
    time.sleep(0.005)
    lo = bool(io.inl(gpio_base + ICH9_GP_LVL) & mask)

    io.outl(gpio_base + ICH9_GP_LVL, orig)
    return hi and not lo


def set_pin(io, gpio_base, bit, value):
    mask = 1 << bit
    lvl = io.inl(gpio_base + ICH9_GP_LVL)
    if value:
        lvl |= mask
    else:
        lvl &= ~mask
    io.outl(gpio_base + ICH9_GP_LVL, lvl)


def write_lcd_byte(io, gpio_base, is_data, byte_val):
    set_pin(io, gpio_base, 21, 0)
    set_pin(io, gpio_base, 19, 1 if is_data else 0)
    for _ in range(8):
        set_pin(io, gpio_base, 7, 0)
        set_pin(io, gpio_base, 6, 1 if (byte_val & 0x80) else 0)
        set_pin(io, gpio_base, 7, 1)
        byte_val <<= 1
    set_pin(io, gpio_base, 21, 1)


def configure_lcd_pins(io, gpio_base):
    all_mask = sum(1 << p['bit'] for p in LCD_PINS.values())
    use = io.inl(gpio_base + ICH9_GPIO_USE_SEL)
    io.outl(gpio_base + ICH9_GPIO_USE_SEL, use | all_mask)
    sel = io.inl(gpio_base + ICH9_GP_IO_SEL)
    io.outl(gpio_base + ICH9_GP_IO_SEL, sel & ~all_mask)


def lcd_reset_and_init(io, gpio_base):
    all_mask = sum(1 << p['bit'] for p in LCD_PINS.values())
    lvl = io.inl(gpio_base + ICH9_GP_LVL)
    io.outl(gpio_base + ICH9_GP_LVL, lvl & ~all_mask)

    set_pin(io, gpio_base, 16, 0)
    time.sleep(0.2)
    set_pin(io, gpio_base, 16, 1)
    time.sleep(0.2)
    set_pin(io, gpio_base, 21, 1)
    set_pin(io, gpio_base, 7, 1)

    for cmd in ST7565R_INIT:
        write_lcd_byte(io, gpio_base, False, cmd)


def send_test_pattern(io, gpio_base, pattern):
    for page in range(8):
        write_lcd_byte(io, gpio_base, False, 0x0F & 0)
        write_lcd_byte(io, gpio_base, False, 0x10 | (0 >> 4))
        write_lcd_byte(io, gpio_base, False, 0xB0 + page)
        for col in range(128):
            if pattern == 'checker':
                val = 0xAA if (page + col) % 2 == 0 else 0x55
            elif pattern == 'white':
                val = 0xFF
            elif pattern == 'black':
                val = 0x00
            elif pattern == 'stripes':
                val = 0xFF if col % 16 < 8 else 0x00
            else:
                val = 0x00
            write_lcd_byte(io, gpio_base, True, val)


def main():
    parser = argparse.ArgumentParser(description='Diagnose ICH9 GPIO LCD hardware health')
    parser.add_argument('--test-pattern', choices=['checker', 'white', 'black', 'stripes'],
                        help='Send a test pattern to the LCD (implies --init)')
    parser.add_argument('--init', action='store_true',
                        help='Reset and reinitialize the LCD controller')
    parser.add_argument('--toggle', action='store_true',
                        help='Toggle-test each LCD pin (briefly pulses pins)')
    args = parser.parse_args()

    if os.geteuid() != 0:
        print('ERROR: Must run as root (need /dev/port access)')
        sys.exit(1)

    passes = 0
    fails = 0

    def result(ok, msg):
        nonlocal passes, fails
        tag = '\033[32mPASS\033[0m' if ok else '\033[31mFAIL\033[0m'
        print(f'  [{tag}] {msg}')
        if ok:
            passes += 1
        else:
            fails += 1

    # --- PCI / GPIOBASE ---
    print('=== ICH9 LPC Bridge ===')
    dev_path, device_id = find_lpc_bridge()
    result(dev_path is not None, f'Intel LPC bridge: {os.path.basename(dev_path) if dev_path else "not found"}'
           + (f' (0x{device_id:04x})' if device_id else ''))
    if not dev_path:
        print('\nCannot continue without LPC bridge.')
        sys.exit(1)

    gpio_base, gpio_ctrl = read_gpiobase(dev_path)
    result(gpio_base != 0, f'GPIOBASE = 0x{gpio_base:04x}')
    gpio_en = bool(gpio_ctrl & 0x10)
    result(gpio_en, f'GPIO enabled in GPIO_CTRL (0x{gpio_ctrl:08x})')

    if gpio_base == 0:
        print('\nCannot continue without GPIOBASE.')
        sys.exit(1)

    io = PortIO()

    # --- LCD Pin Configuration ---
    print('\n=== LCD Pin Configuration ===')
    for name, info in LCD_PINS.items():
        is_gpio, is_output, level = check_pin_config(io, gpio_base, name, info['bit'])
        lvl_str = 'HIGH' if level else 'LOW'
        mode_ok = is_gpio and is_output
        result(mode_ok,
               f"{name:3s} (bit {info['bit']:2d}): {'GPIO' if is_gpio else 'NATIVE':6s} "
               f"{'OUTPUT' if is_output else 'INPUT':6s} {lvl_str:4s}  — {info['desc']}")

    # --- Button Pin State ---
    print('\n=== Button Pins ===')
    for name, info in BUTTON_PINS.items():
        is_gpio, _, level = check_pin_config(io, gpio_base, name, info['bit'])
        pressed = not level
        state = 'PRESSED' if pressed else 'idle'
        result(is_gpio, f"{name:6s} (bit {info['bit']}): {'GPIO' if is_gpio else 'NATIVE':6s} "
               f"level={'HIGH' if level else 'LOW':4s} [{state}]  — {info['desc']}")

    # --- GPIO Register Dump ---
    print('\n=== GPIO Registers ===')
    for rname, off in [('GPIO_USE_SEL', 0x000), ('GP_IO_SEL', 0x004), ('GP_LVL', 0x00C),
                       ('GPIO_USE_SEL2', 0x030), ('GP_IO_SEL2', 0x034), ('GP_LVL2', 0x038)]:
        val = io.inl(gpio_base + off)
        print(f'  {rname:16s} (0x{off:03x}) = 0x{val:08x}')

    # --- Toggle Test ---
    if args.toggle:
        print('\n=== Pin Toggle Test ===')
        for name, info in LCD_PINS.items():
            ok = toggle_test(io, gpio_base, info['bit'])
            result(ok, f'{name} (bit {info["bit"]}): toggle {"responsive" if ok else "STUCK"}')

    # --- LCD Init + Test Pattern ---
    if args.init or args.test_pattern:
        print('\n=== LCD Init ===')
        configure_lcd_pins(io, gpio_base)
        lcd_reset_and_init(io, gpio_base)
        print('  LCD reset + init sequence sent')

        if args.test_pattern:
            print(f'\n=== Test Pattern: {args.test_pattern} ===')
            send_test_pattern(io, gpio_base, args.test_pattern)
            print(f'  Pattern sent — check the front panel display')

    io.close()

    # --- Summary ---
    total = passes + fails
    print(f'\n=== Summary: {passes}/{total} checks passed', end='')
    if fails:
        print(f', \033[31m{fails} failed\033[0m ===')
    else:
        print(f' \033[32m— all OK\033[0m ===')

    sys.exit(1 if fails else 0)


if __name__ == '__main__':
    main()

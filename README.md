<img width="1000" height="500" alt="IMG_20260528_115628953" src="https://github.com/user-attachments/assets/413dcec7-a188-4e0c-bcde-56fd8bec3551" />
<img width="1000" height="500" alt="IMG_20260528_115638640" src="https://github.com/user-attachments/assets/67033ef3-59fb-4a42-a11b-40371a24b909" />

# LenovoEMC PX4-300d

Kernel drivers and userspace tools for the Iomega / Lenovo EMC StorCenter PX4-300d and PX6-300d NAS front-panel LCD and hardware support.

## Hardware

- **SoC**: Intel Atom D525 (x86_64) with ICH9M southbridge
- **Front-panel LCD**: 128×64 monochrome ST7565R, SPI bit-banged over ICH9 GPIO
- **Super I/O**: Fintek F71889 — hwmon via mainline `f71882fg` driver (auto-detected), GPIO via `gpio-f7188x` for status LEDs
- **Front-panel buttons**: SELECT (GPIO4), SCROLL (GPIO5) on ICH9, active-LOW

## LCD Kernel Modules

Both modules drive the ST7565R LCD via SPI bit-banged over ICH9 southbridge GPIOs
(GPIOBASE from PCI config register 0x48). No dependency on the gpio-f7188x driver
for LCD operation.

### ICH9 GPIO Pin Mapping

| Signal | GPIO Bit | Function |
|--------|----------|----------|
| SI (MOSI) | 6 | SPI data |
| SCL (CLK) | 7 | SPI clock |
| RS (Reset) | 16 | LCD reset |
| A0 (D/C) | 19 | Data/Command select |
| CS1 | 21 | Chip select |

### Module Comparison

| | lpc_ich_lenovo.ko | ums8485md.ko |
|---|---|---|
| Interface | `/dev/fb*` + `/dev/lcm` | `/dev/lcm` only |
| LCD init | Deferred (15s workqueue) | Immediate at load |
| Extra features | MFD (watchdog, GPIO, SPI), framebuffer | LCD only |
| Best for | Production use with lcd.py | Simple testing |

`lpc_ich_lenovo` is the preferred module — it provides a standard Linux framebuffer
plus the legacy ioctl interface for backward compatibility.

### Module Parameters (lpc_ich_lenovo)

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `lcd_enable` | bool | true | Enable LCD framebuffer |
| `lcd_contrast` | int | 23 | LCD contrast 0–63 |
| `lcd_refresh_ms` | int | 200 | LCD refresh interval in ms |
| `lcd_init_delay_ms` | int | 15000 | Delay before LCD init (ms) — avoids `register_framebuffer` deadlock during early boot |

Example: `sudo insmod lpc_ich_lenovo.ko lcd_contrast=30 lcd_init_delay_ms=10000`

## Building

### Option 1: OpenWrt Integration

```bash
cd ~/openwrt/package
git clone https://github.com/jaykumar2001/lenovoEMC-px4-300d.git
cd ../..
make menuconfig   # Select packages under Kernel modules
make package/lenovoEMC-px4-300d/{compile,install}
```

### Option 2: Build Against Running Kernel (recommended for Proxmox / Debian)

Build directly on the target NAS using installed kernel headers. This ensures the
module matches the running kernel exactly.

```bash
# Install kernel headers (if not already present)
apt install linux-headers-$(uname -r)

# Build lpc-ich LCD + MFD driver
make -C /lib/modules/$(uname -r)/build M=$(pwd)/Drivers/lpc-ich/src modules

# Build ums8485md legacy LCD driver
make -C /lib/modules/$(uname -r)/build M=$(pwd)/Drivers/ums8485md/src modules

# Build gpio-f7188x (for status LEDs only, not needed for LCD)
make -C /lib/modules/$(uname -r)/build M=$(pwd)/Drivers/gpio-f7188x/src modules
```

### Option 3: Cross-Build Against Kernel Source Tree

When building on a different machine than the target, use a prepared kernel source
tree that matches the target kernel version.

```bash
# Prepare kernel source (one-time)
cd /path/to/linux-source
make defconfig
scripts/config --enable CONFIG_PCI --enable CONFIG_MFD_CORE --enable CONFIG_GPIOLIB \
  --enable CONFIG_FB --enable CONFIG_FB_CORE --enable CONFIG_FB_DEVICE \
  --enable CONFIG_FB_SYS_FILLRECT --enable CONFIG_FB_SYS_COPYAREA \
  --enable CONFIG_FB_SYS_IMAGEBLIT --enable CONFIG_FB_SYS_FOPS
make olddefconfig
make modules_prepare

# Build modules
KDIR=/path/to/linux-source
make -C $KDIR M=$(pwd)/Drivers/lpc-ich/src KBUILD_MODPOST_WARN=1 modules
make -C $KDIR M=$(pwd)/Drivers/ums8485md/src KBUILD_MODPOST_WARN=1 modules
```

`KBUILD_MODPOST_WARN=1` suppresses errors for unresolved symbols that will resolve
at load time on the running kernel. Required when building without a full kernel build.

**Important**: The kernel source version must match the target kernel exactly, including
distribution patches (e.g., Proxmox `-pve` kernels). Mismatched versions will fail at
`insmod` with "Invalid module format".

### Loading

```bash
# Copy to the target NAS
scp Drivers/lpc-ich/src/lpc_ich_lenovo.ko user@nas:/tmp/

# Load ONE of the LCD modules (not both simultaneously)
sudo insmod /tmp/lpc_ich_lenovo.ko
# OR
sudo insmod /tmp/ums8485md.ko
```

### Auto-Load on Boot

To load the modules automatically after every reboot, install them into the kernel
module tree and configure modprobe:

```bash
# Install the .ko files (run on the NAS after building)
sudo cp lpc_ich_lenovo.ko /lib/modules/$(uname -r)/extra/
sudo cp gpio-f7188x.ko /lib/modules/$(uname -r)/extra/    # optional, for LEDs
sudo depmod -a

# Block the in-tree lpc_ich from claiming the LPC bridge
# ("blacklist lpc_ich" alone is insufficient — the module still loads via PCI alias)
echo "install lpc_ich /bin/false" | sudo tee /etc/modprobe.d/blacklist-lpc_ich.conf
sudo update-initramfs -u

# Create modprobe config so they load at boot
echo "lpc_ich_lenovo" | sudo tee /etc/modules-load.d/lpc_ich_lenovo.conf
# Optional — for status LEDs:
echo "gpio-f7188x" | sudo tee /etc/modules-load.d/gpio-f7188x.conf
```

After reboot, verify with `lsmod | grep lpc_ich_lenovo`.

To also start `lcd.py` at boot, create a systemd service:

```bash
sudo tee /etc/systemd/system/lcd-display.service <<'EOF'
[Unit]
Description=Front-panel LCD status display
After=multi-user.target

[Service]
ExecStart=/usr/bin/python3 /path/to/lcd.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable lcd-display
```

### Verifying

```bash
lsmod | grep -E 'lpc_ich_lenovo|ums8485md'
dmesg | tail -20

# For lpc_ich_lenovo — framebuffer device
ls /dev/fb*
cat /sys/class/graphics/fb*/name

# Legacy character device (both modules)
ls /dev/lcm

# Quick framebuffer test
dd if=/dev/urandom of=/dev/fb1 bs=1024 count=1   # random noise
dd if=/dev/zero of=/dev/fb1 bs=1024 count=1       # clear display
```

## lcd.py — Userspace LCD Status Display

Python script that drives the front-panel LCD and reads button input.

### Prerequisites

```bash
pip install Pillow
pip install psutil      # optional — enables disk usage screen
```

### Running

```bash
sudo python3 lcd.py
```

Root is required for `/dev/fb*`, `/dev/lcm`, and `/dev/port` (button polling) access.

The script waits up to 60 seconds for the LCD kernel module to create its device
node, then auto-detects the backend:

| Device exists | Backend | Driver |
|---|---|---|
| `/dev/fb*` (px300d_lcd) | FramebufferBackend | lpc_ich_lenovo |
| `/dev/lcm` only | IoctlBackend | ums8485md or lpc_ich_lenovo |
| Neither after 60s | Exits with error | — |

### Display Screens

1. **Boot logo** — shown for 5 seconds at startup
2. **System Status** — hostname, IP, CPU temp, HD temps, fan speeds (all detected fans), CPU/RAM usage
3. **Disk Usage** (requires psutil) — pie charts for mounted filesystems, RAID status

### Front-Panel Button Controls

Buttons are polled via ICH9 GPIO pins 4 (SELECT) and 5 (SCROLL) through `/dev/port`.

| Action | Effect |
|---|---|
| Short press SELECT | Next screen |
| Long press SELECT (>2s) | Cycle LCD backlight |
| Short press SCROLL | First screen (home) |

## lcd_diag.py — Hardware Diagnostic

Probes ICH9 GPIO and verifies LCD hardware health. Run on the NAS as root.

```bash
# Basic check — LPC bridge, GPIOBASE, pin configuration, button state
sudo python3 lcd_diag.py

# Toggle-test each LCD pin (verifies pins respond to writes)
sudo python3 lcd_diag.py --toggle

# Full test — reset LCD and send a visible pattern
sudo python3 lcd_diag.py --test-pattern checker
```

## Other Drivers

### f71882fg (mainline)

The kernel's built-in `f71882fg` hwmon driver auto-detects the Fintek F71889 Super I/O
and provides fan speed and temperature readings. No out-of-tree driver needed — just
ensure `CONFIG_SENSORS_F71882FG` is enabled (it is on Proxmox/Debian by default).

### gpio-f7188x

Fintek F71889 Super I/O GPIO driver for status LEDs. Not required for LCD operation.

```bash
sudo insmod gpio-f7188x.ko
```

## Reference

- **[arvati/lenovoEMC-300d](https://github.com/arvati/lenovoEMC-300d)** — Original OpenWrt
  package feed for these NAS devices by [@arvati](https://github.com/arvati). This repo
  is based on that work. Thanks to arvati for the initial driver packaging, OpenWrt
  integration, and hardware documentation that made this project possible.
- **`px4px6.patch`** — Original OEM kernel patches from the PX4/PX6 300d firmware,
  including the ICH9 GPIO driver, LCD driver, and Super I/O configuration. Kept as a
  hardware reference document.

## License

GPL v2 — see [LICENSE](LICENSE).

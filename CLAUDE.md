# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What This Is

Kernel drivers and userspace tools for Lenovo EMC (Iomega) StorCenter PX4-300d / PX6-300d NAS front-panel LCD and hardware support. Can be built standalone or as OpenWrt packages.

## Target Hardware

- **SoC**: Intel Atom D525 (x86_64) with Intel ICH9M southbridge
- **Front-panel LCD**: 128×64 monochrome ST7565R controller, SPI bit-banged over ICH9 GPIO
- **Super I/O**: Fintek F71889 — hwmon via mainline `f71882fg` driver (auto-detected by kernel), GPIO via `gpio-f7188x` for status LEDs
- **Front-panel buttons**: SELECT (GPIO4), SCROLL (GPIO5) on ICH9, active-LOW

## Build Commands

### OpenWrt Integration (primary build path)
```bash
cd ~/openwrt/package
git clone https://github.com/arvati/lenovoEMC-300d.git
cd ~/openwrt
make menuconfig   # select desired packages
make package/lenovoEMC-300d/{compile,install}
```

### Standalone Out-of-Tree Kernel Module Build
```bash
# Prepare kernel source (one-time)
cd /home/jkumar/linux-6.17.13
make defconfig
scripts/config --enable CONFIG_PCI --enable CONFIG_MFD_CORE --enable CONFIG_GPIOLIB \
  --enable CONFIG_FB --enable CONFIG_FB_CORE --enable CONFIG_FB_DEVICE \
  --enable CONFIG_FB_SYS_FILLRECT --enable CONFIG_FB_SYS_COPYAREA \
  --enable CONFIG_FB_SYS_IMAGEBLIT --enable CONFIG_FB_SYS_FOPS
make olddefconfig
make modules_prepare

# Build a single driver module
make -C /home/jkumar/linux-6.17.13 M=$(pwd)/Drivers/lpc-ich/src modules
```

## Architecture

### Kernel Drivers (`Drivers/`)

| Directory | Driver | Purpose |
|-----------|--------|---------|
| `lpc-ich` | `lpc_ich_lenovo` | Intel ICH LPC bridge MFD + LCD framebuffer (`/dev/fb*`) + legacy ioctl (`/dev/lcm`) |
| `gpio-f7188x` | `gpio-f7188x` | Fintek F7188x Super I/O GPIO banks (status LEDs, not LCD) |
| `ums8485md` | `lcm` | Legacy standalone LCD character device (predecessor to lpc-ich LCD support) |

Each driver directory follows the pattern: `Makefile` (OpenWrt package definition) + `src/` (kernel source, Kconfig).

### Key Driver Relationship

`lpc-ich` uses ICH9 southbridge GPIO directly (via GPIOBASE I/O ports at PCI config 0x48) for LCD SPI bit-bang. No dependency on `gpio-f7188x` for LCD. The `gpio-f7188x` driver is only needed for Fintek SIO status LEDs.

### LCD SPI Bit-Bang Pin Mapping

LCD pins are on ICH9 southbridge GPIO (GPIOBASE=0x0480), NOT on the Fintek Super I/O:
- SI (MOSI): GPIO6, SCL (CLK): GPIO7
- RS (Reset): GPIO16, A0 (Data/Cmd): GPIO19, CS1: GPIO21

### Userspace Tools

- `lcd.py` — LCD status display with button input, auto-detects framebuffer or ioctl backend
- `lcd_diag.py` — Hardware diagnostic: probes ICH9 GPIO pin config, toggle tests, LCD test patterns

## Conventions

- All Makefiles use OpenWrt package build system conventions (`include $(TOPDIR)/rules.mk`, `KernelPackage/` or `Package/` definitions)
- Kernel drivers use `Kconfig` + single-file `.c` source in `src/`
- The `lpc_ich_lenovo.c` driver targets kernel 6.17+ APIs: uses `strscpy` (not `strlcpy`), `set_writeable` callbacks (not `.writeable` bool), `p2sb_bar()` for BXT SPI
- License: GPL v2

#!/usr/bin/env bash
# Install USBTMC udev rules for common oscilloscope vendors (Linux/WSL).
set -eu

RULE=/etc/udev/rules.d/99-scope-usbtmc.rules
TMP=$(mktemp)

cat >"$TMP" <<'RULES'
# Tektronix, Rigol, Siglent, Keysight/Agilent, LeCroy, Rohde & Schwarz,
# Yokogawa, GW Instek, Hantek, Owon
SUBSYSTEM=="usb", ATTR{idVendor}=="0699", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1ab1", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="f4ec", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="0957", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="2a8d", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="05ff", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="0aad", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="0b21", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="2184", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="0493", MODE="0660", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="5345", MODE="0660", GROUP="plugdev"
RULES

sudo install -m 0644 "$TMP" "$RULE"
rm -f "$TMP"
sudo modprobe usbtmc 2>/dev/null || true
sudo udevadm control --reload-rules
sudo udevadm trigger

echo "installed $RULE"
echo "replug the instrument (or re-run usbipd attach) so the new permissions apply"

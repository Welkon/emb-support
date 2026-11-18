#!/usr/bin/env bash
# Give the current user access to the ATK-Logic analyzer from Linux/WSL.
# Run once with sudo:  sudo -E bash scripts/install_udev.sh
# The udev rule is installed first, so a failed network install cannot block
# permissions. apt is run with the shell proxy when one is set (a plain
# `apt-get update` hangs behind a blocked direct route).
set -uo pipefail

# 1) Permissions: no network needed.
cat > /etc/udev/rules.d/99-atk-logic.rules <<'RULE'
# ALIENTEK ATK-Logic / DL16 / DL32 (Cypress FX3 and CH34x variants)
SUBSYSTEM=="usb", ATTR{idVendor}=="04b4", ATTR{idProduct}=="6a6a", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1a86", ATTR{idProduct}=="6a6b", MODE="0664", GROUP="plugdev"
SUBSYSTEM=="usb", ATTR{idVendor}=="1a86", ATTR{idProduct}=="ffcc", MODE="0664", GROUP="plugdev"
RULE
groupadd -f plugdev || true
usermod -aG plugdev "${SUDO_USER:-$USER}" || true
udevadm control --reload-rules || true
udevadm trigger || true
echo "udev rule installed: /etc/udev/rules.d/99-atk-logic.rules"

# 2) libusb, the only piece that needs a download.
if ldconfig -p | grep -q "libusb-1.0"; then
  echo "libusb-1.0 already present"
  exit 0
fi
proxy_args=()
if [[ -n "${https_proxy:-}" ]]; then
  proxy_args=(-o "Acquire::http::Proxy=${https_proxy}" -o "Acquire::https::Proxy=${https_proxy}")
  echo "using proxy ${https_proxy}"
fi
if command -v apt-get >/dev/null; then
  if timeout 240 apt-get "${proxy_args[@]}" update -qq && \
     timeout 240 apt-get "${proxy_args[@]}" install -y libusb-1.0-0; then
    echo "libusb-1.0 installed"
    exit 0
  fi
  echo "apt failed (network/proxy); the udev rule is still installed." >&2
  echo "run the two apt-get commands by hand with your proxy, then re-attach the device." >&2
  exit 1
fi
echo "install libusb-1.0 for your distribution first" >&2
exit 1

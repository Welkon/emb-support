#!/usr/bin/env bash
set -eu

RULE_PATH="/etc/udev/rules.d/99-tektronix-tbs1102b.rules"
TMP_RULE="$(mktemp)"

cat >"$TMP_RULE" <<'EOF'
SUBSYSTEM=="usb", ATTR{idVendor}=="0699", ATTR{idProduct}=="0368", MODE="0660", GROUP="plugdev"
EOF

install -m 0644 "$TMP_RULE" "$RULE_PATH"
rm -f "$TMP_RULE"

udevadm control --reload-rules
udevadm trigger --attr-match=idVendor=0699 --attr-match=idProduct=0368 || true

echo "Installed $RULE_PATH"
echo "Reattach the scope with usbipd or reconnect the USB cable if permissions do not refresh immediately."

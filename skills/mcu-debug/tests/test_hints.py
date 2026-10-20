"""The agent-facing error must carry the next step, not just the exception."""


def test_hint_for_transfer_error(dap):
    hint = dap.hint_for("TransferError: SWD/JTAG communication failure (No ACK); check USB cable")
    assert hint and "clock" in hint


def test_hint_for_generic_cmsis_dap(dap):
    hint = dap.hint_for("Board ID EA16 is not recognized")
    assert hint and "-t" in hint and "pack" in hint.lower()


def test_hint_for_missing_probe(dap):
    hint = dap.hint_for("No available debug probes are connected")
    assert hint and "usbipd" in hint


def test_hint_for_unknown_text(dap):
    assert dap.hint_for("everything is fine") is None

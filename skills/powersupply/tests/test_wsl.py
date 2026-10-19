SAMPLE = """Connected:
BUSID  VID:PID    DEVICE                                                        STATE
1-4    1a86:7523  USB-SERIAL CH340                                              Not shared
2-3    2e3c:af01  ALIENTEK DP100                                                Shared
2-4    1ab1:0441  Rigol DP832                                                   Attached
"""


def test_parse_usbipd(module):
    from psuscpi.wsl import parse_usbipd
    devs = parse_usbipd(SAMPLE)
    assert [d["busid"] for d in devs] == ["1-4", "2-3", "2-4"]
    dp = next(d for d in devs if d["vid"] == "2e3c")
    assert dp["vendor"] == "ALIENTEK/FNIRSI" and dp["state"] == "Shared"


def test_attach_hints(module):
    from psuscpi.wsl import attach_hint, parse_usbipd
    devs = parse_usbipd(SAMPLE)
    ch340 = next(d for d in devs if d["vid"] == "1a86")
    hints = attach_hint(ch340)
    assert any("bind --busid 1-4" in h for h in hints)
    assert any("attach --wsl --busid 1-4" in h for h in hints)
    rigol = next(d for d in devs if d["vid"] == "1ab1")
    assert attach_hint(rigol) == []

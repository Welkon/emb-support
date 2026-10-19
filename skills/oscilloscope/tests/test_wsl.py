SAMPLE = """Connected:
BUSID  VID:PID    DEVICE                                                        STATE
1-4    0489:e0d8  RZ616 Bluetooth(R) Adapter                                    Not shared
2-3    0699:0368  Tektronix TBS1102B                                           Not shared
2-4    1ab1:0441  Rigol DHO804                                                 Shared
3-1    174f:1811  Integrated Camera                                            Attached
"""


def test_parse_usbipd(scope):
    devices = scope.parse_usbipd(SAMPLE)
    assert [d["busid"] for d in devices] == ["1-4", "2-3", "2-4", "3-1"]
    tek = next(d for d in devices if d["vid"] == "0699")
    assert tek["vendor"] == "Tektronix"
    assert tek["state"] == "Not shared"
    rigol = next(d for d in devices if d["vid"] == "1ab1")
    assert rigol["vendor"] == "Rigol"
    assert next(d for d in devices if d["vid"] == "0489")["vendor"] is None


def test_attach_hint_requires_bind(scope):
    tek = next(d for d in scope.parse_usbipd(SAMPLE) if d["vid"] == "0699")
    hints = scope.attach_hint(tek)
    assert any("bind --busid 2-3" in h for h in hints)
    assert any("attach --wsl --busid 2-3" in h for h in hints)


def test_attach_hint_shared_and_attached(scope):
    devices = scope.parse_usbipd(SAMPLE)
    rigol = next(d for d in devices if d["vid"] == "1ab1")
    hints = scope.attach_hint(rigol)
    assert any("attach --wsl --busid 2-4" in h for h in hints)
    assert not any("bind" in h for h in hints)
    cam = next(d for d in devices if d["vid"] == "174f")
    assert scope.attach_hint(cam) == []

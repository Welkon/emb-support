import json
import threading
import urllib.error
import urllib.request

import pytest


class FakeDevice:
    idn = "FAKE,PSU,SN,1.0"
    family = "fake"
    channels = (1, 2)
    supports_power = True
    supports_ovp = True
    supports_ocp = True
    supports_output_state = True

    def __init__(self):
        self.v = {1: 0.0, 2: 0.0}
        self.i = {1: 0.0, 2: 0.0}
        self.out = {1: False, 2: False}

    def close(self): pass
    def set_voltage(self, ch, v): self.v[ch] = v
    def set_current(self, ch, a): self.i[ch] = a
    def get_voltage(self, ch): return self.v[ch]
    def get_current(self, ch): return self.i[ch]
    def measure_voltage(self, ch): return self.v[ch]
    def measure_current(self, ch): return self.i[ch]
    def measure_power(self, ch): return self.v[ch] * self.i[ch]
    def output(self, ch, on): self.out[ch] = on
    def output_state(self, ch): return "ON" if self.out[ch] else "OFF"
    def set_ovp(self, ch, v): self.ovp = v
    def set_ocp(self, ch, a): self.ocp = a


@pytest.fixture
def server():
    from psuscpi.web import PsuWebServer
    dev = FakeDevice()
    srv = PsuWebServer(dev, 30, 5, bind="127.0.0.1", port=0)
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield srv, dev
    srv.close()


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=3) as r:
        return r.status, r.read()


def _post(port, path, body):
    req = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}", data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=3) as r:
        return r.status, json.loads(r.read())


def test_index_and_state(server):
    srv, dev = server
    status, body = _get(srv.port, "/")
    assert status == 200 and b"<title>Power Supply</title>" in body
    status, body = _get(srv.port, "/api/state?ch=1")
    data = json.loads(body)
    assert data["family"] == "fake" and data["channels"] == [1, 2]
    assert data["limits"]["max_voltage"] == 30.0


def test_set_and_output(server):
    srv, dev = server
    status, data = _post(srv.port, "/api/set", {"ch": 1, "voltage": 5, "current": 1})
    assert status == 200
    assert dev.v[1] == 5 and dev.i[1] == 1
    assert data["setpoint"]["voltage"] == 5

    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, "/api/output", {"ch": 1, "on": True})
    assert e.value.code == 400

    status, data = _post(srv.port, "/api/output", {"ch": 1, "on": True, "confirm": True})
    assert status == 200 and dev.out[1] is True

    status, data = _post(srv.port, "/api/all-off", {})
    assert dev.out[1] is False


def test_limits_enforced(server):
    srv, dev = server
    with pytest.raises(urllib.error.HTTPError) as e:
        _post(srv.port, "/api/set", {"ch": 1, "voltage": 40})
    assert e.value.code == 400
    assert dev.v[1] == 0.0

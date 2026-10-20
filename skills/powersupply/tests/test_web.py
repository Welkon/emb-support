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
    supports_input_voltage = True
    supports_temperature = True

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
    def measure_input_voltage(self, ch): return 12.0
    def measure_temperature(self, ch): return 35.5
    def device_info(self): return {"model": "FAKE"}
    def status(self, ch): return {"output_mode": "ON" if self.out[ch] else "OFF", "work_state": 0}
    def output(self, ch, on): self.out[ch] = on
    def output_state(self, ch): return "ON" if self.out[ch] else "OFF"
    def set_ovp(self, ch, v): self.ovp = v
    def set_ocp(self, ch, a): self.ocp = a


@pytest.fixture
def server():
    from psuscpi.web import PsuWebServer
    dev = FakeDevice()
    srv = PsuWebServer(dev, 30, 5, bind="127.0.0.1", port=0, start_sampler=False)
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
    with urllib.request.urlopen(f"http://127.0.0.1:{srv.port}/", timeout=3) as r:
        body = r.read()
        assert r.status == 200 and r.headers.get("Cache-Control") == "no-cache"
    assert b"<title>Power Supply</title>" in body
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


def test_state_is_reentrant(server):
    """The handler holds srv.lock while _state() reads history/snapshot."""
    srv, _ = server
    result = {}
    done = threading.Event()

    def worker():
        with srv.lock:
            result["state"] = srv._state(1)
        done.set()

    t = threading.Thread(target=worker, daemon=True)
    t.start()
    assert done.wait(2), "state() deadlocked under the server lock"
    assert result["state"]["ch"] == 1


def test_history_endpoint(server):
    import time
    srv, _ = server
    now = int(time.time() * 1000)
    srv.history[1].append({"t": now - 250, "voltage": 5.0, "current": 0.5, "power": 2.5})
    srv.history[1].append({"t": now, "voltage": 5.1, "current": 0.5, "power": 2.55})
    status, body = _get(srv.port, "/api/history?ch=1&seconds=2")
    data = json.loads(body)
    assert status == 200 and data["ok"] and len(data["samples"]) == 2
    assert data["samples"][-1]["voltage"] == 5.1


def test_sampler_fills_history():
    import time
    from psuscpi.web import PsuWebServer
    dev = FakeDevice()
    srv = PsuWebServer(dev, 30, 5, bind="127.0.0.1", port=0)
    try:
        deadline = time.time() + 2
        while time.time() < deadline and not srv.history[1]:
            time.sleep(0.02)
        assert srv.history[1], "background sampler produced no samples"
        assert srv.history[1][-1]["voltage"] == dev.v[1]
    finally:
        srv._stop.set()
        srv.httpd.server_close()

"""Synthetic-only lifecycle and request-boundary checks for CTRL-SP-02."""
import http.client
import json
import importlib.util
from pathlib import Path
import unittest

module_path = Path(__file__).resolve().parents[1] / "control_dashboard_spike.py"
spec = importlib.util.spec_from_file_location("control_dashboard_spike", module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
Controller = module.Controller


class ControlDashboardSpikeTests(unittest.TestCase):
    def setUp(self):
        self.control = Controller()
        self.control.start()
        self.host, self.port = self.control.address
        self.origin = f"http://{self.host}:{self.port}"

    def tearDown(self):
        self.control.close()

    def request(self, method, path, *, origin=None, csrf=None, host=None):
        conn = http.client.HTTPConnection(self.host, self.port, timeout=2)
        headers = {"Host": host or f"{self.host}:{self.port}"}
        if origin is not None:
            headers["Origin"] = origin
        if csrf is not None:
            headers["X-CSRF-Token"] = csrf
        conn.request(method, path, headers=headers)
        response = conn.getresponse()
        body = json.loads(response.read())
        conn.close()
        return response.status, body

    def status(self):
        code, body = self.request("GET", "/api/status")
        self.assertEqual(code, 200)
        return body

    def operate(self, service, action, csrf):
        return self.request("POST", f"/api/services/{service}/{action}", origin=self.origin, csrf=csrf)

    def test_controller_survives_child_stop_start_and_client_disconnect(self):
        initial = self.status()
        self.assertEqual(initial["fake_child"], "stopped")
        self.assertEqual(self.operate("fake-child", "start", initial["csrf"])[0], 200)
        self.assertTrue(self.control.child.running)

        # A tab closing drops its connection, not the independent controller.
        disconnected = http.client.HTTPConnection(self.host, self.port, timeout=2)
        disconnected.request("GET", "/api/status")
        disconnected.close()
        self.assertEqual(self.status()["controller"], "running")
        self.assertEqual(self.status()["fake_child"], "running")
        code, stopped = self.operate("fake-child", "stop", initial["csrf"])
        self.assertEqual((code, stopped["fake_child"]), (200, "stopped"))
        self.assertEqual(self.status()["controller"], "running")

    def test_host_origin_and_csrf_guards_reject_mutations(self):
        csrf = self.status()["csrf"]
        bad_host = self.request("GET", "/api/status", host="attacker.invalid")[0]
        bad_origin = self.request("POST", "/api/services/fake-child/start", origin="http://attacker.invalid", csrf=csrf)[0]
        no_csrf = self.request("POST", "/api/services/fake-child/start", origin=self.origin)[0]
        self.assertEqual((bad_host, bad_origin, no_csrf), (403, 403, 403))
        self.assertFalse(self.control.child.running)

    def test_fixed_allowlist_rejects_other_targets_and_actions(self):
        csrf = self.status()["csrf"]
        codes = [
            self.operate("neo4j", "stop", csrf)[0],
            self.operate("fake-child", "restart", csrf)[0],
            self.operate("fake-child;id", "start", csrf)[0],
        ]
        self.assertEqual(codes, [404, 404, 404])
        self.assertFalse(self.control.child.running)
        self.assertEqual(set(self.control.allowed), {("fake-child", "start"), ("fake-child", "stop")})

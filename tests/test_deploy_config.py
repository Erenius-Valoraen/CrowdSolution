"""Deployment settings: Snowflake from environment variables, /tmp storage on Vercel, stateless spoken summaries."""
import importlib
import os
import unittest
from unittest import mock

os.environ.setdefault("COMMUNITY_MEMORY", "off")

from fastapi.testclient import TestClient  # noqa: E402

from api import main, service, storage  # noqa: E402
from legit import config, db  # noqa: E402


class SnowflakeParamsTest(unittest.TestCase):
    def test_uses_access_token_from_environment(self):
        with mock.patch.multiple(config, SNOWFLAKE_ACCOUNT="ACME-X1", SNOWFLAKE_USER="BOT", SNOWFLAKE_TOKEN="t0ken"):
            params = db.connect_params()
        self.assertEqual(params["authenticator"], "PROGRAMMATIC_ACCESS_TOKEN")
        self.assertEqual((params["account"], params["user"], params["token"]), ("ACME-X1", "BOT", "t0ken"))
        self.assertNotIn("connection_name", params)

    def test_falls_back_to_local_connection(self):
        with mock.patch.multiple(config, SNOWFLAKE_ACCOUNT=None, SNOWFLAKE_USER=None, SNOWFLAKE_TOKEN=None):
            self.assertEqual(db.connect_params(), {"connection_name": config.SNOWFLAKE_CONNECTION})


class StoragePathTest(unittest.TestCase):
    def tearDown(self):
        importlib.reload(storage)

    def test_vercel_uses_tmp(self):
        with mock.patch.dict(os.environ, {"VERCEL": "1"}, clear=False):
            os.environ.pop("TRUSTIFY_DB_PATH", None)
            self.assertEqual(str(importlib.reload(storage).DB_PATH).replace("\\", "/"), "/tmp/trustify-history.db")

    def test_explicit_path_wins(self):
        with mock.patch.dict(os.environ, {"VERCEL": "1", "TRUSTIFY_DB_PATH": "custom/history.db"}):
            self.assertEqual(importlib.reload(storage).DB_PATH.as_posix(), "custom/history.db")


class StatelessSpokenSummaryTest(unittest.TestCase):
    client = TestClient(main.app)
    report = {"id": "chk_elsewhere", "overall": "HIGH RISK", "counts": {}, "findings": []}

    def test_uses_report_from_page_when_scan_is_on_another_instance(self):
        with mock.patch.object(main.storage, "get_scan", return_value=None), \
                mock.patch.object(main.storage, "update_payload"), \
                mock.patch.object(service, "spoken_summary", return_value=("This looks high risk.", "template")) as make:
            res = self.client.post("/api/scans/chk_elsewhere/spoken-summary", json={"report": self.report})
        self.assertEqual(res.status_code, 200)
        self.assertEqual(make.call_args.args[0]["id"], "chk_elsewhere")

    def test_report_for_a_different_scan_is_ignored(self):
        with mock.patch.object(main.storage, "get_scan", return_value=None):
            res = self.client.post("/api/scans/chk_other/spoken-summary", json={"report": self.report})
        self.assertEqual(res.status_code, 404)


if __name__ == "__main__":
    unittest.main()

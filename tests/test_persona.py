"""Offline tests for persona.py (stdlib unittest; runs under pytest too).

Run: .venv/bin/python -m unittest tests.test_persona -v
Live sandbox check (only if PERSONA_API_KEY + PERSONA_TEMPLATE_ID are in .env):
     PERSONA_LIVE=1 .venv/bin/python -m unittest tests.test_persona -v
"""
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import persona  # noqa: E402

FAKE_ENV = {"PERSONA_API_KEY": "test_key", "PERSONA_TEMPLATE_ID": "itmpl_test"}


def _resp(status_code=200, body=None):
    r = mock.Mock()
    r.status_code = status_code
    r.json.return_value = body or {}
    r.text = str(body)
    return r


def _inquiry(status, inq_id="inq_123", meta=None):
    body = {"data": {"id": inq_id, "type": "inquiry", "attributes": {"status": status}}}
    if meta is not None:
        body["meta"] = meta
    return body


class PersonaOfflineTests(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, FAKE_ENV)
        self.env.start()
        self.sess = mock.patch.object(persona, "_session")
        self.session = self.sess.start()

    def tearDown(self):
        self.sess.stop()
        self.env.stop()

    def test_copy(self):
        self.assertEqual(
            persona.PERSONA_COPY,
            "Persona verifies who is approving — not legal authority.",
        )

    def test_missing_key_raises_before_network(self):
        with mock.patch.dict(os.environ, {"PERSONA_API_KEY": ""}):
            with self.assertRaisesRegex(RuntimeError, "PERSONA_API_KEY"):
                persona.get_status("inq_123")
            with self.assertRaisesRegex(RuntimeError, "PERSONA_API_KEY"):
                persona.create_inquiry("daughter-reviewer")
        self.session.request.assert_not_called()

    def test_missing_template_raises(self):
        with mock.patch.dict(os.environ, {"PERSONA_TEMPLATE_ID": ""}):
            with self.assertRaisesRegex(RuntimeError, "PERSONA_TEMPLATE_ID"):
                persona.create_inquiry("daughter-reviewer")

    def test_status_parsing_all_documented_values(self):
        for status in persona.STATUSES:
            self.session.request.return_value = _resp(200, _inquiry(status))
            self.assertEqual(persona.get_status("inq_123"), status)
            self.assertEqual(persona.is_approved("inq_123"), status == "approved")

    def test_unknown_status_passes_through_not_approved(self):
        self.session.request.return_value = _resp(200, _inquiry("some_new_status"))
        self.assertEqual(persona.get_status("inq_1"), "some_new_status")
        self.assertFalse(persona.is_approved("inq_1"))

    def test_malformed_response_raises(self):
        self.session.request.return_value = _resp(200, {"data": {}})
        with self.assertRaises(RuntimeError):
            persona.get_status("inq_1")

    def test_http_error_raises(self):
        self.session.request.return_value = _resp(
            401, {"errors": [{"title": "Unauthorized"}]}
        )
        with self.assertRaisesRegex(RuntimeError, "401"):
            persona.is_approved("inq_1")

    def test_get_request_shape(self):
        self.session.request.return_value = _resp(200, _inquiry("pending"))
        persona.get_status("inq_abc")
        args, kwargs = self.session.request.call_args
        self.assertEqual(args, ("GET", "https://api.withpersona.com/api/v1/inquiries/inq_abc"))
        self.assertEqual(kwargs["headers"]["Authorization"], "Bearer test_key")
        self.assertEqual(kwargs["headers"]["Persona-Version"], persona.PERSONA_VERSION)
        self.assertEqual(kwargs["timeout"], persona.TIMEOUT)

    def test_create_inquiry_uses_one_time_link_from_meta(self):
        self.session.request.return_value = _resp(
            201,
            _inquiry("created", "inq_new", meta={
                "one-time-link": "https://withpersona.com/verify?code=abc",
                "one-time-link-short": "https://perso.na/x",
            }),
        )
        out = persona.create_inquiry("daughter-reviewer", "Maya", "Reed")
        self.assertEqual(out, {"inquiry_id": "inq_new",
                               "hosted_url": "https://withpersona.com/verify?code=abc"})
        args, kwargs = self.session.request.call_args
        self.assertEqual(args, ("POST", "https://api.withpersona.com/api/v1/inquiries"))
        body = kwargs["json"]
        self.assertEqual(body["data"]["attributes"]["inquiry-template-id"], "itmpl_test")
        self.assertEqual(body["data"]["attributes"]["fields"],
                         {"name-first": "Maya", "name-last": "Reed"})
        self.assertEqual(body["meta"]["auto-create-account-reference-id"], "daughter-reviewer")
        self.assertTrue(body["meta"]["auto-create-one-time-link"])
        self.assertEqual(kwargs["timeout"], persona.TIMEOUT)

    def test_create_inquiry_falls_back_to_generate_link(self):
        self.session.request.side_effect = [
            _resp(201, _inquiry("created", "inq_new", meta={})),
            _resp(200, _inquiry("created", "inq_new",
                                meta={"one-time-link": "https://withpersona.com/verify?code=z",
                                      "one-time-link-short": "s"})),
        ]
        out = persona.create_inquiry("daughter-reviewer")
        self.assertEqual(out["hosted_url"], "https://withpersona.com/verify?code=z")
        args, _ = self.session.request.call_args
        self.assertEqual(args[1], "https://api.withpersona.com/api/v1/inquiries/inq_new/generate-one-time-link")

    def test_template_attr_by_prefix(self):
        self.assertEqual(persona._template_attr("tmpl_1"), "template-id")
        self.assertEqual(persona._template_attr("itmpl_1"), "inquiry-template-id")
        self.assertEqual(persona._template_attr("itmplv_1"), "inquiry-template-version-id")

    def test_simulate_approve_body(self):
        self.session.request.return_value = _resp(200, _inquiry("approved"))
        self.assertEqual(persona.simulate_approve("inq_1"), "approved")
        args, kwargs = self.session.request.call_args
        self.assertTrue(args[1].endswith("/inquiries/inq_1/perform-simulate-actions"))
        self.assertEqual(kwargs["json"], {"meta": {"simulate-actions": [{"type": "approve_inquiry"}]}})


@unittest.skipUnless(
    os.getenv("PERSONA_LIVE") == "1" and os.getenv("PERSONA_API_KEY"),
    "live sandbox test: set PERSONA_LIVE=1 with PERSONA_API_KEY in .env",
)
class PersonaLiveSandboxTest(unittest.TestCase):
    def test_create_and_status(self):
        out = persona.create_inquiry("daughter-reviewer")
        print("\nlive inquiry:", out["inquiry_id"], "link:", bool(out["hosted_url"]))
        status = persona.get_status(out["inquiry_id"])
        print("live status:", status)
        self.assertIn(status, persona.STATUSES)


if __name__ == "__main__":
    unittest.main(verbosity=2)

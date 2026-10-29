import io
import json
import unittest
import urllib.error
from datetime import date

import ai_coach
import planner

TODAY = date(2026, 10, 25)


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_returning(payload):
    seen = {}

    def opener(request, timeout=None):
        seen["url"] = request.full_url
        seen["headers"] = dict(request.header_items())
        seen["body"] = json.loads(request.data.decode())
        return FakeResponse(json.dumps(payload).encode())
    opener.seen = seen
    return opener


class AICoachTests(unittest.TestCase):
    def call(self, opener, **kw):
        args = dict(base_url="https://api.example.com/v1/", api_key="k", model="m",
                    messages=[{"role": "user", "content": "hi"}])
        args.update(kw)
        return ai_coach.chat(opener=opener, **args)

    def test_success_and_request_shape(self):
        op = opener_returning({"choices": [{"message": {"content": "<think>x</think>Do this."}}]})
        self.assertEqual(self.call(op), "Do this.")
        self.assertEqual(op.seen["url"], "https://api.example.com/v1/chat/completions")
        self.assertEqual(op.seen["headers"]["Authorization"], "Bearer k")
        self.assertEqual(op.seen["body"]["model"], "m")

    def test_validation_errors(self):
        op = opener_returning({})
        with self.assertRaises(ai_coach.AIError): self.call(op, api_key="")
        with self.assertRaises(ai_coach.AIError): self.call(op, model=" ")
        with self.assertRaises(ai_coach.AIError): self.call(op, base_url="ftp://x")

    def test_provider_errors_are_user_safe(self):
        def http_error(request, timeout=None):
            raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"secret body"))
        with self.assertRaises(ai_coach.AIError) as cm: self.call(http_error)
        self.assertIn("401", str(cm.exception)); self.assertNotIn("secret", str(cm.exception))

        def net_error(request, timeout=None):
            raise urllib.error.URLError("dns")
        with self.assertRaises(ai_coach.AIError): self.call(net_error)
        for bad in ({}, {"choices": []}, {"choices": [{"message": {"content": "  "}}]}):
            with self.assertRaises(ai_coach.AIError): self.call(opener_returning(bad))

    def test_context_and_messages(self):
        tasks = planner.demo_tasks(TODAY)
        plan = planner.build_plan(tasks, 60, TODAY)
        ctx = ai_coach.build_context(tasks, plan, TODAY, 60)
        self.assertIn("Calculus problem set 5", ctx)
        msgs = ai_coach.build_messages(ctx, "")
        self.assertEqual([m["role"] for m in msgs], ["system", "user"])
        self.assertIn("focus on today", msgs[1]["content"])


if __name__ == "__main__":
    unittest.main()

import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import Mock

from push_dispatch import (
    PushDispatchError,
    acknowledge_pending,
    dispatch_notifications,
    post_dispatch,
)


def response_payload(sent=0, skipped=0, devices=0, removed=0, failed=0, notifications=0):
    return {
        "notifications": notifications,
        "devices": devices,
        "sent": sent,
        "skipped": skipped,
        "removed": removed,
        "failed": failed,
    }


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


class PushDispatchTests(unittest.TestCase):
    def test_request_uses_explicit_user_agent_and_bearer_token(self):
        captured = {}

        def opener(request, timeout):
            captured["request"] = request
            captured["timeout"] = timeout
            return FakeResponse(response_payload())

        post_dispatch("https://worker.example", "test-token", [], opener=opener, sleeper=lambda _: None)

        request = captured["request"]
        self.assertEqual(request.get_header("User-agent"), "PANS-Schedule-Updater/1.0 (+https://plan.mandaro.eu)")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-token")
        self.assertEqual(captured["timeout"], 30)
        self.assertEqual(json.loads(request.data), {"notifications": []})

    def test_noop_preflight_accepts_empty_queue_without_devices(self):
        result = dispatch_notifications(
            "https://worker.example",
            "test-token",
            [],
            opener=lambda request, timeout: FakeResponse(response_payload()),
            sleeper=lambda _: None,
        )
        self.assertEqual(result, [])

    def test_notification_requires_confirmed_delivery_or_previous_delivery(self):
        notification = {"id": "event-1", "message": "Zmiana"}
        with self.assertRaisesRegex(PushDispatchError, "Brak potwierdzonego dostarczenia"):
            dispatch_notifications(
                "https://worker.example",
                "test-token",
                [notification],
                opener=lambda request, timeout: FakeResponse(response_payload(notifications=1)),
                sleeper=lambda _: None,
            )

    def test_http_403_is_not_retried_and_surfaces_cloudflare_body(self):
        calls = []

        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(
                "https://worker.example/dispatch",
                403,
                "Forbidden",
                {"server": "cloudflare", "cf-ray": "test-ray"},
                io.BytesIO(b"error code: 1010"),
            )

        with self.assertRaisesRegex(PushDispatchError, "HTTP 403"):
            post_dispatch(
                "https://worker.example",
                "test-token",
                [],
                opener=opener,
                sleeper=lambda _: None,
            )
        self.assertEqual(len(calls), 1)

    def test_http_503_is_retried_and_then_succeeds(self):
        calls = []
        sleeps = []

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise HTTPError(
                    "https://worker.example/dispatch",
                    503,
                    "Unavailable",
                    {},
                    io.BytesIO(b"temporary"),
                )
            return FakeResponse(response_payload())

        result = post_dispatch(
            "https://worker.example",
            "test-token",
            [],
            opener=opener,
            sleeper=sleeps.append,
        )
        self.assertEqual(result["failed"], 0)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1])

    def test_queue_acknowledges_only_confirmed_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pending_path = Path(temp_dir) / "pending_push.json"
            pending_path.write_text(json.dumps({
                "notifications": [
                    {"id": "event-1", "message": "Wysłano"},
                    {"id": "event-2", "message": "Nadal oczekuje"},
                ]
            }), encoding="utf-8")

            acknowledge_pending(pending_path, ["event-1"])

            remaining = json.loads(pending_path.read_text(encoding="utf-8"))["notifications"]
            self.assertEqual(remaining, [{"id": "event-2", "message": "Nadal oczekuje"}])

    def test_queue_acknowledgement_rejects_unknown_ids(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            pending_path = Path(temp_dir) / "pending_push.json"
            original = {"notifications": [{"id": "event-1"}]}
            pending_path.write_text(json.dumps(original), encoding="utf-8")

            with self.assertRaisesRegex(PushDispatchError, "nie znajdują się"):
                acknowledge_pending(pending_path, ["unknown"])

            self.assertEqual(json.loads(pending_path.read_text(encoding="utf-8")), original)

    def test_large_queue_is_sent_in_batches_of_fifty(self):
        notifications = [{"id": f"event-{index}"} for index in range(51)]
        batch_sizes = []

        def opener(request, timeout):
            count = len(json.loads(request.data)["notifications"])
            batch_sizes.append(count)
            return FakeResponse(response_payload(sent=count, devices=1, notifications=count))

        delivered = dispatch_notifications(
            "https://worker.example",
            "test-token",
            notifications,
            opener=opener,
            sleeper=lambda _: None,
        )

        self.assertEqual(batch_sizes, [50, 1])
        self.assertEqual(len(delivered), 51)


if __name__ == "__main__":
    unittest.main()

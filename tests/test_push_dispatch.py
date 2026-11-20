import io
import json
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from push_dispatch import (
    PushDispatchError,
    acknowledge_pending,
    dispatch_notifications,
    post_dispatch,
)


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return self.payload


def response_payload(**overrides):
    payload = {
        "notifications": 1,
        "devices": 1,
        "sent": 1,
        "skipped": 0,
        "removed": 0,
        "failed": 0,
    }
    payload.update(overrides)
    return payload


class PushDispatchTests(unittest.TestCase):
    def test_successful_dispatch_parses_response_and_uses_authorization(self):
        calls = []

        def opener(request, timeout):
            calls.append((request, timeout))
            return FakeResponse(response_payload())

        result = post_dispatch(
            "https://push.example",
            "secret-token",
            [{"id": "notification-1", "message": "Zmiana planu"}],
            opener=opener,
            sleeper=lambda _: self.fail("Nie powinno być retry"),
            attempts=1,
        )

        self.assertEqual(result["sent"], 1)
        self.assertEqual(calls[0][0].get_header("Authorization"), "Bearer secret-token")
        self.assertEqual(calls[0][0].get_method(), "POST")
        self.assertEqual(calls[0][1], 30)

    def test_http_403_is_not_retried_and_is_reported_clearly(self):
        calls = []
        sleeps = []

        def opener(request, timeout):
            calls.append(request)
            raise HTTPError(
                request.full_url, 403, "Forbidden", {},
                io.BytesIO(b"invalid dispatch token"),
            )

        with self.assertRaisesRegex(PushDispatchError, "HTTP 403"):
            post_dispatch(
                "https://push.example",
                "wrong-token",
                [{"id": "notification-1"}],
                opener=opener,
                sleeper=sleeps.append,
                attempts=3,
            )

        self.assertEqual(len(calls), 1)
        self.assertEqual(sleeps, [])

    def test_http_503_is_retried_then_succeeds(self):
        calls = []
        sleeps = []
        failure = HTTPError(
            "https://push.example/dispatch", 503, "Service unavailable", {},
            io.BytesIO(b"temporary failure"),
        )

        def opener(request, timeout):
            calls.append(request)
            if len(calls) == 1:
                raise failure
            return FakeResponse(response_payload())

        result = post_dispatch(
            "https://push.example",
            "secret-token",
            [{"id": "notification-1"}],
            opener=opener,
            sleeper=sleeps.append,
            attempts=2,
        )

        self.assertEqual(result["sent"], 1)
        self.assertEqual(len(calls), 2)
        self.assertEqual(sleeps, [1])

    def test_pending_notifications_are_not_acknowledged_when_no_device_received_them(self):
        payload = response_payload(devices=0, sent=0, skipped=0, removed=0)
        opener = lambda request, timeout: FakeResponse(payload)

        with self.assertRaisesRegex(PushDispatchError, "Brak potwierdzonego dostarczenia"):
            dispatch_notifications(
                "https://push.example",
                "secret-token",
                [{"id": "notification-1"}],
                opener=opener,
                sleeper=lambda _: None,
            )

    def test_failed_device_delivery_keeps_the_batch_unacknowledged(self):
        opener = lambda request, timeout: FakeResponse(response_payload(sent=0, failed=1))
        with self.assertRaisesRegex(PushDispatchError, "błędów dostarczenia"):
            dispatch_notifications(
                "https://push.example",
                "secret-token",
                [{"id": "notification-1"}],
                opener=opener,
                sleeper=lambda _: None,
            )

    def test_acknowledge_removes_only_confirmed_notification_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_push.json"
            path.write_text(json.dumps({
                "updated_at": "2026-11-20 08:00",
                "notifications": [
                    {"id": "sent-1"},
                    {"id": "still-pending-2"},
                    {"id": "still-pending-3"},
                ],
            }), encoding="utf-8")

            acknowledge_pending(path, ["sent-1"])
            stored = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(
                [item["id"] for item in stored["notifications"]],
                ["still-pending-2", "still-pending-3"],
            )

    def test_acknowledge_rejects_unknown_ids_without_mutating_the_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "pending_push.json"
            original = {
                "notifications": [{"id": "pending-1"}],
                "updated_at": "2026-11-20 08:00",
            }
            path.write_text(json.dumps(original), encoding="utf-8")

            with self.assertRaisesRegex(PushDispatchError, "nie znajdują się"):
                acknowledge_pending(path, ["unknown-id"])

            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), original)

    def test_invalid_worker_counters_are_rejected(self):
        invalid = response_payload(sent=-1)
        opener = lambda request, timeout: FakeResponse(invalid)
        with self.assertRaisesRegex(PushDispatchError, "Nieprawidłowa wartość pola sent"):
            post_dispatch(
                "https://push.example",
                "secret-token",
                [{"id": "notification-1"}],
                opener=opener,
                sleeper=lambda _: None,
                attempts=1,
            )


if __name__ == "__main__":
    unittest.main()

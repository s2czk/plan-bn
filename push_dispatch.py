import json
import os
import time
import urllib.error
import urllib.request
from pathlib import Path

PUSH_PAYLOAD_FILE = Path("push_payload.json")
PENDING_PUSH_FILE = Path("pending_push.json")
USER_AGENT = "PANS-Schedule-Updater/1.0 (+https://plan.mandaro.eu)"
REQUIRED_RESPONSE_FIELDS = {"notifications", "devices", "sent", "skipped", "removed", "failed"}


class PushDispatchError(RuntimeError):
    """Błąd konfiguracji lub niedostępności dostarczenia Push."""


def post_dispatch(worker_url, token, notifications, opener=None, sleeper=None, attempts=3):
    """Wysyła jedną partię. Ponawia błędy sieciowe, 429 i odpowiedzi 5xx."""
    opener = opener or urllib.request.urlopen
    sleeper = sleeper or time.sleep
    body = json.dumps({"notifications": notifications}, ensure_ascii=False).encode("utf-8")
    last_error = None

    for attempt in range(attempts):
        request = urllib.request.Request(
            worker_url + "/dispatch",
            data=body,
            headers={
                "Authorization": "Bearer " + token,
                "Content-Type": "application/json",
                "User-Agent": USER_AGENT,
            },
            method="POST",
        )
        try:
            with opener(request, timeout=30) as response:
                response_body = response.read().decode("utf-8")
            result = json.loads(response_body)
            if not isinstance(result, dict) or not REQUIRED_RESPONSE_FIELDS.issubset(result):
                raise PushDispatchError("Cloudflare Push zwrócił odpowiedź w nieoczekiwanym formacie.")
            for field in REQUIRED_RESPONSE_FIELDS:
                if not isinstance(result[field], int) or result[field] < 0:
                    raise PushDispatchError(f"Nieprawidłowa wartość pola {field} w odpowiedzi Cloudflare.")
            return result
        except urllib.error.HTTPError as error:
            response_body = error.read().decode("utf-8", errors="replace")
            response_headers = {
                key: error.headers.get(key)
                for key in ("server", "cf-ray", "cf-cache-status", "content-type")
                if error.headers and error.headers.get(key)
            }
            print(json.dumps({
                "push_http_status": error.code,
                "push_response_headers": response_headers,
                "push_response_body": response_body[:2000],
            }, ensure_ascii=False))
            if 400 <= error.code < 500 and error.code != 429:
                raise PushDispatchError(
                    f"Push odrzucony przez serwer (HTTP {error.code}); kolejka pozostaje zapisana."
                ) from error
            last_error = error
        except (urllib.error.URLError, TimeoutError, OSError) as error:
            last_error = error

        if attempt < attempts - 1:
            sleeper(2 ** attempt)

    raise PushDispatchError(
        f"Nie udało się wysłać Push po {attempts} próbach: {last_error}. "
        "Kolejka pozostaje zapisana w repozytorium."
    )


def dispatch_notifications(worker_url, token, notifications, opener=None, sleeper=None):
    """Wysyła kolejkę partiami i wymaga potwierdzenia co najmniej jednego dostarczenia."""
    batches = [notifications[index:index + 50] for index in range(0, len(notifications), 50)] or [[]]
    dispatched_ids = []

    for batch_index, batch in enumerate(batches, start=1):
        result = post_dispatch(worker_url, token, batch, opener=opener, sleeper=sleeper)
        print(json.dumps({"push_batch": batch_index, "result": result}, ensure_ascii=False))

        if result["failed"]:
            raise PushDispatchError(
                f"Cloudflare zgłosił {result['failed']} błędów dostarczenia; kolejka pozostaje zapisana."
            )
        if batch and result["sent"] + result["skipped"] == 0:
            raise PushDispatchError(
                "Brak potwierdzonego dostarczenia. "
                f"devices={result['devices']}, removed={result['removed']}. "
                "Powiadomienia pozostają w kolejce do ponowienia."
            )

        dispatched_ids.extend(item["id"] for item in batch)

    return dispatched_ids


def acknowledge_pending(pending_path, delivered_ids):
    """Usuwa z trwałej kolejki wyłącznie komunikaty z potwierdzonym dostarczeniem."""
    pending_path = Path(pending_path)
    payload = json.loads(pending_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("notifications"), list):
        raise PushDispatchError("Plik pending_push.json ma nieprawidłowy format.")

    delivered = set(delivered_ids)
    pending = payload["notifications"]
    pending_ids = {item.get("id") for item in pending if isinstance(item, dict)}
    if not delivered.issubset(pending_ids):
        raise PushDispatchError("Nie można potwierdzić Push: ID nie znajdują się w trwałej kolejce.")

    payload["notifications"] = [
        item for item in pending
        if item.get("id") not in delivered
    ]
    temporary = pending_path.with_name(pending_path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(pending_path)


def main():
    worker = os.environ.get("PUSH_WORKER_URL", "").strip().rstrip("/")
    token = os.environ.get("PUSH_DISPATCH_TOKEN", "").strip()
    payload = json.loads(PUSH_PAYLOAD_FILE.read_text(encoding="utf-8"))
    notifications = payload.get("notifications", [])

    if not isinstance(notifications, list):
        raise PushDispatchError("push_payload.json ma nieprawidłowy format.")

    if not worker and not token:
        if notifications:
            raise PushDispatchError(
                "Push jest niekonfigurowany, ale kolejka zawiera oczekujące powiadomienia. Nie usuwam ich."
            )
        print("Cloudflare Push nie jest skonfigurowany; brak oczekujących powiadomień.")
        return
    if not worker or not token:
        raise PushDispatchError(
            "Niekompletna konfiguracja Push: wymagane są oba sekrety PUSH_WORKER_URL i PUSH_DISPATCH_TOKEN."
        )
    if not worker.startswith("https://"):
        raise PushDispatchError("PUSH_WORKER_URL musi używać HTTPS.")

    delivered_ids = dispatch_notifications(worker, token, notifications)
    if not notifications:
        print("Autoryzowany test Cloudflare Push zakończony poprawnie; nie było nowych zmian.")
        return

    acknowledge_pending(PENDING_PUSH_FILE, delivered_ids)
    print(f"Potwierdzono dostarczenie {len(delivered_ids)} powiadomień; kolejka została zaktualizowana.")


if __name__ == "__main__":
    try:
        main()
    except PushDispatchError as error:
        raise SystemExit(str(error))

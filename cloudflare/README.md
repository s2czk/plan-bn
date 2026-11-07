# Powiadomienia Push — plan BN

Prosty backend powiadomień dla `plan.mandaro.eu`. Wykorzystuje **jeden Cloudflare Worker + jedną przestrzeń KV**. Nie wymaga D1, Cloudflare Cron ani VPS.

## Jednorazowa konfiguracja

Wymagania: Node.js LTS, konto Cloudflare oraz dostęp do repozytorium GitHub.

1. W terminalu przejdź do katalogu i zaloguj Wrangler:

   ```bash
   cd cloudflare
   npm install
   npx wrangler login
   ```

2. Utwórz przestrzeń KV:

   ```bash
   npx wrangler kv namespace create PUSH_KV
   ```

   Skopiuj zwrócone ID do `cloudflare/wrangler.toml`, w pole `id` pod `[[kv_namespaces]]`. Nie pozostawiaj przykładowego zera.

3. Wygeneruj klucze VAPID:

   ```bash
   npx web-push generate-vapid-keys
   ```

   Publiczny klucz wpisz w `VAPID_PUBLIC_KEY` w `wrangler.toml`. Klucza prywatnego nie wpisuj do żadnego pliku repozytorium; ustaw go jako sekret:

   ```bash
   npx wrangler secret put VAPID_PRIVATE_KEY
   ```

4. Wygeneruj długi, losowy token wysyłki. Ustaw go jako sekret Workera:

   ```bash
   npx wrangler secret put DISPATCH_TOKEN
   ```

   Tę samą wartość dodaj w GitHub: **Settings → Secrets and variables → Actions → New repository secret**, pod nazwą `PUSH_DISPATCH_TOKEN`.

5. Wdróż Workera:

   ```bash
   npx wrangler deploy
   ```

   Zapisz adres otrzymany po wdrożeniu, np. `https://plan-bn-push.twoj-login.workers.dev`.

6. W GitHub dodaj drugi sekret Actions:
   - `PUSH_WORKER_URL` — adres Workera, bez końcowego `/dispatch`.

7. W pliku głównym repozytorium `push-config.js` ustaw adres Workera:

   ```js
   window.PUSH_API_URL = "https://plan-bn-push.twoj-login.workers.dev";
   ```

   Zapisz plik w gałęzi `main`. Adres ten jest publiczny; nie umieszczaj w nim żadnych sekretów.

## Test wdrożenia

1. Otwórz `https://<adres-workera>/health`. Oczekiwany wynik: `{"ok":true,"service":"plan-bn-push"}`.
2. Otwórz stronę planu na urządzeniu i wybierz **Włącz powiadomienia**. Powtórz na kolejnych urządzeniach.
3. Sprawdź dostarczenie testowej zmiany, gdy przeglądarka nie ma otwartej karty strony.
4. Wyłącz powiadomienia na jednym urządzeniu i sprawdź, czy pozostałe nadal działają.

## Jak działa

- GitHub Actions sprawdza PDF co godzinę między 6:00 a 23:00 czasu `Europe/Warsaw`.
- Parser porównuje nowy plan z poprzednim i zapisuje zmiany.
- Gdy pojawią się zmiany, Actions wywołuje zabezpieczony tokenem endpoint Workera `POST /dispatch`.
- Worker wysyła Web Push do wszystkich zarejestrowanych urządzeń i zapisuje identyfikatory wysłanych powiadomień na 7 dni, aby uniknąć duplikatów.
- KV przechowuje subskrypcje urządzeń i znaczniki wysyłek. Worker nie przechowuje całego planu ani danych osobowych użytkownika.

## Endpointy

- `GET /health` — stan Workera.
- `GET /config` — publiczny klucz VAPID.
- `POST /subscribe` — zapis subskrypcji urządzenia.
- `POST /unsubscribe` — usunięcie subskrypcji urządzenia.
- `POST /dispatch` — wysyłka z GitHub Actions; wymaga nagłówka `Authorization: Bearer ...`.

## Bezpieczeństwo i koszty

Worker przyjmuje żądania przeglądarkowe tylko z `ALLOWED_ORIGIN` ustawionego w `wrangler.toml`. Sekret prywatny VAPID i token wysyłki przechowuj wyłącznie w Cloudflare/GitHub Secrets — nigdy w repozytorium.

Przy kilku urządzeniach zużycie KV i żądań powinno być niewielkie. Cloudflare Workers Free ma jednak niski limit CPU na pojedyncze wywołanie, dlatego wysyłkę trzeba sprawdzić na docelowym koncie. Jeśli szyfrowanie wiadomości Push przekroczy limit CPU, konieczna może być zmiana planu Workers. Nie da się uczciwie potwierdzić działania rzeczywistych powiadomień przed wdrożeniem i testem na koncie Cloudflare.


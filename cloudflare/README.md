# Powiadomienia Push — plan BN

Backend korzysta z jednego Cloudflare Workera i KV. Nie wymaga D1, Cloudflare Cron ani VPS.

## Jednorazowa konfiguracja

Wymagania: Node.js LTS, konto Cloudflare i dostęp do DNS/Workers (domena strony nie musi być przenoszona do Cloudflare).

1. Otwórz katalog \`cloudflare\`:
   \`\`\`bash
   cd cloudflare
   npm install
   npx wrangler login
   \`\`\`

2. Utwórz przestrzeń KV:
   \`\`\`bash
   npx wrangler kv namespace create PUSH_KV
   \`\`\`
   Skopiuj zwrócone \`id\` do \`cloudflare/wrangler.toml\` w polu \`[[kv_namespaces]] id\`.

3. Wygeneruj klucze VAPID:
   \`\`\`bash
   npx web-push generate-vapid-keys
   \`\`\`
   - publiczny klucz wpisz w \`VAPID_PUBLIC_KEY\` w \`wrangler.toml\`;
   - prywatnego klucza **nie wpisuj do pliku**. Ustaw go poleceniem:
   \`\`\`bash
   npx wrangler secret put VAPID_PRIVATE_KEY
   \`\`\`

4. Wygeneruj długi, losowy token wysyłki i ustaw go jako sekret Workera:
   \`\`\`bash
   npx wrangler secret put DISPATCH_TOKEN
   \`\`\`
   Ten sam token dodaj w repozytorium GitHub: **Settings → Secrets and variables → Actions → New repository secret**, nazwa \`PUSH_DISPATCH_TOKEN\`.

5. Wdróż Workera:
   \`\`\`bash
   npx wrangler deploy
   \`\`\`
   Otrzymasz adres podobny do \`https://plan-bn-push.twoj-login.workers.dev\`.

6. W GitHub dodaj drugi sekret Actions:
   - \`PUSH_WORKER_URL\` — sam adres Workera, bez \`/dispatch\`.

7. W głównym katalogu repozytorium otwórz \`push-config.js\` i wpisz adres Workera:
   \`\`\`js
   window.PUSH_API_URL = "https://plan-bn-push.twoj-login.workers.dev";
   \`\`\`
   Zapisz plik w gałęzi \`main\).

## Test po wdrożeniu

- Otwórz \`https://plan.mandaro.eu/health\` w adresie Workera — powinno zwrócić \`{"ok":true,"service":"plan-bn-push"}\`.
- Otwórz stronę planu na każdym urządzeniu i wybierz **Włącz powiadomienia**.
- Przetestuj dostarczenie Push, gdy przeglądarka jest zamknięta.
- Sprawdź również wyłączenie powiadomień na jednym urządzeniu.

## Endpointy

- \`GET /health\` — stan Workera.
- \`GET /config\` — publiczny klucz VAPID.
- \`POST /subscribe\` — zapis subskrypcji urządzenia.
- \`POST /unsubscribe\` — usunięcie subskrypcji urządzenia.
- \`POST /dispatch\` — wysyłka z GitHub Actions, wymaga nagłówka \`Authorization: Bearer ...\`.

Worker akceptuje żądania przeglądarkowe wyłącznie z \`ALLOWED_ORIGIN\`. Sekret prywatny VAPID i token wysyłki są przechowywane jako sekrety Cloudflare/GitHub, nie w repozytorium.

## Limity i koszty

Przy kilku urządzeniach i małej liczbie zmian zużycie jest niewielkie. Cloudflare Free ma limit 100 000 żądań Workera dziennie oraz limit CPU 10 ms na żądanie; KV Free ma 100 000 odczytów i 1000 zapisów dziennie. Wysyłka rzeczywistych wiadomości Push wymaga testu na docelowym koncie Cloudflare — w szczególności czasu CPU szyfrowania. Gdy limit CPU zostanie przekroczony, konieczne może być przejście na Workers Paid.

## Prywatność

Worker zapisuje adres endpointu Push i klucze subskrypcji wymagane przez standard Web Push oraz identyfikatory wysyłek przez 7 dni. Nie przechowuje nazw użytkowników ani treści planu.

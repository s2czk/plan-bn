# Cloudflare Worker — powiadomienia Push planu BN

Worker `plan-bn-push` jest częścią repozytorium `s2czk/plan-bn` i obsługuje subskrypcje Web Push, rejestr urządzeń i wysyłanie powiadomień. Parser PDF pozostaje w GitHub Actions; Worker nie instaluje ani nie uruchamia zależności Pythona.

## 1. Jednorazowe ustawienie Workers Builds

Log z 8 listopada 2026 r. wykazał, że Cloudflare wykonywał `pip install -r requirements.txt` z katalogu głównego repozytorium, a następnie używał `npx wrangler preview` jako **komendy produkcyjnego wdrożenia**. Obie rzeczy są nieprawidłowe dla tego projektu.

W Cloudflare Dashboard otwórz **Workers & Pages → plan-bn-push → Settings → Build**. Ustaw:

| Pole | Wartość |
|---|---|
| Git repository | `s2czk/plan-bn` |
| Production branch | `main` |
| Root directory | `cloudflare` |
| Build command | `npm install --no-audit --no-fund` |
| Deploy command | `npm run deploy` |
| Preview command | `npm run preview` |

Zapisz ustawienia.

Następnie w **Settings → Build → Branch control**:
- Production branch: `main`.
- **Enable Preview Builds: wyłączone** na potrzeby tej prostej konfiguracji produkcyjnej. Nie tworzymy obecnie osobnej bazy KV ani sekretów dla gałęzi testowych.

Dlaczego te wartości:
- `cloudflare` jako Root directory izoluje Worker od głównego projektu, w którym znajduje się `requirements.txt` dla parsera PDF.
- Build command instaluje zależności Node z `cloudflare/package.json`.
- Deploy command uruchamia prawdziwe wdrożenie produkcyjne (`wrangler deploy`), a nie podgląd (`wrangler preview`).
- Preview Builds są wyłączone, aby gałęzie testowe nie tworzyły wdrożeń z niekompletnymi, produkcyjnymi zależnościami.

Po zapisaniu ustawień scalony commit na `main` wywoła automatyczny build. Jeśli build nie uruchomi się sam, użyj **Retry build** dla ostatniego nieudanego wdrożenia — ponowienie użyje nowych ustawień.

## 2. Zasoby i zmienne produkcyjne

`cloudflare/wrangler.toml` zawiera:
- Worker name: `plan-bn-push`;
- binding `PUSH_KV` i istniejące ID przestrzeni KV;
- publiczne `VAPID_PUBLIC_KEY`;
- `VAPID_SUBJECT`;
- dozwolony origin `https://plan.mandaro.eu`.

Nie twórz kolejnej przestrzeni KV i nie podmieniaj istniejącego ID — obecna przestrzeń jest już wskazana w konfiguracji.

W **Worker → Settings → Variables and Secrets** sprawdź, czy istnieją dwa sekrety produkcyjne:
- `VAPID_PRIVATE_KEY` — prywatny klucz odpowiadający publicznemu `VAPID_PUBLIC_KEY`;
- `DISPATCH_TOKEN` — losowy, długi token wymagany przez endpoint `POST /dispatch`.

Jeśli któregoś brakuje, dodaj go jako **Secret**, nie jako zwykłą zmienną i nigdy nie commituj go do GitHub. Nie zmieniaj istniejących wartości, jeśli już działają.

W repozytorium GitHub sprawdź **Settings → Secrets and variables → Actions**. Workflow aktualizacji planu wymaga dwóch sekretów:
- `PUSH_WORKER_URL` — `https://plan-bn-push.szk-c00.workers.dev` (bez `/dispatch`);
- `PUSH_DISPATCH_TOKEN` — dokładnie ta sama wartość co Cloudflare `DISPATCH_TOKEN`.

GitHub Secrets nie ujawniają wartości po zapisaniu, więc trzeba sprawdzić jedynie, czy oba wpisy istnieją i czy token został skopiowany do obu miejsc bez spacji.

## 3. Test po automatycznym wdrożeniu

1. Otwórz `https://plan-bn-push.szk-c00.workers.dev/health`. Oczekiwany JSON: `{"ok":true,"service":"plan-bn-push"}`.
2. Otwórz `https://plan-bn-push.szk-c00.workers.dev/config`. Odpowiedź powinna zawierać niepusty `publicVapidKey`.
3. Na `https://plan.mandaro.eu` otwórz panel powiadomień. Powinien pojawić się status, że usługa Push odpowiada.
4. Włącz powiadomienia na telefonie. Sprawdź, czy urządzenie zostało zarejestrowane.
5. Wykonaj kontrolowaną próbę wysyłki na własne urządzenie; nie wysyłaj testowych komunikatów do innych użytkowników.

Sama odpowiedź `/health` potwierdza tylko działanie procesu Workera. Rzeczywista wysyłka wymaga poprawnego prywatnego klucza VAPID, tokenu, KV oraz subskrypcji konkretnego urządzenia.

## 4. Automatyzacja po konfiguracji

Po jednorazowym zapisaniu ustawień:
- push do `main` automatycznie wdraża Worker przez Cloudflare Workers Builds;
- GitHub Actions niezależnie sprawdza PDF i wysyła wykryte zmiany do `POST /dispatch`;
- nie jest potrzebny VPS, D1 ani osobny serwer;
- katalog główny repozytorium zachowuje `requirements.txt` dla parsera Pythona.

W razie problemu sprawdź log Cloudflare. Prawidłowa produkcyjna komenda powinna być widoczna jako `npm run deploy` / `wrangler deploy`, a nie `wrangler preview` ani `pip install -r requirements.txt`.

## 5. Pliki i komendy lokalne

W katalogu `cloudflare`:
- `npm install --no-audit --no-fund` — instaluje zależności;
- `npm test` — testuje API Workera;
- `npm run deploy` — wdraża produkcyjnego Workera;
- `npm run preview` — uruchamia Preview (wymaga oddzielnej konfiguracji zasobów, dlatego Preview Builds są obecnie wyłączone).

Sekretów `VAPID_PRIVATE_KEY` i `DISPATCH_TOKEN` nie umieszczaj w repozytorium.

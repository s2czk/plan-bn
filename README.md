# Plan BN — PANS Koszalin

Aplikacja PWA z planem zajęć kierunku Bezpieczeństwo Narodowe (I rok).

## Architektura

- `updater.py` — pobiera aktualny PDF z kursu PANS, rozdziela strony tygodniowe na siedem kolumn, odczytuje przedmioty, godziny, sale, prowadzących, tryby oraz oznaczenia odwołań.
- `schedule.json` — opublikowany plan wykorzystywany przez interfejs.
- `audit_plan.py` — niezależnie pobiera i parsuje źródłowy PDF, porównuje wynik z `schedule.json`, sprawdza nakładanie godzin i statusy odwołań.
- `push_dispatch.py` — wysyła trwałą kolejkę powiadomień do Cloudflare Worker i usuwa wyłącznie komunikaty potwierdzone przez usługę.
- `index.html` — interfejs aplikacji.
- `sw.js` — cache aplikacji, tryb offline i Web Push.
- `cloudflare/src/index.js` — Worker obsługujący subskrypcje i dystrybucję Web Push.

## Zasada publikacji

Plan nie może zostać zapisany, dopóki:
1. każda strona PDF nie zostanie rozpoznana;
2. każda karta zajęć nie przejdzie walidacji pól źródłowych;
3. czerwone oznaczenia i tekst odwołania nie zostaną zachowane jako status;
4. nie przejdzie `validate_schedule()`;
5. niezależny `audit_plan.py` nie potwierdzi zgodności świeżego parsowania z opublikowanym JSON-em.

W przypadku błędu poprzedni `schedule.json` pozostaje bez zmian. Push jest wysyłany dopiero po zapisaniu planu i trwałej kolejki.

## Środowisko CI

- Python 3.14.10
- Node.js 26.13.1 LTS
- npm 12.2.3
- requests 2.34.2
- beautifulsoup4 4.15.0
- pdfplumber 0.11.11
- Wrangler 4.168.0
- @block65/webcrypto-web-push 2.0.0

Wersje bezpośrednich zależności są przypięte. Zależności Node są instalowane z `cloudflare/package-lock.json` przez `npm ci`.

## Uruchomienie testów

Z katalogu głównego:

```bash
python -m pip install -r requirements.txt
python -m pip check
python -m compileall -q updater.py audit_plan.py push_dispatch.py tests
python -m unittest discover -s tests -v
python audit_plan.py
```

Testy Workera:

```bash
cd cloudflare
npm ci
npm test
npx wrangler deploy --dry-run --outdir ./.test-build
```

## Bezpieczna praca z sekretami

Nie zapisuj do repozytorium klucza prywatnego VAPID ani tokenów dispatch. Wymagane wartości muszą pozostać w GitHub Actions Secrets i Cloudflare Worker Secrets.

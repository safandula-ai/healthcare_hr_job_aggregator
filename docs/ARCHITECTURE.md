# Architektura projektu

Ten dokument opisuje aktualny przepływ działania aplikacji i wskazuje moduły, w których wprowadza się zmiany.

## Uruchomienie

1. `run_app.py` ustawia katalog projektu jako bieżący, konfiguruje logowanie i uruchamia serwer Uvicorn.
2. Serwer nasłuchuje wyłącznie na `127.0.0.1:8000`. Osobny wątek otwiera przeglądarkę, gdy endpoint kontrolny zaczyna odpowiadać.
3. Podczas startu `app.main` wywołuje `models.database.init_db()`. Funkcja tworzy brakujące tabele, wykonuje lekką migrację SQLite i uzupełnia początkową listę miast oraz źródeł.
4. FastAPI udostępnia strony HTML, API JSON oraz pliki statyczne.

Aplikacja jest przeznaczona do użytku lokalnego. Panel administratora nie wymaga logowania, dlatego nie należy wystawiać serwera w sieci ani w internecie bez dodania kontroli dostępu.

## Główne moduły

| Ścieżka | Odpowiedzialność |
| --- | --- |
| `run_app.py` | Lokalny punkt startowy, uruchomienie Uvicorn i otwarcie przeglądarki. |
| `app/main.py` | Konfiguracja FastAPI, inicjalizacja bazy, strony i montowanie statycznych plików. |
| `app/public.py` | Aktywne endpointy ofert i aktualizacji statusu. |
| `app/admin.py` | Aktywne endpointy panelu administracyjnego. |
| `app/*.html` | Aktywne szablony stron. Są ładowane bezpośrednio z katalogu `app`. |
| `app/static/` | Style, ikony oraz aktywne skrypty frontendowe `js/app.js` i `js/admin.js`. |
| `models/database.py` | Modele SQLAlchemy, połączenie SQLite, migracja i dane początkowe. |
| `config/settings.py` | Ustawienia aplikacji i wartości pobierane z `.env`. |
| `scrapers/base_scraper.py` | Rejestr scraperów, wspólna konfiguracja Selenium i funkcje bazowe. |
| `scrapers/run_scrapers.py` | Orkiestracja pobierania ofert i stan bieżącego przebiegu. |
| `scrapers/scraper_*.py` | Integracje z poszczególnymi serwisami lub typami stron. |
| `utils/profile_matcher.py` | Ocena dopasowania treści oferty do profilu stanowisk. |
| `utils/location_matcher.py` | Odległości, filtrowanie lokalizacji i korekta punktacji za lokalizację. |
| `utils/deduplication.py` | Wykrywanie wcześniej zapisanych adresów ofert. |
| `utils/logging_config.py` | Rotujące logi aplikacji i scraperów w katalogu `logs/`. |

`app/routes/`, `app/templates/` oraz część plików bezpośrednio w `app/` (np. `app/app.js`) zawierają starsze kopie. Nie są używane przez konfigurację w `app/main.py`, która podłącza `app/public.py`, `app/admin.py`, szablony z katalogu `app` i skrypty z `app/static/`. Przy zmianach aktualizuj aktywne pliki.

## Model danych

- `Website` opisuje źródło: URL, nazwę, kategorię, lokalizację, aktywność oraz opcjonalny `custom_config`.
- `City` przechowuje nazwę, współrzędne i flagę aktywności. Aktywne miasta są używane przy dopasowywaniu lokalizacji.
- `JobOffer` przechowuje tytuł, firmę, lokalizację, oryginalny URL, opis, czasy pobrania i źródło.
- `OfferStatus` przechowuje status aplikacji i notatki użytkownika. Oferta ma jeden powiązany rekord statusu.

Baza domyślnie znajduje się w `data/apjobs.db`; ścieżkę można zmienić przez `DB_PATH`. Początkowe miasta i źródła są dodawane tylko wtedy, gdy odpowiednia tabela jest pusta. Zmiana danych początkowych w kodzie nie aktualizuje automatycznie istniejącej bazy.

## Przepływ scrapowania

1. Użytkownik uruchamia wyszukiwanie z panelu admina albo startuje moduł `scrapers.run_scrapers` z linii poleceń.
2. Orkiestrator wybiera aktywne rekordy `Website` i dla każdego znajduje klasę po nazwie firmy, a następnie po kategorii.
3. Klasa scrapera pobiera stronę przez Requests/BeautifulSoup albo Selenium, parsuje kandydatów i stosuje filtr dopasowania oraz lokalizacji.
4. `Deduplicator` tworzy SHA-1 z URL-a. Modele mają też unikalne ograniczenia na URL i hash.
5. Nowa oferta oraz początkowy status `new` trafiają do SQLite.

Scrapery są rejestrowane dekoratorem `@ScraperRegistry.register("nazwa")`. Nowa klasa powinna dziedziczyć po `BaseScraper`, udostępniać `run(website_record)` i zamykać zasoby przeglądarki w metodzie `close()`.

| Plik | Integracja |
| --- | --- |
| `scraper_olx.py` | OLX. |
| `scraper_pracuj.py` | Pracuj.pl. |
| `scraper_local.py` | Lokalne strony kariery konfigurowane selektorami CSS. |
| `scraper_nationwide.py` | Wspólne parsowanie stron ogólnopolskich oraz wybrane warianty specyficzne dla pracodawcy. |
| `scraper_enelmed.py` | Enel-Med. |
| `scraper_luxmed.py` | LUX MED. |
| `scraper_medicover.py` | Medicover. |
| `scraper_erecruiter.py` | Widżety eRecruiter, m.in. Synevo, ALAB, Affidea i Scanmed. |
| `scraper_su.py` | Szpital Uniwersytecki. |

Aktualna konfiguracja orkiestratora przetwarza źródła sekwencyjnie (`MAX_WORKERS = 1`). Postęp i ostatni błąd są przechowywane w pamięci procesu, a nie w bazie.

## Konfiguracja strony źródłowej

Pola `Website.custom_config` oczekują JSON-a. Ogólny parser obsługuje selektory CSS:

```json
{
  "strategy": "requests",
  "card_selector": ".job-card",
  "title_selector": ".job-title",
  "url_selector": "a.job-link",
  "location_selector": ".job-location"
}
```

`url_selector` i `location_selector` są opcjonalne; bez nich parser szuka linku w karcie i używa domyślnej lokalizacji źródła. Dla scrapera lokalnego `strategy` może mieć wartość `selenium`; wtedy `expand_selector` wskazuje elementy rozwijające treść. Integracja eRecruiter może dodatkowo przyjmować `erecruiter_cfg`. Selektory zależą od konkretnej strony i mogą przestać działać po jej zmianie.

## Dopasowanie i punktacja

`ProfileMatcher` normalizuje treść oferty i sumuje sygnały dotyczące stanowiska, kontekstu medycznego i administracji. Stosuje również premie za wybrane kombinacje, kary za negatywne słowa i twarde wykluczenia. Wynik jest ograniczany do zakresu 0–100. Lokalizacja może zmienić wynik końcowy.

`LocationMatcher` porównuje współrzędne skonfigurowanego centrum z miastami zapisanymi w bazie. Dla wybranych lokalizacji ma ręczne przybliżenia dojazdu. Wyszukiwanie tekstu lokalizacji opiera się na nazwach miast oraz ich aktywności.

Ważne: API przelicza punktację na podstawie bieżących reguł; pole `JobOffer.score` jest zapisywane przez część scraperów, ale nie jest źródłem wyniku zwracanego przez listę ofert.

## Konfiguracja i pliki lokalne

Ustawienia opisuje `.env.example`; lokalny `.env`, baza, logi i środowisko Python są wykluczone przez `.gitignore`. Najważniejsze zmienne:

- `BASE_LOCATION_LAT`, `BASE_LOCATION_LON`, `SEARCH_RADIUS_KM` — centrum i zasięg filtrowania.
- `MIN_MATCH_SCORE` — minimalny próg przy zapisywaniu kandydatów przez scrapery.
- `SELENIUM_HEADLESS`, `CHROME_BINARY_PATH` — tryb przeglądarki i opcjonalna ścieżka do Chrome.
- `DB_PATH`, `LOG_LEVEL` — lokalizacja bazy i poziom logowania.

Logi trafiają do `logs/app.log` i `logs/scrapers.log`; oba pliki są rotowane. Scraperzy Selenium mogą też zapisywać zrzuty diagnostyczne w `logs/screenshots/`.

## Wskazówki dla osób rozwijających

- Po zmianie API sprawdź, czy frontend używa tego samego URL-a, parametrów i kształtu JSON.
- Zmiana danych początkowych wpływa tylko na pustą tabelę; istniejące wpisy trzeba edytować w panelu lub bazie.
- Zmiany schematu SQLite wymagają migracji w `migrate_db()` albo kontrolowanego odtworzenia lokalnej bazy.
- W projekcie nie ma obecnie zautomatyzowanego zestawu testów.

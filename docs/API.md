# API aplikacji

API jest częścią lokalnego serwera FastAPI. Domyślny adres bazowy to `http://127.0.0.1:8000`. Interaktywna dokumentacja FastAPI jest dostępna pod `/docs`, gdy aplikacja działa.

## Strony

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| GET | `/` | Dashboard ofert. |
| GET | `/offers/{offer_id}` | Szczegóły oferty. |
| GET | `/matching` | Wyjaśnienie punktacji. |
| GET | `/admin` | Panel administracyjny. |

## Oferty i statusy

Wszystkie poniższe endpointy mają prefiks `/api`.

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| GET | `/offer-filter-options` | Zwraca listę źródeł i firm używaną w filtrach. |
| GET | `/offers` | Lista stronicowanych ofert z filtrami, sortowaniem i licznikami statusów. |
| GET | `/offers/{offer_id}` | Szczegóły oferty, jej status i wyjaśnienie dopasowania. |
| PUT | `/offers/{offer_id}` | Aktualizuje status oraz opcjonalne notatki dla jednej oferty. |
| PUT | `/offers/bulk/status` | Ustawia status dla wielu ofert. |

Parametry `GET /api/offers`:

| Parametr | Domyślnie | Znaczenie |
| --- | --- | --- |
| `status` | `new` | Status do wyświetlenia. `zero` wybiera nowe oferty z wynikiem poniżej 1. |
| `page` | `1` | Numer strony, od 1. |
| `size` | `20` | Liczba wyników na stronę, co najmniej 1. |
| `sort` | `date_desc` | `date_desc`, `date_asc`, `score_desc` lub `score_asc`. Nieznana wartość używa domyślnego sortowania malejąco po dacie. |
| `min_score` | — | Dolna granica punktacji 0–100. |
| `max_score` | — | Górna granica punktacji 0–100. |
| `source` | — | Fragment nazwy źródła. |
| `company` | — | Fragment nazwy firmy podanej przy ofercie. |
| `zero_score` | `false` | Gdy `true`, zwraca wyłącznie wyniki poniżej 1. |

Statusy używane w aplikacji to `new`, `cv_sent`, `replied`, `interview` i `archived`. Endpointy statusu przyjmują JSON:

```json
{
  "status": "cv_sent",
  "notes": "Wysłano CV przez formularz pracodawcy"
}
```

Aktualizacja zbiorcza przyjmuje `offer_ids` zamiast pojedynczego ID:

```json
{
  "offer_ids": [12, 15],
  "status": "archived"
}
```

Backend przyjmuje pola `status` jako tekst i nie ogranicza ich do powyższej listy. Klient powinien przesyłać wyłącznie obsługiwane statusy.

## Panel administratora

Wszystkie endpointy administracyjne mają prefiks `/api/admin`.

| Metoda | Ścieżka | Opis |
| --- | --- | --- |
| GET | `/stats` | Liczba ofert oraz aktywnych źródeł i miast. |
| GET | `/websites` | Lista źródeł. |
| GET | `/websites/{website_id}` | Szczegóły źródła. |
| POST | `/websites` | Dodaje źródło. |
| PUT | `/websites/{website_id}` | Zastępuje pola źródła przekazanymi wartościami. |
| DELETE | `/websites/{website_id}` | Usuwa źródło. |
| PUT | `/websites/bulk/active` | Zbiorczo zmienia aktywność źródeł. |
| GET | `/cities` | Lista miast. |
| GET | `/cities/{city_id}` | Szczegóły miasta. |
| POST | `/cities` | Dodaje miasto. |
| PUT | `/cities/{city_id}` | Zastępuje pola miasta przekazanymi wartościami. |
| DELETE | `/cities/{city_id}` | Usuwa miasto. |
| PUT | `/cities/bulk/active` | Zbiorczo zmienia aktywność miast. |
| POST | `/scrape-now` | Kolejkuje scrapowanie, jeśli inne nie trwa. |
| GET | `/scrape-status` | Zwraca bieżący postęp scrapowania. |
| POST | `/shutdown` | Kończy lokalny proces aplikacji. |

Źródło przyjmuje pola `url`, `company_name`, `category`, `active`, `keywords`, `location` i `custom_config`. Miasto przyjmuje `city_name`, `latitude`, `longitude` i `active`. Endpointy zbiorcze przyjmują `ids` oraz `active`, na przykład:

```json
{
  "ids": [1, 2],
  "active": false
}
```

Endpointy administratora nie są chronione logowaniem. Serwer wiąże się z `127.0.0.1`; nie wystawiaj tych endpointów do niezaufanej sieci.

## Odpowiedź scrapowania

`GET /api/admin/scrape-status` zwraca między innymi pola:

```json
{
  "running": true,
  "current_website": "LUX MED",
  "completed": 2,
  "total": 10,
  "started_at": "2026-09-25T10:00:00",
  "finished_at": null,
  "last_error": null
}
```

Wartości są stanem w pamięci procesu, więc po restarcie serwera historia przebiegów nie jest zachowana.

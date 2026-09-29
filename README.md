# AP Job Aggregator

A Windows desktop application that collects healthcare job listings from selected job boards and employer career pages. It provides a local dashboard for reviewing offers, matching them against a configurable location and a healthcare administration profile, and tracking application status.

> This project is currently tailored to a Polish healthcare administration job search around Kraków. The matching rules and location scoring contain project-specific defaults.

## Features

- Collects listings from OLX, Pracuj.pl and selected healthcare employers.
- Scores listings using role, healthcare and administration keywords.
- Filters listings by location and removes duplicate URLs.
- Provides a local web dashboard to review offers and track application status.
- Includes an admin page for managing source websites and cities and starting a scrape.
- Stores application data in a local SQLite database.

## Requirements

- Windows 10 or 11
- Python 3.10 or newer
- Google Chrome for Selenium-based sources
- Internet access for installing Python dependencies and collecting listings

## Install and run

1. Install Python from [python.org](https://www.python.org/downloads/) and enable **Add Python to PATH**.
2. Download or clone this repository.
3. Double-click `Install AP Job Aggregator.bat`. The installer creates `.venv`, installs requirements, copies `.env.example` to `.env` if needed, and creates a desktop shortcut.
4. Open the dashboard at <http://127.0.0.1:8000>.

To start it manually after installation:

```powershell
cd path\to\healthcare_hr_job_search
.\.venv\Scripts\python.exe run_app.py
```

The application binds to `127.0.0.1` and is intended for local use. The admin page has no authentication. Do not expose this server to a network or the public internet without adding access controls and reviewing the security configuration.

## Configuration

The installer creates `.env` from `.env.example`. Available settings:

| Setting | Default | Description |
| --- | --- | --- |
| `BASE_LOCATION_LAT` | `50.0647` | Latitude used as the search center (Kraków city center). |
| `BASE_LOCATION_LON` | `19.9450` | Longitude used as the search center (Kraków city center). |
| `SEARCH_RADIUS_KM` | `50` | Search radius in kilometers. |
| `MIN_MATCH_SCORE` | `5` | Minimum match score used by scrapers. |
| `DB_PATH` | `./data/apjobs.db` | SQLite database path. |
| `LOG_LEVEL` | `INFO` | Logging verbosity. |
| `SELENIUM_HEADLESS` | `True` | Run Chrome without a visible browser window. |
| `CHROME_BINARY_PATH` | *(empty)* | Optional path to the Chrome executable; leave empty for automatic detection. |

The location matcher and keyword profile also contain project-specific defaults; changing the coordinates alone does not make every matching rule generic.

## Data and privacy

The database stores collected job offers and locally entered application statuses and notes. Logs may include scraper errors and captured page content. These files stay on the machine unless the user shares them. Do not commit `.env`, the database, logs, browser profiles or other runtime data to a public repository.

## Scraping

Scrapers depend on third-party websites and may stop working when those sites change. Before using or redistributing this software, review the terms and access rules of each source website and use reasonable request rates. The project is not affiliated with the listed job boards or employers.

## Development

Install dependencies in a virtual environment with `python -m pip install -r requirements.txt`. Run the app with `python run_app.py` from the project directory. No automated test suite is currently included.

## Documentation

- [Architecture and development guide (Polish)](docs/ARCHITECTURE.md)
- [HTTP API reference (Polish)](docs/API.md)
- [Scheduled scraping on Windows](DEPLOYMENT.md)

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE).

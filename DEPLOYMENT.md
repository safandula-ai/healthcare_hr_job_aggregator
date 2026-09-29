# Scheduled scraping on Windows

The scraper suite can run without starting the web dashboard. Create a Windows Task Scheduler task that launches the Python module from the project directory.

## Prerequisites

- Install the application and dependencies using `Install Healthcare HR Job Aggregator.bat`.
- Run a manual scrape from the admin panel once and confirm that Chrome and the source websites work.
- Set `SELENIUM_HEADLESS=True` in `.env` for scheduled runs.

## Create the task

In Task Scheduler, create a task with a daily trigger and these action values:

| Field | Value |
| --- | --- |
| Program/script | Full path to `.venv\Scripts\python.exe` |
| Add arguments | `-m scrapers.run_scrapers` |
| Start in | Full path to the project root containing `run_app.py` |

For example, if the project is in `D:\Apps\healthcare_hr_job_search`, use:

```text
Program:   D:\Apps\healthcare_hr_job_search\.venv\Scripts\python.exe
Arguments: -m scrapers.run_scrapers
Start in:  D:\Apps\healthcare_hr_job_search
```

The **Start in** directory matters: it lets Python import the project modules and lets the application load the root `.env` file and write logs to the project `logs` folder.

Use the same Windows account that installed the application and has access to its files. Enable **Run task as soon as possible after a scheduled start is missed** if the computer may be off at the scheduled time. In the task's **Settings** tab, set **If the task is already running** to **Do not start a new instance**.

## Logs and troubleshooting

The application writes scraper activity to `logs/scrapers.log` and general application messages to `logs/app.log`. The log files rotate automatically. Task Scheduler's **Last Run Result** reports whether Python exited successfully; check the logs for details about individual sources.

If the task cannot find Python modules or `.env` settings, verify the **Start in** path. If Selenium cannot start Chrome, confirm Chrome is installed, check `CHROME_BINARY_PATH` in `.env` when automatic detection does not work, and keep `SELENIUM_HEADLESS=True` for non-interactive runs.

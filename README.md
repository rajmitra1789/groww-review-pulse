# Groww Review Pulse

Groww Review Pulse turns a committed snapshot of public Google Play reviews into
a checked weekly brief. It filters and clusters reviews, uses Groq to name
themes and draft actions, preserves quotes verbatim, and can append an approved
brief to Google Docs and create a Gmail draft through a separate MCP server.

The Streamlit deployment does not fetch Play Store data. It reads a committed,
identity-stripped snapshot from `data/snapshots/` or a snapshot uploaded in the
UI.

## Local setup

Python 3.12 is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-dev.txt
cp .env.example .env
```

Set the five local values in `.env`:

- `GROQ_API_KEY`
- `MCP_SERVER_URL`
- `MCP_AUTH_TOKEN`
- `PULSE_DOC_ID`
- `PULSE_RECIPIENT`

Run the tests and app:

```bash
pytest -q
streamlit run app.py
```

The app reads each setting from the environment first and then from Streamlit
secrets.

## Refresh the snapshot

Fetching is a local-only task because `google-play-scraper` is intentionally a
development dependency:

```bash
python scripts/fetch_reviews.py
```

The script writes `data/snapshots/reviews_YYYY-MM-DD.jsonl` after removing
reviewer identity fields. Review that file, then add it to git so Community
Cloud can read it. Generated run artifacts under `data/runs/` are temporary and
are intentionally ignored.

## Streamlit Community Cloud

Deploy `app.py` from the repository with Python 3.12 and copy the five settings
above into the app's Secrets editor. Do not upload `.env` or
`.streamlit/secrets.toml`.

The app is intended to be public and has no password gate. Consequently, every
visitor can generate previews and can use the Publish button after validation;
Publish writes to the configured Google Doc and creates a draft for the
configured recipient. Use a dedicated document and recipient, monitor the MCP
service, and remove or rotate its bearer token before taking the app offline.

The complete deployment, verification, and rollback procedure is in
[`docs/deployment-plan.md`](docs/deployment-plan.md).

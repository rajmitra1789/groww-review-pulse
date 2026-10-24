# Groww Review Pulse

Groww Review Pulse reads Groww Play Store reviews and writes a one-page weekly note with the top 3 themes, 3 verbatim user quotes, and 3 action ideas. It then sends the note to a Google Doc and a Gmail draft through an MCP server.

## Live links

- [Live app](https://groww-review-puls-mny9sziydzh2kndreerqfh.streamlit.app/)
- [MCP server](https://mcp-server-pulse-production.up.railway.app), with a health check at [`/health`](https://mcp-server-pulse-production.up.railway.app/health)
- [MCP server code](https://github.com/rajmitra1789/mcp-server-pulse)

## Features

- Reads a saved snapshot of public Groww Play Store reviews.
- Normalizes review text and removes reviewer identity fields.
- Groups similar reviews into themes using embeddings and clustering.
- Uses Groq to name themes and suggest practical actions.
- Preserves selected user quotes verbatim.
- Validates the note before it can be published.
- Appends the weekly note to a Google Doc and creates a Gmail draft through an authenticated MCP server.
- Provides a Streamlit interface for previewing and publishing the pulse.

## How it works

1. **Ingest:** Load a committed review snapshot or an uploaded snapshot.
2. **Normalize:** Clean and standardize review text while excluding reviewer identity data.
3. **Cluster:** Embed reviews and group similar feedback with KMeans.
4. **Name themes and pick quotes:** Name the strongest themes, select verbatim quotes, and draft action ideas.
5. **Validate:** Check the generated note, its structure, and its quotes before publishing.
6. **Publish through MCP:** Send the approved note to the MCP server, which appends it to Google Docs and creates a Gmail draft.

## Usage

### Run locally

Python 3.12 is required.

```bash
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
streamlit run app.py
```

Configure these five secrets in your environment, local `.env` file, or Streamlit secrets:

- `GROQ_API_KEY`
- `MCP_SERVER_URL`
- `MCP_AUTH_TOKEN`
- `PULSE_DOC_ID`
- `PULSE_RECIPIENT`

### Use the live app

1. Open the [live app](https://groww-review-puls-mny9sziydzh2kndreerqfh.streamlit.app/).
2. Click **Generate preview** and review the weekly note.
3. Click **Publish** to append the note to the configured Google Doc and create the Gmail draft.

## Tech stack

- Python 3.12
- Streamlit Community Cloud
- FastEmbed with `bge-small-en-v1.5`
- scikit-learn KMeans
- Groq
- Official MCP Python SDK
- MCP server built with Node.js and deployed on Railway

## Known limits

- The Google login for the MCP server expires every 7 days while the Google OAuth app is in Testing mode. Re-run the sign-in and replace the token in Railway.
- Anyone with the app URL can click Publish and write to the Doc.
- About 200 reviews, mostly Hinglish, are held out of the pulse in a noise group.
- Themes are ranked with a keyword-based complaint score, and the cutoff of 0.60 was set by hand. A theme with few reviews can rank first.
- A chosen quote can be praise instead of a problem.
- Republishing the same week can add the note to the Doc twice.
- There is no scheduler. The pulse is run by hand each week.

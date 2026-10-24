# Streamlit Community Cloud deployment

This runbook prepares and deploys `app.py` as a public Streamlit Community
Cloud app. The Railway MCP server remains a separate service. This procedure
does not create a private app or add an application password.

## Before the first push

1. Use Python 3.12 and install only the cloud dependencies:

   ```bash
   source .venv/bin/activate
   python --version
   python -m pip install -r requirements.txt
   pytest -q
   ```

2. Confirm at least one snapshot is tracked and that generated run artifacts
   are not required:

   ```bash
   git ls-files data/snapshots
   git check-ignore data/snapshots/reviews_2026-10-21.jsonl
   ```

   The second command must print nothing and exit with status 1.

3. Check the committed snapshot before staging it:

   ```bash
   git grep -n -E 'userName|userImage|reviewId|replyContent|repliedAt|https?://' -- data/snapshots
   ```

   It must print nothing. The snapshot may contain review text, hashed IDs,
   ratings, dates, app versions, and thumbs-up counts only.

4. Check the staged and tracked content for secrets without inspecting local
   secret files:

   ```bash
   git status --short
   git grep -n "$(printf 'gsk\137')"
   git check-ignore .env .streamlit/secrets.toml data/runs
   ```

   `.env`, `.streamlit/secrets.toml`, and `data/runs/` must be ignored.
   Neither secret file should be staged or tracked.

5. Run a local Streamlit smoke test. Select the committed snapshot and generate
   a preview. Do not click Publish merely to test deployment packaging.

## Create the Community Cloud app

1. Push the reviewed commit to GitHub manually. This repository preparation
   does not push anything.
2. In Streamlit Community Cloud, create an app from that GitHub repository.
3. Select the deployment branch and set the entry point to `app.py`.
4. In Advanced settings, choose Python 3.12.
5. Keep the app public. Do not configure a viewer allow-list and do not add a
   password gate.
6. In the Secrets editor, set exactly these five keys using TOML syntax:

   ```toml
   GROQ_API_KEY = "<value>"
   MCP_SERVER_URL = "<bare Railway MCP URL>"
   MCP_AUTH_TOKEN = "<bearer token>"
   PULSE_DOC_ID = "<Google Doc ID>"
   PULSE_RECIPIENT = "<draft recipient>"
   ```

7. Deploy and wait for the dependency install and app health check to finish.
   The first preview also downloads the FastEmbed model and will be slower than
   later previews in the same app instance.

## Live checks

1. Open the app in a signed-out browser window and confirm it is publicly
   reachable.
2. Confirm `reviews_2026-10-21.jsonl` appears in the snapshot selector.
3. Generate a preview with the committed snapshot. Confirm the note, checks,
   funnel, themes, and run-zip download appear.
4. Compare the cluster count, theme sizes, and quotes with a local run using the
   same snapshot, week ending, and window.
5. Upload a valid JSONL snapshot and confirm preview generation works.
6. Confirm a failed validation keeps Publish disabled.
7. On an approved passing preview, click Publish once. Confirm the configured
   Doc was appended, a Gmail draft was created, and no email was sent.
8. Reload the same week and confirm the app shows the Doc link instead of a
   second Publish button while the current app instance retains its run files.

## Public-app exposure

There is intentionally no viewer authentication. Any visitor can run the
cost-bearing Groq pipeline and, after a passing validation, invoke the
secret-backed Publish action. The per-week `publish.json` duplicate guard lives
on Community Cloud's ephemeral filesystem; it is not a durable authorization
or rate-limit control and can disappear after a restart or redeploy.

Use a dedicated destination document and recipient. Monitor Groq and MCP usage,
and rotate `MCP_AUTH_TOKEN` if the URL is shared beyond the intended audience.

## Rollback

1. Stop or delete the Streamlit app to remove public access.
2. Revoke or rotate `MCP_AUTH_TOKEN` on the Railway service. Update the
   Streamlit secret only when redeploying.
3. Roll back the GitHub branch to the last known-good commit and redeploy.
4. Inspect the destination Doc and Gmail Drafts. Remove duplicate or unwanted
   output manually; a git rollback cannot undo external writes.
5. If only application code is faulty, keep the MCP token revoked until the
   replacement deployment passes the live preview checks.

## Deployment record

Fill this in after deployment:

- Commit:
- Public URL:
- Deployment date:
- Python version shown in logs:
- Snapshot checked:
- Preview result:
- Publish result:
- Rollback owner:

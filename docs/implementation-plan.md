# Implementation Plan

How to build the Groww Weekly Review Pulse, phase by phase. It follows [`architecture.md`](./architecture.md) and [`problemStatement.md`](./problemStatement.md). Where this plan and the architecture disagree, the architecture wins and this plan is updated.

Each phase ends in a working, checkable state. Do not start a phase until the hand checks of the previous one pass. Tasks are sized so each one fits in a single prompt.

Two phases are **PROVISIONAL** and will be rewritten before they are built:

- **Phase 3 (clustering)**, after the owner inspects a real `reviews.jsonl` from Phase 2.
- **Phase 6 (MCP connection)**, after the tool names are read from the MCP server's GitHub README.

## Phase overview

| Phase | Name | Status | Ends with |
| --- | --- | --- | --- |
| 0 | Empty project setup | Ready | Folders, dependencies and config files. No logic |
| 1 | Ingest | Ready | A dated raw snapshot of Groww reviews with no reviewer identity |
| 2 | Normalize | Ready | `reviews.jsonl` plus drop counts per filter |
| 3 | Clustering | **PROVISIONAL** | At most 5 themes with sizes and representatives |
| 4 | Themes, quotes, actions | Ready | Named themes, 3 quote IDs, 3 action ideas |
| 5 | Note, checks, preview UI | Ready | A validated note in a Streamlit preview with a Publish button |
| 6 | MCP connection | **PROVISIONAL** | Publish writes the Google Doc and the Gmail draft |
| 7 | Deployment | Ready | A private app on Streamlit Community Cloud |

---

## Phase 0: Empty project setup

### Goal

Create the folder structure, dependency files and config templates from the architecture's proposed layout. There is no logic in this phase: no functions, no pipeline code, no UI.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/__init__.py`, `src/pulse/delivery/__init__.py` | Empty |
| `scripts/`, `tests/`, `data/snapshots/`, `data/runs/` | Empty folders (with `.gitkeep` where git needs one) |
| `requirements.txt` | Runtime packages only: `streamlit`, `groq`, `fastembed`, `scikit-learn`, `lingua-language-detector`, `emoji`, `mcp`, `python-dotenv`. Exact `==` pins |
| `requirements-dev.txt` | `-r requirements.txt` plus `pytest` and `google-play-scraper`. The scraper runs only on a laptop, so it stays out of the cloud build |
| `runtime.txt` | `python-3.12`. `lingua-language-detector` needs Python 3.12 or later. Records the version to pick in Streamlit's Advanced settings |
| `.env.example` | The four settings from the architecture: `GROQ_API_KEY`, `MCP_SERVER_URL`, `PULSE_DOC_ID`, `PULSE_RECIPIENT`. Placeholder values only |
| `.streamlit/config.toml` | `server.headless = true`, theme |
| `.streamlit/secrets.toml.example` | Same four keys as `.env.example` |
| `.gitignore` | `.env`, `.streamlit/secrets.toml`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `data/runs/` |

### Check by hand when done

- [ ] `python3.12 -m venv .venv && pip install -r requirements-dev.txt` finishes with no errors.
- [ ] `python -c "import streamlit, groq, fastembed, sklearn, lingua, emoji, mcp, google_play_scraper"` prints nothing.
- [ ] `.env.example` lists exactly four keys and contains no real value.
- [ ] No `.py` file contains anything except an empty `__init__.py`.
- [ ] `data/runs/` and `.env` are ignored by git; `data/snapshots/` is not.

### Tasks

1. Create the folder tree and empty `__init__.py` files from the architecture's **Proposed layout**.
2. Write `requirements.txt` and `requirements-dev.txt` with the packages above. Install them in a Python 3.12 venv and pin the versions that were installed.
3. Write `runtime.txt`, `.env.example`, `.streamlit/config.toml` and `.streamlit/secrets.toml.example`.
4. Write `.gitignore` and confirm that `git status` does not list `.env` or `data/runs/`.

---

## Phase 1: Ingest

### Goal

Download recent public Play Store reviews for `com.nextbillion.groww` into a dated raw file. Remove reviewer names, avatars and raw review IDs before anything is written to disk. Nothing in this phase filters or judges reviews.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/config.py` | `APP_ID`, `PLAY_LANG`, `PLAY_COUNTRY`, `WINDOW_WEEKS`, `TIMEZONE`, and the env-then-`st.secrets` lookup for the four settings |
| `src/pulse/models.py` | `Review` dataclass with the snapshot schema: `id`, `rating`, `title`, `text`, `date`, `app_version`, `thumbs_up` |
| `scripts/fetch_reviews.py` | Fetch with `google-play-scraper`, map fields, write the raw file |
| `src/pulse/snapshot.py` | Load and validate a snapshot (JSONL or CSV). Rejects bad rows with the line number |
| `data/snapshots/reviews_YYYY-MM-DD.jsonl` | First real raw file, dated by fetch day |
| `tests/test_snapshot.py` | Schema and identity-stripping tests |

### Check by hand when done

- [ ] Run `python scripts/fetch_reviews.py`. A new `data/snapshots/reviews_<today>.jsonl` appears.
- [ ] The oldest `date` in the file is at least 12 weeks before today. The newest is today or yesterday.
- [ ] Open the file and search for `userName`, `userImage`, `reviewId`, `replyContent`, `repliedAt`, `http`. None are present.
- [ ] Every `id` is 12 hex characters. Every `title` is `null`. Ratings are 1 to 5.
- [ ] Pick 3 reviews at random and compare them with the Play Store page. The `text` matches exactly, including emoji.
- [ ] The script printed how many pages it fetched and paused between pages.

### Tasks

1. Write `config.py` with the defaults from the architecture and a `get_setting(name)` helper that reads the environment first, then `st.secrets`.
2. Write the `Review` dataclass in `models.py`, matching the snapshot schema table.
3. Write `scripts/fetch_reviews.py`. Use `lang="en"`, `country="in"`, newest first, and page until a review is older than `WINDOW_WEEKS` plus one week. Sleep between pages. No login, no proxies.
4. In the same script, map each raw review to `Review`. Hash `reviewId` with SHA-256 and keep the first 12 hex characters. Convert `at` to Asia/Kolkata before taking the date. Never write `userName`, `userImage`, the raw `reviewId`, `replyContent` or `repliedAt`.
5. Write `snapshot.py` to load a JSONL or CSV snapshot into `Review` objects and reject rows with missing fields or wrong types, reporting the line number.
6. Write `tests/test_snapshot.py`. A fake raw review with a name, avatar URL and reply maps to a `Review` with none of them. A bad row is rejected with its line number.
7. Run the script once and commit the first snapshot.

---

## Phase 2: Normalize

### Goal

Apply the four filters in the architecture's order and write `reviews.jsonl` with a count of how many reviews each filter removed. Kept reviews are written unchanged.

Filter order:

1. Window: within the last `WINDOW_WEEKS` full weeks (Monday to Sunday, IST) up to `week_ending`.
2. Emoji-only: drop a review if no letter or digit is left after ignoring emoji, whitespace and punctuation. Do not strip emoji from kept reviews.
3. More than 8 words: keep at least 9 `\w+` tokens.
4. English: keep if `lingua` ranks English first with confidence of at least 0.5.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/filters.py` | One pure function per rule, plus `apply_filters(reviews, week_ending, window_weeks)` returning kept reviews and the funnel |
| `src/pulse/config.py` | Add `MIN_WORDS = 9`, `MIN_ENGLISH_CONFIDENCE = 0.5` |
| `scripts/normalize.py` | CLI: snapshot in, `data/runs/{week_ending}/reviews.jsonl` and `funnel.json` out |
| `tests/test_filters.py` | Boundary and language tests |

`reviews.jsonl` is the file the architecture calls `filtered.jsonl`. Same schema as the snapshot.

`funnel.json` holds: reviews in, removed by window, removed by emoji-only, removed by word count, removed by language, reviews kept. The numbers must add up.

### Check by hand when done

- [ ] Run `python scripts/normalize.py --snapshot data/snapshots/reviews_<date>.jsonl`. `reviews.jsonl` and `funnel.json` appear under `data/runs/<week_ending>/`.
- [ ] In `funnel.json`, reviews in minus every removal equals reviews kept.
- [ ] Search `reviews.jsonl` for a review containing an emoji. It is there, and its text matches the snapshot exactly.
- [ ] No review in `reviews.jsonl` has fewer than 9 words.
- [ ] Read 20 kept reviews. All are English.
- [ ] Read 20 reviews removed by the language filter (the script can print a sample). Note how many are Hinglish, for the owner's Phase 3 review.
- [ ] All dates fall inside the window.

### Tasks

1. Write the window filter, with Monday-to-Sunday weeks in IST and `week_ending` defaulting to the last full Sunday.
2. Write the emoji-only filter with the `emoji` package. Test `👍👍👍` and `🔥🔥 !!!` (dropped) and `Great app 👍 but withdrawals take 3 days` (kept, unchanged).
3. Write the word-count filter. Test 8 words (dropped) and 9 words (kept), and that emoji do not count as words.
4. Write the English filter with `lingua`, limited to English, Hindi and the main Indian languages. Build the detector once and reuse it.
5. Write `apply_filters` to run the rules in order and count removals per rule.
6. Write `scripts/normalize.py` to write `reviews.jsonl` and `funnel.json`, and print a sample of reviews removed by each rule.
7. Run it on the Phase 1 snapshot and hand `reviews.jsonl` to the owner for inspection before Phase 3.

---

## Phase 3: Clustering — PROVISIONAL

> **PROVISIONAL.** This phase will be rewritten after the owner inspects `reviews.jsonl` from Phase 2. The steps below come from the current architecture and may change: the embedding model, the range of `k`, the clustering method, and how generic praise ("good app, easy to use") is handled.

What the inspection should look at:

- How many reviews are kept, and whether that is enough for 3 to 5 stable themes.
- The spread of review lengths after the 9-word minimum.
- Whether generic praise dominates and would swallow a cluster.
- Whether the reviews dropped as non-English take a topic with them (for example, Hinglish complaints about one feature).

### Goal

Group the reviews in `reviews.jsonl` into at most 5 themes, with the same result every time on the same input.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/cluster.py` | Embed with FastEmbed, KMeans for `k` in 3 to 5, pick the best silhouette, compute representatives and theme stats |
| `src/pulse/models.py` | Add `Cluster`: member IDs, centroid, size, share, average rating, share of 1-2 star reviews, representative IDs |
| `src/pulse/config.py` | Add `EMBEDDING_MODEL`, `K_RANGE`, `RANDOM_STATE`, `REPS_PER_THEME` |
| `scripts/cluster.py` | CLI: `reviews.jsonl` in, a readable cluster report out |
| `tests/test_cluster.py` | Determinism and the 5-cluster cap |

### Check by hand when done

- [ ] Run `scripts/cluster.py` twice on the same `reviews.jsonl`. The chosen `k`, cluster sizes and representatives are the same both times.
- [ ] There are never more than 5 clusters.
- [ ] Read the 12 representatives of each cluster. You can say in a few words what each cluster is about.
- [ ] Cluster sizes add up to the number of reviews in `reviews.jsonl`.
- [ ] The silhouette score for each `k` is printed, so the choice of `k` can be explained.

### Tasks

1. Write the embedding step with FastEmbed and `BAAI/bge-small-en-v1.5`. Cache the model between calls.
2. Write the KMeans loop over `k` = 3, 4, 5 with a fixed `random_state`, keeping the best silhouette score.
3. Compute stats for each cluster: size, share, average rating, share of 1-2 star reviews, and the 12 reviews closest to the centroid.
4. Write `scripts/cluster.py` to print each cluster's stats and representatives.
5. Write `tests/test_cluster.py` on a small fixed fixture: same seed, same result; never more than 5 clusters.

---

## Phase 4: Theme naming, quote selection and action ideas

### Goal

Use Groq to name each theme and draft the summary lines and 3 action ideas. Build a PII-clean quote pool and have the LLM pick 3 quotes **by ID only**. Code copies quote text from the data, so quotes stay verbatim.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/llm.py` | Groq client, JSON-only calls, one retry on invalid JSON, one wait-and-retry on a 429 using `retry-after` |
| `src/pulse/themes.py` | One label call per cluster. Returns `{name, summary}` (name of at most 4 words, summary of at most 20). Ranks themes by review count, lowest average rating breaking ties |
| `src/pulse/pii.py` | `find_pii(text)` for emails, Indian phone numbers, PAN, UPI IDs, digit runs of 8 or more, `@handles` and "my name is ..." |
| `src/pulse/note.py` | Quote pool (top 3 themes, 9 to 40 words, PII-clean, 8 nearest the centroid ranked by `thumbs_up`) and the compose call returning `themes`, `quote_ids` and `actions` |
| `src/pulse/models.py` | Add `Theme` and `ComposeResult` |
| `src/pulse/config.py` | Add `GROQ_MODEL`, `QUOTE_WORDS` |
| `tests/test_pii.py`, `tests/test_quote_pool.py`, `tests/test_llm_json.py` | See tasks |

### Check by hand when done

- [ ] Each of the top 3 theme names matches what you saw in that cluster's representatives in Phase 3.
- [ ] Every quote candidate shown is 9 to 40 words long and has no email, phone number, PAN, UPI ID or long number.
- [ ] Every `quote_id` returned by the compose call is in the quote pool. An unknown ID is rejected, not guessed.
- [ ] Each action names one of the top 3 themes and is something a product, growth or support team could do.
- [ ] The summary lines and actions contain no numbers that were not in the input.
- [ ] Groq calls in a run: at most 5 label calls and 1 compose call.

### Tasks

1. Write `llm.py`: a `call_json(system, user, schema_hint)` helper with low temperature, JSON-only output, one retry on invalid JSON, and one wait-and-retry on a 429.
2. Write `themes.py`: the label prompt with only the cluster's representatives, the length limits for name and summary, and ranking by review count.
3. Write `pii.py` with one pattern per PII type, and `tests/test_pii.py` with a positive and a negative example for each.
4. Write the quote pool in `note.py`, and `tests/test_quote_pool.py`: a review with a phone number never enters the pool; a 41-word review never enters the pool.
5. Write the compose prompt and call. Validate the returned JSON shape: 3 theme lines, 3 distinct quote IDs from the pool, 3 actions with `theme_rank` 1, 2 or 3.
6. Write `tests/test_llm_json.py` with a fake Groq response: valid JSON is parsed; invalid JSON triggers exactly one retry; an unknown quote ID is rejected.

---

## Phase 5: Note assembly, validation and preview UI

### Goal

Build the note in code from the template, run every validation check, and show the result in a Streamlit preview with a Publish button. The Publish button is enabled only when every check passes. It is not connected to the MCP server until Phase 6.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/note.py` | `assemble(themes, compose_result, reviews)` using the architecture's template, and `validate(note, result) -> list[Failure]` |
| `src/pulse/pipeline.py` | `run_pulse(snapshot, week_ending) -> PulseResult`: Phases 2 to 5 end to end, the retry-once-on-failed-checks rule, and the run artifacts |
| `src/pulse/models.py` | Add `PulseResult` and `Failure` |
| `scripts/run_pulse.py` | CLI preview: prints the note, word count, checks and funnel |
| `app.py` | Streamlit preview UI |
| `tests/test_note.py`, `tests/test_pipeline.py` | See tasks |

Run artifacts written to `data/runs/{week_ending}/`: `reviews.jsonl`, `funnel.json`, `themes.json`, `note.md`, `checks.json`.

Validation checks, all required:

| Check | Rule |
| --- | --- |
| Length | At most 250 `\w+` words over the whole note |
| Structure | Exactly 3 themes, 3 quotes, 3 actions; each action references a top-3 theme |
| Verbatim | Each quote is an exact substring of a review `text` in `reviews.jsonl` |
| Distinct quotes | The 3 quote IDs are different |
| Grounded numbers | Every number in the note is in the computed stats or the template |
| PII | `find_pii` finds nothing in the full note |

### Check by hand when done

- [ ] `python scripts/run_pulse.py --snapshot <file>` prints a note of 250 words or fewer, with every check passing.
- [ ] Copy each quote from the note and search for it in `reviews.jsonl`. Each is found exactly, emoji included.
- [ ] Next to each quote there is only a star rating: no date, app version or ID.
- [ ] The note can be read in under a minute and fits on one page.
- [ ] `streamlit run app.py`: pick the snapshot, click **Generate preview**. The note, word count, checks, funnel and all themes appear.
- [ ] Break a check on purpose (for example, set `MAX_NOTE_WORDS = 50` locally). The UI lists the failed check and the Publish button is disabled.
- [ ] With all checks passing, the Publish button is enabled. Clicking it says publishing is not connected yet and contacts nothing.
- [ ] `data/runs/<week_ending>/` has all five artifacts, and none contain a name, avatar URL or raw review ID.

### Tasks

1. Write `assemble()` from the template. Copy quote text from `reviews.jsonl` by ID. Only the star rating goes next to a quote.
2. Write `validate()` with the six checks. Write `tests/test_note.py` with a passing note and one failing note per check.
3. Write `run_pulse()` in `pipeline.py`: load, filter, cluster, label, compose, assemble, validate. On failure, retry the compose call once with the failure list; then stop. Stop early with a clear message when fewer than 30 reviews remain or fewer than 3 themes have a quote candidate.
4. Add the run artifacts to `run_pulse()`, and a zip of the run folder for download.
5. Write `scripts/run_pulse.py` (preview only, no `--publish` yet).
6. Write `app.py`: sidebar with the snapshot picker or upload, `week_ending` and window weeks (8 to 12); a **Generate preview** button; a note panel with word count; a checks table; the filter funnel; a themes table with representatives; a zip download.
7. Add the **Publish** button to `app.py`: disabled unless every check passed; for now it shows "Publishing is not connected yet."
8. Write `tests/test_pipeline.py` with fake LLM and fake embeddings: a run that passes, a run that fails twice and stops, and a run with too few reviews.

---

## Phase 6: Connect to the MCP server — PROVISIONAL

> **PROVISIONAL.** This phase will be rewritten after the MCP server's GitHub README is read. Tool names, arguments, response shapes, the transport and any auth header are **not** filled in here and must not be guessed. They are recorded in this section and in the architecture's **Delivery through MCP** section before any task is built.

What must be read from the README before rewriting:

- The tool that writes to an existing Google Doc by ID, and whether it replaces or appends.
- The tool that creates a Gmail draft, its recipient, subject and body arguments, and its response.
- Whether the server also has a send tool. The brief says the output is a **draft** and auto-sending is out of scope, so only a draft tool may be used. If the server can only send, stop and raise it with the owner.
- The transport (for example streamable HTTP) and whether the server expects an auth header.
- How the server returns errors, including Google errors.

### Goal

Make the Publish button write the validated note to the Google Doc at `PULSE_DOC_ID` and create a Gmail draft to `PULSE_RECIPIENT` containing the note and the Doc link. All calls go through the MCP server at `MCP_SERVER_URL`. The agent holds no Google credentials.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/delivery/mcp_client.py` | Remote session to `MCP_SERVER_URL` with the official `mcp` SDK |
| `src/pulse/delivery/publish.py` | `publish(result)`: write the Doc, then create the draft, then return the link and confirmation |
| `app.py` | Publish button calls `publish()`; shows the Doc link and draft confirmation; "Retry email" when the Doc write worked and the draft did not |
| `scripts/run_pulse.py` | Add `--publish` |
| `src/pulse/pipeline.py` | Write `publish.json` after a successful publish |
| `tests/test_publish.py`, `tests/test_no_google_sdk.py` | See tasks |

### Check by hand when done

- [ ] Click **Publish** with all checks passing. The Google Doc at `PULSE_DOC_ID` shows this week's note, word for word as in the preview.
- [ ] A Gmail draft to `PULSE_RECIPIENT` exists with the note and a working Doc link. **No email was sent.** Check Gmail's Sent folder.
- [ ] Clicking Publish twice for the same week does not leave the note twice in the Doc (behaviour depends on the write tool; confirm against the README).
- [ ] Set `MCP_SERVER_URL` to a wrong address. Publish fails with a clear connection error and the preview still works.
- [ ] Search `src/` for `googleapiclient` and `google.oauth2`. Nothing is found.
- [ ] Neither `.env.example` nor the code contains any Google OAuth client, token or account setting.

### Tasks

1. Read the MCP server's GitHub README and record the tool names, arguments, responses, transport and auth in this section and in `architecture.md`. Rewrite the tasks below to match.
2. Write `mcp_client.py`: open a session to `MCP_SERVER_URL`, list the server's tools, and fail early with a clear message if a required tool is missing.
3. Write `publish.py`: the Doc write to `PULSE_DOC_ID`, then the draft to `PULSE_RECIPIENT`. Never call a send tool.
4. Wire the Publish button and "Retry email" in `app.py`, and add `--publish` to `scripts/run_pulse.py`.
5. Write `tests/test_publish.py` against a fake MCP session that records calls: the Doc write targets `PULSE_DOC_ID`, the draft goes only to `PULSE_RECIPIENT`, the Doc write comes before the draft, and no send tool is ever called.
6. Write `tests/test_no_google_sdk.py`: fail if `googleapiclient` or `google.oauth2` is imported anywhere under `src/`.

---

## Phase 7: Deployment on Streamlit Community Cloud

### Goal

Deploy `app.py` from GitHub to Streamlit Community Cloud, the same way as the Nutrition RAG project. Secrets are set in Streamlit's secrets store. The MCP server is a separate Railway deployment and is not deployed here.

### Files created or changed

| File | Contents |
| --- | --- |
| `requirements.txt` | Re-check the pins against a clean Python 3.12 install |
| `README.md` | What the app does, how to run it locally, how to fetch a snapshot, and how to deploy |
| `docs/deployment-plan.md` | Step-by-step deploy, checks and rollback, in the style of the Nutrition RAG plan |
| `data/snapshots/` | At least one committed, PII-free snapshot so the deployed app has data |

### Check by hand when done

- [ ] Before the first push: `git status` does not list `.env` or `.streamlit/secrets.toml`, and `git grep -n "gsk_"` prints nothing.
- [ ] Search every committed snapshot for `userName`, `userImage`, `reviewId` and `http`. Nothing is found.
- [ ] The app is deployed as **private**, viewable only by listed emails. The Publish button can write to the owner's Google Doc and Gmail, so it must not be public.
- [ ] Python 3.12 is selected in Advanced settings. Secrets hold exactly `GROQ_API_KEY`, `MCP_SERVER_URL`, `PULSE_DOC_ID` and `PULSE_RECIPIENT`.
- [ ] On the live URL: pick the committed snapshot and generate a preview. The first run is slow (embedding model download); later runs are faster.
- [ ] The live preview matches a local preview of the same snapshot: same `k`, same theme sizes, same quotes.
- [ ] Publish from the live app. The Doc updates and a Gmail draft appears. Nothing is sent.
- [ ] Uploading a snapshot file in the live app works.

### Tasks

1. Rehearse in a clean Python 3.12 venv with only `requirements.txt`. Run `pytest -q` and a full preview. Fix the pins locally, not on the server.
2. Write `README.md` and `docs/deployment-plan.md`.
3. `git init`, confirm no secrets are staged, commit, and push to a new GitHub repo.
4. Create the Streamlit app: repo, `main` branch, `app.py`, Python 3.12, the four secrets, private visibility.
5. Run the live checks above. Record the results in `docs/deployment-plan.md`.

---

## Requirements trace

Each rule in `problemStatement.md`, the phase that builds it, and where it is checked.

| Rule in the problem statement | Phase | Checked by |
| --- | --- | --- |
| Source is Google Play Store reviews only | 1 | `fetch_reviews.py` uses `APP_ID` on Google Play only |
| App Store is out of scope | 1 | No App Store fetcher exists |
| Window of roughly the last 8 to 12 weeks | 1, 2 | Fetch goes back at least 12 weeks (Phase 1); window filter, 8 to 12 allowed (Phase 2) |
| Fields: rating, title, text, date | 1 | Snapshot schema; `title` kept as null because Play does not provide it |
| Pull recent Play Store reviews | 1 | Dated raw snapshot check |
| Public review exports only; no scraping behind logins; no ToS-violating automation | 1 | Logged-out public feed, no login, no proxies, pauses between pages, run from a laptop |
| Keep only reviews with more than 8 words | 2 | Word-count filter and its 8- vs 9-word test |
| Remove emoji reviews | 2 | Emoji-only filter; kept reviews unchanged |
| Remove non-English reviews | 2 | English filter and its hand check |
| Cluster into at most 5 themes | 3 | `k` capped at 5; test |
| The note highlights the top 3 themes | 4, 5 | Ranking by review count (Phase 4); structure check (Phase 5) |
| 3 real user quotes, verbatim, no invented wording | 4, 5 | Quotes chosen by ID (Phase 4); verbatim check (Phase 5) |
| 3 action ideas grounded in the themes | 4, 5 | Each action carries a `theme_rank` (Phase 4); structure and grounded-numbers checks (Phase 5) |
| Write a one-page weekly note | 5 | Template and one-page hand check |
| 250 words or fewer | 5 | Length check |
| Note is scannable | 5 | Template headings and the under-a-minute hand check |
| No PII in any artifact; no usernames, emails, device IDs or reviewer identity | 1, 4, 5, 7 | Identity stripped at fetch (1); PII-clean quote pool (4); PII check on the note and artifacts (5); committed snapshot check (7) |
| Quotes are anonymous | 5 | Only a star rating next to each quote |
| Put the note in a Google Doc | 6 | Doc write to `PULSE_DOC_ID` |
| Create a Gmail draft to myself or an alias, with the note or a link | 6 | Draft to `PULSE_RECIPIENT` with the note and the Doc link |
| Docs and Gmail go through MCP tools; no direct Google API code | 6 | `publish()` uses only the MCP client; no-Google-SDK test |
| Auto-sending email is out of scope; output is a draft | 6 | Only a draft tool is used; test that no send tool is called; Sent-folder hand check |
| Deployment follows the Zomato and RAG projects | 7 | Streamlit Community Cloud from GitHub, as in the Nutrition RAG project |

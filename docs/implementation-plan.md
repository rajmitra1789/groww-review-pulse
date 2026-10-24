# Implementation Plan

How to build the Groww Weekly Review Pulse, phase by phase. It follows [`architecture.md`](./architecture.md) and [`problemStatement.md`](./problemStatement.md). Where this plan and the architecture disagree, the architecture wins and this plan is updated.

Each phase ends in a working, checkable state. Do not start a phase until the hand checks of the previous one pass. Tasks are sized so each one fits in a single prompt.

## Phase overview

| Phase | Name | Status | Ends with |
| --- | --- | --- | --- |
| 0 | Empty project setup | Ready | Folders, dependencies and config files. No logic |
| 1 | Ingest | Ready | A dated raw snapshot of Groww reviews with no reviewer identity |
| 2 | Normalize | Ready | `reviews.jsonl` plus drop counts per filter |
| 3 | Clustering | Ready | At most 5 themes with sizes and representatives |
| 4 | Themes, quotes, actions | Ready | Named themes, 3 quote IDs, 3 action ideas |
| 5 | Note, checks, preview UI | Ready | A validated note in a Streamlit preview with a Publish button |
| 6 | MCP connection | Ready | Publish appends to the Google Doc and creates the Gmail draft |
| 7 | Deployment | Ready | A public app on Streamlit Community Cloud |

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
| `.env.example` | The five settings from the architecture: `GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_AUTH_TOKEN`, `PULSE_DOC_ID`, `PULSE_RECIPIENT`. Placeholder values only |
| `.streamlit/config.toml` | `server.headless = true`, theme |
| `.streamlit/secrets.toml.example` | Same five keys as `.env.example` |
| `.gitignore` | `.env`, `.streamlit/secrets.toml`, `.venv/`, `__pycache__/`, `.pytest_cache/`, `data/runs/` |

### Check by hand when done

- [ ] `python3.12 -m venv .venv && pip install -r requirements-dev.txt` finishes with no errors.
- [ ] `python -c "import streamlit, groq, fastembed, sklearn, lingua, emoji, mcp, google_play_scraper"` prints nothing.
- [ ] `.env.example` lists exactly five keys and contains no real value.
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
| `src/pulse/config.py` | `APP_ID`, `PLAY_LANG`, `PLAY_COUNTRY`, `WINDOW_WEEKS`, `TIMEZONE`, and the env-then-`st.secrets` lookup for the five settings: `GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_AUTH_TOKEN`, `PULSE_DOC_ID`, `PULSE_RECIPIENT` |
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

## Phase 3: Clustering

### What the real data showed

Measured on `data/snapshots/reviews_2026-10-21.jsonl` and the Phase 2 output for week ending 2026-10-18 (`data/runs/2026-10-18/reviews.jsonl`). The keyword counts come from simple word lists, so treat them as estimates.

| Measure | Value |
| --- | --- |
| Snapshot | 13,625 reviews, 2026-07-22 to 2026-10-20. 77% five-star, 10% one-star. Median length 2 words |
| Kept by Phase 2 | 1,950 (window removed 749, emoji-only 288, word count 10,558, language 80) |
| Rating split of kept | 1★ 42%, 2★ 6%, 3★ 8%, 4★ 9%, 5★ 36%. The 9-word minimum keeps mostly complaints |
| Word count of kept | median 20; 10th to 90th percentile 10 to 64; max 188. 481 reviews have 9 to 12 words; 92 have more than 80 |
| Generic praise | About 260 (13%): praise words, no complaint words, no specific topic. 228 of them are 5★ |
| Complaint topics | 1,035 reviews contain complaint words. 14 topics reach 2% of kept reviews, 7 reach 5%: app slow/crashes/glitches, customer support, F&O and options trading, app updates and UI changes, charges and brokerage, charts and indicators, order execution. 483 complaints touch 2 or more topics |
| Hinglish (Roman-script Hindi) | About 201 (10%), 40 of them mostly Hindi. Romanised Punjabi and Telugu also appear. 105 of the 201 are 1★ |
| Gibberish and other noise | About 7 keyboard-mash reviews, 1 Kannada-script review, plus a few off-topic ones (under 0.5%) |
| Rating disagrees with text | 207 reviews rated 4–5★ contain complaint words (107 with no praise at all). 16 reviews rated 1–2★ contain only praise |

Why Hinglish got through Phase 2: `lingua`'s Hindi model only recognises Devanagari script. On Latin-script text, English is the only candidate, and every Hinglish review scored English confidence 1.0. Raising `MIN_ENGLISH_CONFIDENCE` cannot catch them, so Phase 3 handles them.

What the clustering trials showed (FastEmbed, KMeans, `random_state` 42):

- **There is no natural number of clusters.** Silhouette scores were 0.047 to 0.054 for every `k` from 3 to 10. Choosing `k` by silhouette picks noise.
- **Raw embeddings group by mood, not topic.** At `k` = 5, one cluster was 75% generic praise and another was 90% 1–2★ "worst app" reviews mixing withdrawals, support and bugs.
- **Taking out generic praise and the positive/negative direction helps.** Agreement with keyword topics rose from 0.29 to 0.33 at `k` = 5, and no cluster was dominated by one mood (52% to 85% complaint share).
- **Merging 12 small clusters into 5 by distance fails.** One merged group took about 65% of reviews. Merging with the LLM would move a Groq call into this phase, so it is not used.
- **`jinaai/jina-embeddings-v2-small-en` was no better than `BAAI/bge-small-en-v1.5`** (0.34 to 0.39 against 0.35 to 0.39 for `k` from 8 to 15). Embedding about 1,500 reviews took about 50 seconds on a laptop with either model.

### Goal

Split `reviews.jsonl` into three groups, using only review text, never star ratings:

1. **Noise**: Hinglish and other Roman-script Indian languages, gibberish, non-Latin script. Counted and reported. Never clustered, ranked, quoted or sent to the LLM.
2. **Generic praise**: praise with no specific topic. Counted and reported as one line ("13% general praise"). Never clustered, ranked or quoted.
3. **Clusterable**: everything else (about 1,490 reviews on this snapshot), grouped into exactly 5 themes. Fewer than 5 only if there are too few reviews.

The two buckets are not themes and do not count toward the cap of 5. The result is the same every time on the same input.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/buckets.py` | Text-only rules: `is_hinglish`, `is_gibberish`, `is_non_latin`, `is_generic_praise`, and the word lists they use (Roman-Hindi function words, praise words, complaint words, topic words). `split_buckets(reviews)` returns noise, generic praise and clusterable, and records why each noise review was removed |
| `src/pulse/cluster.py` | Embed, cache embeddings, remove the positive/negative direction, KMeans, cluster stats, representatives |
| `src/pulse/models.py` | Add `Cluster`: member IDs, centroid, size, share of clusterable, share of kept, complaint share (from text), top topic words, representative IDs. Average rating and 1–2★ share are stored for display only. Add `Buckets`: counts per noise reason, generic praise count, and the topic words found in noise |
| `src/pulse/config.py` | Add `EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"`, `N_CLUSTERS = 5`, `MIN_CLUSTERABLE = 250`, `RANDOM_STATE = 42`, `KMEANS_N_INIT = 10`, `REPS_PER_THEME = 12` |
| `scripts/cluster.py` | CLI: `reviews.jsonl` in. Writes `buckets.json`, `clusters.json` and `embeddings.npy` to the run folder and prints a readable report |
| `tests/test_buckets.py`, `tests/test_cluster.py` | See tasks |

Rules in `buckets.py`, applied in this order. Each review gets the first rule it matches:

| Rule | Bucket | Definition |
| --- | --- | --- |
| Non-Latin script | Noise | More than half the letters are outside the Latin alphabet (catches the Kannada review, and any other script Phase 2's detector does not know) |
| Gibberish | Noise | At least 5 letter-tokens, and either 60% or more are 1–2 letters long, or a character repeats 5 or more times, with under 20% real English words of 3+ letters. Checked against an English word list shipped in the repo, not the operating system's |
| Hinglish | Noise | At least 2 distinct strong Roman-Hindi words (`hai`, `nahi`, `nhi`, `kya`, `bahut`, `bekar`, `bakwas`, `chahiye`, …), or Hindi words making up at least 25% of the tokens. Weak words that are also English (`main`, `par`, `pe`, `ho`) count only toward the 25% rule |
| Generic praise | Generic praise | Has a praise word, has no complaint word, and matches no topic word |
| Everything else | Clusterable | |

The noise report keeps the topic words found in Hinglish reviews (for example, brokerage complaints) so the team can see what this rule removes.

Clustering, on the clusterable reviews only:

1. **Embedding model: `BAAI/bge-small-en-v1.5`** through FastEmbed (384 dimensions, no prefix). Its 512-token window covers the longest kept review (188 words). It matched the Jina model on this data and is smaller. Embeddings are normalised and cached in `embeddings.npy`, keyed by review ID and model name, so re-runs skip the roughly 50-second embed.
2. **Remove the positive/negative direction.** Compute the mean embedding of reviews with complaint words minus the mean of reviews with only praise words (text cues, never ratings). Project that direction out of every embedding and normalise again.
3. **KMeans with `k` = 5**, `random_state` 42, `n_init` 10. `k` is fixed, not chosen by silhouette. If there are fewer than `MIN_CLUSTERABLE` (250) clusterable reviews, use `k` = 3. Print the silhouette score for information only.
4. **Stats for each cluster:** size, share of clusterable and of kept, complaint share (from text), the top 3 topic words, and average rating and 1–2★ share for display only. Ratings never decide cluster membership, ranking, names or representatives.
5. **Representatives:** the 12 reviews closest to the centroid. They come only from the clusterable group, so noise and generic praise can never be shown to the LLM in Phase 4 or quoted.

Phase 4 ranks themes by size, with the complaint share from this phase breaking ties.

### Check by hand when done

- [ ] Run `python scripts/cluster.py --run data/runs/2026-10-18` twice. Bucket counts, cluster sizes and representatives are identical both times. The second run reuses `embeddings.npy`.
- [ ] Noise plus generic praise plus clusterable equals the 1,950 reviews in `reviews.jsonl`. Cluster sizes add up to clusterable.
- [ ] On this snapshot: noise is about 200 to 215 (mostly Hinglish), generic praise about 250 to 265, clusterable about 1,480 to 1,500.
- [ ] Read 20 reviews from each noise reason. At most 2 per 20 are plain English that should have been kept.
- [ ] Read 20 generic-praise reviews. None names a specific feature, problem or request.
- [ ] Exactly 5 clusters. None holds more than 35% of clusterable reviews. None is more than 60% praise-only reviews.
- [ ] Read the 12 representatives of each cluster. You can name what it is about in a few words, and none of them is Hinglish or gibberish.
- [ ] Find a 4–5★ review that complains (for example about charges). It sits in a complaint-topic cluster, not with praise.

### Tasks

1. Write `buckets.py` with the four rules and their word lists, and `split_buckets` returning the three groups plus the counts per reason.
2. Write `tests/test_buckets.py`: Hinglish complaints, Romanised Punjabi, keyboard mash, a non-Latin-script review and repeated-letter spam go to noise; plain English that contains `main` or `par` is not Hinglish; "very easy to use, love it" is generic praise; "good app but brokerage is too high" is clusterable. Use invented examples, not real reviews.
3. Write the embedding step in `cluster.py` with FastEmbed and `bge-small-en-v1.5`. Load the model once, and read or write the `embeddings.npy` cache.
4. Write the step that removes the positive/negative direction, using text cues only.
5. Write KMeans with `k` = 5 (3 below `MIN_CLUSTERABLE`), the cluster stats and the 12 representatives.
6. Write `scripts/cluster.py` to write `buckets.json` and `clusters.json` and print the bucket counts, each cluster's stats and representatives, and the silhouette score.
7. Write `tests/test_cluster.py` on a small fixed fixture: same input gives the same clusters; never more than 5; noise and generic praise never appear as members or representatives; changing only star ratings changes no cluster.

---

## Phase 4: Theme naming, quote selection and action ideas

### Goal

Use Groq to name each theme and draft the summary lines and 3 action ideas. Build a PII-clean quote pool and have the LLM pick 3 quotes **by ID only**. Code copies quote text from the data, so quotes stay verbatim.

Themes are ranked by review count, with the complaint share from Phase 3 (measured from text) breaking ties, highest first. When picking the top 3, any cluster whose complaint share is below `MIN_COMPLAINT_SHARE` is skipped, so a mostly-praise cluster cannot take a top slot. If fewer than 3 clusters pass, the remaining slots are filled from the skipped clusters by review count, largest first. Star ratings never decide ranking or quote choice. Quote candidates are sent to the LLM as `{id, theme, text}`, without their rating. The rating is added next to the quote only when the note is assembled in Phase 5.

A quote candidate is dropped if `find_pii` matches (email, phone number, PAN, UPI ID, digit run of 8 or more) or if `looks_like_name` says it appears to contain a person's name. The name check is a simple heuristic and errs on the side of dropping:

- two or more consecutive capitalised words (such as `Rahul Sharma`) that are not at the start of a sentence, or
- a name pattern at the very start of the review, such as one or two capitalised words followed by a comma, a colon or "here" (`Priya here, ...`, `Amit Kumar: ...`), or
- a name-like signature at the very end of the review, such as a capitalised word followed by one or two single-letter initials (`... Yogeshwara m p`), or a sign-off word followed by one or two capitalised words (`Thanks, Priya`, `Regards Amit Kumar`).

Known product and brand words (`Groww`, `Google Play`, `Mutual Funds`, `F&O` and similar) are listed in `pii.py` and do not count as names. `looks_like_name` applies only to the quote pool, not to the final note, because theme names are capitalised.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/llm.py` | Groq client, JSON-only calls, one retry on invalid JSON, one wait-and-retry on a 429 using `retry-after` |
| `src/pulse/themes.py` | One label call per cluster. Returns `{name, summary}` (name of at most 4 words, summary of at most 20). Ranks themes by review count, complaint share breaking ties, skips clusters below `MIN_COMPLAINT_SHARE` for the top 3 and fills any empty slots by size |
| `src/pulse/pii.py` | `find_pii(text)` for emails, Indian phone numbers, PAN, UPI IDs, digit runs of 8 or more, `@handles` and "my name is ...". `looks_like_name(text)` for the name heuristic (including end-of-review signatures and sign-offs), with its list of product and brand words and its list of sign-off words |
| `src/pulse/note.py` | Quote pool (top 3 themes, 9 to 40 words, PII-clean, no likely name, 8 nearest the centroid ranked by `thumbs_up`) and the compose call returning `themes`, `quote_ids` and `actions` |
| `src/pulse/models.py` | Add `Theme` and `ComposeResult` |
| `src/pulse/config.py` | Add `GROQ_MODEL`, `QUOTE_WORDS`, `MIN_COMPLAINT_SHARE` (value set during the hand check below) |
| `tests/test_pii.py`, `tests/test_quote_pool.py`, `tests/test_llm_json.py` | See tasks |

### Check by hand when done

- [ ] Print the complaint share of each cluster. Set `MIN_COMPLAINT_SHARE` so the mostly-praise cluster falls below it and the complaint-topic clusters stay above it. Re-run and confirm the mostly-praise cluster is not in the top 3 (unless it was needed to fill a slot).
- [ ] Each of the top 3 theme names matches what you saw in that cluster's representatives in Phase 3.
- [ ] Every quote candidate shown is 9 to 40 words long and has no email, phone number, PAN, UPI ID, long number or person's name.
- [ ] Every `quote_id` returned by the compose call is in the quote pool. An unknown ID is rejected, not guessed.
- [ ] Read all 3 chosen quotes in full. None contains a person's name.
- [ ] The quote pool sent to the compose call has no star ratings in it.
- [ ] Each action names one of the top 3 themes and is something a product, growth or support team could do.
- [ ] The summary lines and actions contain no numbers that were not in the input.
- [ ] Groq calls in a run: at most 5 label calls and 1 compose call.

### Tasks

1. Write `llm.py`: a `call_json(system, user, schema_hint)` helper with low temperature, JSON-only output, one retry on invalid JSON, and one wait-and-retry on a 429.
2. Write `themes.py`: the label prompt with only the cluster's representatives, the length limits for name and summary, and ranking by review count with complaint share breaking ties. When picking the top 3, skip clusters below `MIN_COMPLAINT_SHARE`; if fewer than 3 remain, fill the rest from the skipped clusters by size.
3. Write `pii.py` with one pattern per PII type and `looks_like_name`, and `tests/test_pii.py` with a positive and a negative example for each. For names: `Rahul Sharma` mid-sentence, `Priya here, ...` at the start, a review ending in `... Yogeshwara m p` and a review ending in `Thanks, Priya` are caught; `Groww`, `Mutual Funds`, an ordinary capitalised first word of a sentence and a review ending in a plain `Thanks` are not.
4. Write the quote pool in `note.py`, and `tests/test_quote_pool.py`: a review with a phone number never enters the pool; a review with a likely name never enters the pool; a review ending in a name-like signature never enters the pool; a 41-word review never enters the pool; changing only star ratings changes neither the theme ranking nor the pool; a large cluster below `MIN_COMPLAINT_SHARE` is left out of the top 3 when 3 other clusters pass, and is used to fill a slot when fewer than 3 pass.
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

## Phase 6: Connect to the MCP server

### Goal

Make the Publish button append the validated note to the Google Doc at `PULSE_DOC_ID` and create a Gmail draft to `PULSE_RECIPIENT` containing the note and the Doc link. Draft only. No send. All calls go through the MCP server; the agent holds no Google credentials.

Publish runs only when the owner clicks **Publish**, and the button works only after every validation check has passed. Nothing publishes automatically.

### MCP server

Details are in the architecture's **Delivery through MCP** section. In short:

| Item | Value |
| --- | --- |
| URL | `https://mcp-server-pulse-production.up.railway.app` (`MCP_SERVER_URL`) |
| Code | [github.com/rajmitra1789/mcp-server-pulse](https://github.com/rajmitra1789/mcp-server-pulse) |
| Transport | Streamable HTTP at `MCP_SERVER_URL` itself, with no path added. The server's only other routes are `GET /health`, `GET /`, `/oauth/start` and `/oauth/callback` |
| Auth | `Authorization: Bearer <MCP_AUTH_TOKEN>` on every request |
| Doc tool | `google_docs_append_content` with `documentId`, `content`, `ensureLeadingNewline: true` |
| Draft tool | `gmail_create_draft` with `to` (array), `subject`, `body`, `bodyType: "text"` |
| Never called | `gmail_send_email` |

### Secrets

There are now five: `GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_AUTH_TOKEN`, `PULSE_DOC_ID`, `PULSE_RECIPIENT`. `MCP_AUTH_TOKEN` is the bearer token for the MCP server, not a Google credential.

### Files created or changed

| File | Contents |
| --- | --- |
| `src/pulse/config.py` | Add `MCP_AUTH_TOKEN` to the settings read through `get_setting()` |
| `.env.example`, `.streamlit/secrets.toml.example` | Add `MCP_AUTH_TOKEN` with a placeholder value. Five keys in total |
| `src/pulse/delivery/mcp_client.py` | `McpClient`: streamable HTTP session to `MCP_SERVER_URL` (no path added) with the bearer header, a tool check, and `call_tool(name, args)` that returns the parsed envelope |
| `src/pulse/delivery/publish.py` | `publish(result, client)`: append to the Doc, then create the draft. `retry_draft(result, client)`: the draft step only |
| `src/pulse/models.py` | Add `PublishResult`: Doc link, `charactersAppended`, `draftId`, and the error code and message of a failed step |
| `src/pulse/pipeline.py` | Write `publish.json` to the run folder after each publish or retry |
| `app.py` | Wire the Publish button to `publish()`; show the Doc link and draft confirmation; show **Retry draft** when the append worked and the draft did not |
| `scripts/run_pulse.py` | Add `--publish`, which only runs when every check passed |
| `tests/test_publish.py`, `tests/test_mcp_client.py`, `tests/test_no_google_sdk.py` | See tasks |

### Check by hand when done

- [ ] With all five secrets set, `streamlit run app.py`, generate a preview, and confirm every check passes before clicking anything.
- [ ] Break a check on purpose. The Publish button is disabled and clicking around the page contacts nothing.
- [ ] Generating a preview, reloading the page and changing sidebar settings never publish on their own.
- [ ] Set `PULSE_DOC_ID` to my Doc ID and `PULSE_RECIPIENT` to my address. Click **Publish** once.
- [ ] Open the Doc. This week's note appears at the end, word for word as in the preview, and nothing above it changed.
- [ ] Open Gmail Drafts. A draft to my address is there, with the note and a Doc link that opens the Doc.
- [ ] Gmail's Sent folder has no new email.
- [ ] The UI shows the Doc link and the draft confirmation, and `data/runs/<week_ending>/publish.json` holds the Doc link, `charactersAppended` and `draftId`.
- [ ] Reload the app for the same week. The Publish button is replaced by the Doc link, so the note cannot be appended twice.
- [ ] Set `MCP_AUTH_TOKEN` to a wrong value. Publish fails with a clear auth error, nothing is appended, and the preview still works.
- [ ] Set `MCP_SERVER_URL` to a wrong address. Publish fails with a clear connection error and the preview still works.
- [ ] Search `src/` for `googleapiclient`, `google.oauth2` and `gmail_send_email`. Nothing is found.
- [ ] Neither `.env.example` nor the code contains any Google OAuth client, token or account setting.

### Tasks

1. Add `MCP_AUTH_TOKEN` to `config.py`, `.env.example` and `.streamlit/secrets.toml.example`.
2. Write `mcp_client.py`: open a streamable HTTP session to `MCP_SERVER_URL` itself, with no path added, using the official `mcp` SDK, passing `Authorization: Bearer <MCP_AUTH_TOKEN>` as a header so it goes on every request. List the tools and stop with a clear message if `google_docs_append_content` or `gmail_create_draft` is missing. `call_tool()` parses the response and turns `ok: false` into an error that carries `code` and `message`.
3. Write `publish()` in `publish.py`. Call `google_docs_append_content` with `documentId` set to `PULSE_DOC_ID`, `content` set to the final note and `ensureLeadingNewline` set to `true`. If that fails, stop and return the error. Then call `gmail_create_draft` with `to` set to `[PULSE_RECIPIENT]`, `subject` set to the note's first line, `body` set to the note, a blank line and `https://docs.google.com/document/d/{PULSE_DOC_ID}/edit`, and `bodyType` set to `"text"`. Never call `gmail_send_email`. Refuse to run if any validation check failed.
4. Write `retry_draft()` in `publish.py`: the draft call only, using the same arguments. It never calls the append tool.
5. Write `publish.json` from `pipeline.py` after each publish or retry. When it records a successful append for a week, the app treats the Doc step as done for that week.
6. Wire `app.py`. The Publish button is enabled only when every check passed and calls `publish()` only on click. After an append that worked and a draft that failed, show the Doc link, the draft error and a **Retry draft** button that calls `retry_draft()`. When `publish.json` already records an append for the week, show the Doc link instead of the Publish button.
7. Add `--publish` to `scripts/run_pulse.py`. It publishes only when every check passed, and it is never the default.
8. Write `tests/test_mcp_client.py`: replace the SDK's streamable HTTP connection with a stub that records its arguments, and assert the URL is exactly `MCP_SERVER_URL` with no path added and the headers hold `Authorization: Bearer <MCP_AUTH_TOKEN>`. Assert a missing required tool stops with a clear message. No network.
9. Write `tests/test_publish.py` against a fake MCP client that records every call and returns set envelopes. Assert: the append targets `PULSE_DOC_ID` with `ensureLeadingNewline: true`; the draft goes only to `[PULSE_RECIPIENT]` with `bodyType: "text"` and contains the note and the Doc link; the append comes before the draft; a failed append means no draft call; a failed draft leaves the append result in place; `retry_draft()` makes exactly one draft call and no append call; `publish()` refuses when a check failed; `gmail_send_email` is never called. No test calls the real server or sends anything.
10. Write `tests/test_no_google_sdk.py`: fail if `googleapiclient` or `google.oauth2` is imported anywhere under `src/`, or if the string `gmail_send_email` appears there.

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

- [ ] Before the first push: `git status` does not list `.env` or `.streamlit/secrets.toml`, and `git grep -n "$(printf 'gsk\137')"` prints nothing.
- [ ] Search every committed snapshot for `userName`, `userImage`, `reviewId` and `http`. Nothing is found.
- [ ] The app is deployed as **public**, with no viewer allow-list or password gate. The deployment runbook records that any visitor can invoke the secret-backed Publish action after validation.
- [ ] Python 3.12 is selected in Advanced settings. Secrets hold exactly `GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_AUTH_TOKEN`, `PULSE_DOC_ID` and `PULSE_RECIPIENT`.
- [ ] On the live URL: pick the committed snapshot and generate a preview. The first run is slow (embedding model download); later runs are faster.
- [ ] The live preview matches a local preview of the same snapshot: same `k`, same theme sizes, same quotes.
- [ ] Publish from the live app. The Doc updates and a Gmail draft appears. Nothing is sent.
- [ ] Uploading a snapshot file in the live app works.

### Tasks

1. Rehearse in a clean Python 3.12 venv with only `requirements.txt`. Run `pytest -q` and a full preview. Fix the pins locally, not on the server.
2. Write `README.md` and `docs/deployment-plan.md`.
3. `git init`, confirm no secrets are staged, commit, and push to a new GitHub repo.
4. Create the Streamlit app: repo, `main` branch, `app.py`, Python 3.12, the five secrets (`GROQ_API_KEY`, `MCP_SERVER_URL`, `MCP_AUTH_TOKEN`, `PULSE_DOC_ID`, `PULSE_RECIPIENT`), public visibility, and no password gate.
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

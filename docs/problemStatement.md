# Problem Statement: Groww Weekly Review Pulse

## Goal

Turn raw Google Play Store reviews for the Groww app into a weekly pulse a team can scan in minutes. The pulse says what users care about, what they actually said, and what to do next.

Reviews are public. The agent aggregates them, groups them into themes, summarises them, and delivers the result through Google Docs (the written pulse) and Gmail (a draft email). Google Docs and Gmail are reached through an MCP server. No direct Google API code in the agent.

Play Store link: [com.nextbillion.groww](https://play.google.com/store/apps/details?id=com.nextbillion.groww&hl=en_IN)

## Scope

- Source: Google Play Store reviews only. The App Store is out of scope for now.
- Window: reviews from roughly the last 8 to 12 weeks.
- Fields: rating, title, text, date, whatever the export provides.

## End-to-end flow

1. Pull recent Play Store reviews.
2. Cluster them into at most 5 themes.
3. Write a one-page weekly note.
4. Put the note in a Google Doc.
5. Create a Gmail draft to myself or an alias containing the note or a link to it.

## Deliverable: weekly one-page pulse

- Top 3 themes
- 3 real user quotes, verbatim, no invented wording
- 3 action ideas grounded in the themes
- 250 words or fewer

## Who it helps

- Product and Growth: prioritise fixes from real signals.
- Support: align messaging with what users say.
- Leadership: one-page health check without raw reviews.

## Constraints

- Public review exports only. No scraping behind logins. No ToS-violating automation.
- Maximum 5 themes for clustering. The note highlights the top 3.
- Note is scannable and 250 words or fewer.
- No PII in any artifact. No usernames, emails, device IDs or other reviewer identity. Quotes are anonymous.
- Docs and Gmail go through MCP tools. MCP first, not manual Google API calls.

## Review filtering

- Keep only reviews with more than 8 words.
- Remove emoji reviews.
- Remove non-English reviews.

## Out of scope for now

- App Store reviews.
- Auto-sending email. The output is a draft.

## Deployment

Same process as the Zomato and RAG projects.

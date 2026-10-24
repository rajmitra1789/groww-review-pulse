"""Label each cluster and rank themes for the note."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from pulse.config import MIN_COMPLAINT_SHARE
from pulse.llm import call_json
from pulse.models import Cluster, Review, Theme

NAME_MAX_WORDS = 4
SUMMARY_MAX_WORDS = 20
TOP_THEMES = 3

LABEL_SYSTEM = (
    "You label one theme of app reviews. Return JSON only. "
    "The name has at most 4 words. The summary has at most 20 words. "
    "Do not invent numbers."
)
LABEL_SCHEMA = '{"name": "at most 4 words", "summary": "at most 20 words"}'


def rank_clusters(clusters: Sequence[Cluster | Theme]) -> tuple[Cluster | Theme, ...]:
    """Largest review count first. Complaint share breaks ties, highest first."""
    return tuple(sorted(clusters, key=_rank_key))


def pick_top_themes(
    clusters: Sequence[Cluster | Theme],
    min_complaint_share: float = MIN_COMPLAINT_SHARE,
    limit: int = TOP_THEMES,
) -> tuple[Cluster | Theme, ...]:
    """Pick the top themes, skipping clusters below the complaint-share cutoff.

    Clusters at or above the cutoff keep rank order. If fewer than ``limit``
    pass, the empty slots are filled from the skipped clusters, largest first.
    """
    ranked = rank_clusters(clusters)
    eligible = [cluster for cluster in ranked if cluster.complaint_share >= min_complaint_share]
    skipped = [cluster for cluster in ranked if cluster.complaint_share < min_complaint_share]
    chosen = list(eligible[:limit])
    if len(chosen) < limit:
        chosen.extend(skipped[: limit - len(chosen)])
    return tuple(chosen)


def label_cluster(texts: Sequence[str], *, client=None) -> tuple[str, str]:
    """Name one cluster from its representative texts. Returns ``(name, summary)``."""
    payload = call_json(LABEL_SYSTEM, "\n\n".join(texts), LABEL_SCHEMA, client=client)
    name = payload.get("name")
    summary = payload.get("summary")
    if not isinstance(name, str) or not isinstance(summary, str):
        raise ValueError("theme label needs name and summary strings")
    name = _clamp_words(name, NAME_MAX_WORDS)
    summary = _clamp_words(summary, SUMMARY_MAX_WORDS)
    if not name or not summary:
        raise ValueError("theme label is empty")
    return name, summary


def label_themes(
    clusters: Sequence[Cluster],
    reviews: Sequence[Review],
    *,
    client=None,
) -> tuple[Theme, ...]:
    """One label call per cluster. Ratings are not sent."""
    by_id = {review.id: review for review in reviews}
    themes: list[Theme] = []
    for cluster in clusters:
        texts = [_representative_text(by_id, review_id) for review_id in cluster.representative_ids]
        name, summary = label_cluster(texts, client=client)
        themes.append(Theme.from_cluster(cluster, name, summary))
    return tuple(themes)


def _representative_text(reviews_by_id: Mapping[str, Review], review_id: str) -> str:
    return reviews_by_id[review_id].text


def _rank_key(cluster: Cluster | Theme) -> tuple[int, float, int]:
    cluster_id = cluster.cluster_id if isinstance(cluster, Theme) else cluster.id
    return (-cluster.size, -cluster.complaint_share, cluster_id)


def _clamp_words(text: str, limit: int) -> str:
    return " ".join(text.split()[:limit]).strip()

from __future__ import annotations

from datetime import date

import numpy as np

from pulse.cluster import choose_k, cluster_reviews
from pulse.config import N_CLUSTERS
from pulse.models import Review

_TOPICS = (
    "The brokerage charges on every trade are far too high for small orders",
    "Customer support never answers the ticket and the chat keeps dropping calls",
    "The charts freeze and the indicators lag whenever the market opens each day",
    "Withdrawals take three days and the payout stays pending after I sell shares",
    "The latest update ruined the UI layout and the new interface is confusing",
)


def _review(text: str, review_id: str, rating: int = 3) -> Review:
    return Review(
        id=review_id,
        rating=rating,
        title=None,
        text=text,
        date=date(2026, 10, 1),
        app_version=None,
        thumbs_up=0,
    )


def _hex_id(index: int) -> str:
    return f"{index:012x}"


def _fixture() -> list[Review]:
    reviews: list[Review] = []
    index = 0
    for topic in _TOPICS:
        for _copy in range(6):
            reviews.append(_review(topic, _hex_id(index), rating=1 + (index % 5)))
            index += 1
    reviews.append(
        _review(
            "app bahut slow hai paisa nahi nikal raha please fix this now",
            _hex_id(index),
        )
    )
    index += 1
    reviews.append(_review("very easy to use, love it", _hex_id(index), rating=5))
    return reviews


def _embed(texts: list[str]) -> np.ndarray:
    vectors = np.zeros((len(texts), 8), dtype=np.float32)
    for row, text in enumerate(texts):
        lowered = text.lower()
        if "brokerage" in lowered or "charge" in lowered:
            vectors[row, 0] = 1.0
        if "support" in lowered or "ticket" in lowered:
            vectors[row, 1] = 1.0
        if "chart" in lowered or "indicator" in lowered:
            vectors[row, 2] = 1.0
        if "withdraw" in lowered or "payout" in lowered:
            vectors[row, 3] = 1.0
        if "update" in lowered or "interface" in lowered or "layout" in lowered:
            vectors[row, 4] = 1.0
        vectors[row, 5] = (sum(map(ord, lowered)) % 7) / 7.0
    return vectors


def test_same_input_gives_same_clusters() -> None:
    reviews = [review for review in _fixture() if "bahut" not in review.text and "love it" not in review.text]
    first = cluster_reviews(reviews, kept_count=len(_fixture()), embed_fn=_embed, min_clusterable=10)
    second = cluster_reviews(reviews, kept_count=len(_fixture()), embed_fn=_embed, min_clusterable=10)
    assert [cluster.member_ids for cluster in first.clusters] == [
        cluster.member_ids for cluster in second.clusters
    ]
    assert [cluster.representative_ids for cluster in first.clusters] == [
        cluster.representative_ids for cluster in second.clusters
    ]


def test_never_more_than_five_clusters() -> None:
    reviews = [review for review in _fixture() if "bahut" not in review.text and "love it" not in review.text]
    result = cluster_reviews(reviews, kept_count=40, embed_fn=_embed, min_clusterable=10)
    assert len(result.clusters) <= N_CLUSTERS
    assert result.k <= N_CLUSTERS
    assert choose_k(400) == 5
    assert choose_k(20) == 3


def test_noise_and_generic_praise_are_not_cluster_members(tmp_path) -> None:
    from pulse.buckets import split_buckets

    reviews = _fixture()
    buckets = split_buckets(reviews)
    excluded = {review.id for review in buckets.noise + buckets.generic_praise}
    assert excluded
    result = cluster_reviews(
        list(buckets.clusterable),
        kept_count=len(reviews),
        cache_path=tmp_path / "embeddings.npy",
        embed_fn=_embed,
        min_clusterable=10,
    )
    members = {review_id for cluster in result.clusters for review_id in cluster.member_ids}
    reps = {review_id for cluster in result.clusters for review_id in cluster.representative_ids}
    assert members.isdisjoint(excluded)
    assert reps.isdisjoint(excluded)
    assert members == {review.id for review in buckets.clusterable}


def test_changing_only_ratings_does_not_change_clusters() -> None:
    reviews = [review for review in _fixture() if "bahut" not in review.text and "love it" not in review.text]
    flipped = [
        Review(
            id=review.id,
            rating=1 if review.rating >= 4 else 5,
            title=review.title,
            text=review.text,
            date=review.date,
            app_version=review.app_version,
            thumbs_up=review.thumbs_up,
        )
        for review in reviews
    ]
    original = cluster_reviews(reviews, kept_count=len(reviews), embed_fn=_embed, min_clusterable=10)
    changed = cluster_reviews(flipped, kept_count=len(flipped), embed_fn=_embed, min_clusterable=10)
    assert [cluster.member_ids for cluster in original.clusters] == [
        cluster.member_ids for cluster in changed.clusters
    ]
    assert [cluster.representative_ids for cluster in original.clusters] == [
        cluster.representative_ids for cluster in changed.clusters
    ]

"""Embed clusterable reviews, drop mood, and fit a fixed-k KMeans model."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score

from pulse.buckets import has_complaint_word, has_praise_word, topic_hits
from pulse.config import (
    EMBEDDING_MODEL,
    KMEANS_N_INIT,
    MIN_CLUSTERABLE,
    N_CLUSTERS,
    RANDOM_STATE,
    REPS_PER_THEME,
)
from pulse.models import Cluster, Review

EmbedFn = Callable[[list[str]], np.ndarray]

_embedder = None


@dataclass(frozen=True)
class ClusterResult:
    clusters: tuple[Cluster, ...]
    k: int
    silhouette: float | None
    model: str
    cache_hit: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "k": self.k,
            "silhouette": self.silhouette,
            "model": self.model,
            "clusterable": sum(cluster.size for cluster in self.clusters),
            "clusters": [cluster.to_dict() for cluster in self.clusters],
        }


def cluster_reviews(
    reviews: list[Review],
    kept_count: int,
    cache_path: Path | None = None,
    embed_fn: EmbedFn | None = None,
    model_name: str = EMBEDDING_MODEL,
    n_clusters: int = N_CLUSTERS,
    min_clusterable: int = MIN_CLUSTERABLE,
    random_state: int = RANDOM_STATE,
    n_init: int = KMEANS_N_INIT,
    reps_per_theme: int = REPS_PER_THEME,
) -> ClusterResult:
    if not reviews:
        return ClusterResult(
            clusters=(),
            k=0,
            silhouette=None,
            model=model_name,
            cache_hit=True,
        )

    vectors, cache_hit = embed_reviews(reviews, cache_path, embed_fn, model_name)
    vectors = remove_polarity_direction(vectors, reviews)
    k = choose_k(len(reviews), n_clusters=n_clusters, min_clusterable=min_clusterable)
    labels, centroids, silhouette = fit_kmeans(
        vectors, k=k, random_state=random_state, n_init=n_init
    )
    clusters = build_clusters(
        reviews,
        vectors,
        labels,
        centroids,
        kept_count=kept_count,
        reps_per_theme=reps_per_theme,
    )
    return ClusterResult(
        clusters=clusters,
        k=k,
        silhouette=silhouette,
        model=model_name,
        cache_hit=cache_hit,
    )


def choose_k(
    n_reviews: int,
    n_clusters: int = N_CLUSTERS,
    min_clusterable: int = MIN_CLUSTERABLE,
) -> int:
    if n_reviews <= 0:
        return 0
    k = n_clusters if n_reviews >= min_clusterable else min(3, n_clusters)
    return max(1, min(k, n_reviews, n_clusters))


def embed_reviews(
    reviews: list[Review],
    cache_path: Path | None = None,
    embed_fn: EmbedFn | None = None,
    model_name: str = EMBEDDING_MODEL,
) -> tuple[np.ndarray, bool]:
    cached_model, cached = _load_cache(cache_path)
    cache_usable = cached_model == model_name
    vectors = np.zeros((len(reviews), 0), dtype=np.float32)
    missing_indexes: list[int] = []
    missing_texts: list[str] = []

    if cache_usable and cached:
        dim = next(iter(cached.values())).shape[0]
        vectors = np.zeros((len(reviews), dim), dtype=np.float32)
        for index, review in enumerate(reviews):
            vector = cached.get(review.id)
            if vector is None:
                missing_indexes.append(index)
                missing_texts.append(review.text)
            else:
                vectors[index] = vector
    else:
        missing_indexes = list(range(len(reviews)))
        missing_texts = [review.text for review in reviews]

    cache_hit = cache_usable and not missing_indexes
    if missing_indexes:
        fresh = _l2_normalize(_call_embedder(missing_texts, embed_fn, model_name))
        if vectors.shape[1] == 0:
            vectors = np.zeros((len(reviews), fresh.shape[1]), dtype=np.float32)
        for index, vector in zip(missing_indexes, fresh, strict=True):
            vectors[index] = vector
        if cache_path is not None:
            merged = dict(cached) if cache_usable else {}
            for review, vector in zip(reviews, vectors, strict=True):
                merged[review.id] = vector
            _save_cache(cache_path, model_name, merged)

    return _l2_normalize(vectors), cache_hit


def polarity_vectors_by_id(
    reviews: list[Review],
    cache_path: Path | None = None,
    embed_fn: EmbedFn | None = None,
    model_name: str = EMBEDDING_MODEL,
) -> dict[str, np.ndarray]:
    """Embeddings in the same space as cluster centroids (mood direction removed)."""
    vectors, _ = embed_reviews(reviews, cache_path, embed_fn, model_name)
    vectors = remove_polarity_direction(vectors, reviews)
    return {review.id: vectors[index] for index, review in enumerate(reviews)}


def remove_polarity_direction(vectors: np.ndarray, reviews: list[Review]) -> np.ndarray:
    complaint_indexes = [
        index for index, review in enumerate(reviews) if has_complaint_word(review.text)
    ]
    praise_only_indexes = [
        index
        for index, review in enumerate(reviews)
        if has_praise_word(review.text) and not has_complaint_word(review.text)
    ]
    if not complaint_indexes or not praise_only_indexes:
        return _l2_normalize(vectors)

    direction = vectors[complaint_indexes].mean(axis=0) - vectors[praise_only_indexes].mean(
        axis=0
    )
    norm = float(np.linalg.norm(direction))
    if norm < 1e-8:
        return _l2_normalize(vectors)
    direction = direction / norm
    projected = vectors - np.outer(vectors @ direction, direction)
    return _l2_normalize(projected)


def fit_kmeans(
    vectors: np.ndarray,
    k: int,
    random_state: int = RANDOM_STATE,
    n_init: int = KMEANS_N_INIT,
) -> tuple[np.ndarray, np.ndarray, float | None]:
    if k <= 1 or len(vectors) <= 1:
        centroid = vectors.mean(axis=0) if len(vectors) else np.zeros(0, dtype=np.float32)
        labels = np.zeros(len(vectors), dtype=np.int32)
        return labels, centroid.reshape(1, -1), None

    model = KMeans(n_clusters=k, random_state=random_state, n_init=n_init)
    labels = model.fit_predict(vectors)
    silhouette = None
    if k > 1 and len(vectors) > k:
        silhouette = float(silhouette_score(vectors, labels))
    return labels, model.cluster_centers_, silhouette


def build_clusters(
    reviews: list[Review],
    vectors: np.ndarray,
    labels: np.ndarray,
    centroids: np.ndarray,
    kept_count: int,
    reps_per_theme: int = REPS_PER_THEME,
) -> tuple[Cluster, ...]:
    grouped: dict[int, list[int]] = defaultdict(list)
    for index, label in enumerate(labels):
        grouped[int(label)].append(index)

    clusterable_count = len(reviews)
    clusters: list[Cluster] = []
    for label in sorted(grouped):
        member_indexes = grouped[label]
        centroid = centroids[label]
        member_vectors = vectors[member_indexes]
        distances = np.linalg.norm(member_vectors - centroid, axis=1)
        ranked = sorted(
            zip(distances, member_indexes, strict=True),
            key=lambda item: (float(item[0]), reviews[item[1]].id),
        )
        rep_indexes = [index for _, index in ranked[:reps_per_theme]]
        members = [reviews[index] for index in member_indexes]
        topic_counts = Counter(
            hit for review in members for hit in topic_hits(review.text)
        )
        complaint_share = _mean(
            has_complaint_word(review.text) for review in members
        )
        one_two_star_share = _mean(review.rating <= 2 for review in members)
        average_rating = _mean(review.rating for review in members)
        size = len(members)
        clusters.append(
            Cluster(
                id=label,
                member_ids=tuple(review.id for review in members),
                centroid=tuple(float(value) for value in centroid),
                size=size,
                share_of_clusterable=_share(size, clusterable_count),
                share_of_kept=_share(size, kept_count),
                complaint_share=complaint_share,
                top_topic_words=tuple(word for word, _ in topic_counts.most_common(3)),
                representative_ids=tuple(reviews[index].id for index in rep_indexes),
                average_rating=average_rating,
                one_two_star_share=one_two_star_share,
            )
        )
    return tuple(clusters)


def _call_embedder(texts: list[str], embed_fn: EmbedFn | None, model_name: str) -> np.ndarray:
    if not texts:
        return np.zeros((0, 0), dtype=np.float32)
    if embed_fn is not None:
        return np.asarray(embed_fn(texts), dtype=np.float32)
    model = _get_embedder(model_name)
    return np.asarray(list(model.embed(texts)), dtype=np.float32)


def _get_embedder(model_name: str):
    global _embedder
    if _embedder is None or getattr(_embedder, "model_name", model_name) != model_name:
        from fastembed import TextEmbedding

        _embedder = TextEmbedding(model_name=model_name)
    return _embedder


def _load_cache(path: Path | None) -> tuple[str | None, dict[str, np.ndarray]]:
    if path is None or not path.exists():
        return None, {}
    try:
        payload = np.load(path, allow_pickle=True).item()
    except (OSError, ValueError, AttributeError, EOFError):
        return None, {}
    if not isinstance(payload, dict) or "model" not in payload or "ids" not in payload:
        return None, {}
    ids = [str(review_id) for review_id in payload["ids"]]
    vectors = np.asarray(payload["vectors"], dtype=np.float32)
    if len(ids) != len(vectors):
        return None, {}
    return str(payload["model"]), {review_id: vector for review_id, vector in zip(ids, vectors)}


def _save_cache(path: Path, model_name: str, vectors_by_id: dict[str, np.ndarray]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ids = list(vectors_by_id)
    vectors = np.stack([vectors_by_id[review_id] for review_id in ids]).astype(np.float32)
    np.save(path, {"model": model_name, "ids": np.array(ids, dtype=object), "vectors": vectors})


def _l2_normalize(vectors: np.ndarray) -> np.ndarray:
    if vectors.size == 0:
        return vectors.astype(np.float32, copy=False)
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    norms = np.where(norms == 0, 1.0, norms)
    return (vectors / norms).astype(np.float32)


def _share(part: int, whole: int) -> float:
    if whole <= 0:
        return 0.0
    return part / whole


def _mean(values) -> float:
    items = list(values)
    if not items:
        return 0.0
    return float(sum(items) / len(items))

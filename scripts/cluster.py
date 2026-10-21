"""Split kept reviews into buckets and cluster the clusterable group."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from pulse.buckets import split_buckets  # noqa: E402
from pulse.cluster import cluster_reviews  # noqa: E402
from pulse.snapshot import load_snapshot  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Bucket and cluster a normalized run.")
    parser.add_argument("--run", required=True, type=Path, help="Run folder with reviews.jsonl")
    args = parser.parse_args()

    run_dir = args.run
    reviews_path = run_dir / "reviews.jsonl"
    reviews = load_snapshot(reviews_path)
    buckets = split_buckets(reviews)
    summary = buckets.summary()
    result = cluster_reviews(
        list(buckets.clusterable),
        kept_count=summary.kept_count,
        cache_path=run_dir / "embeddings.npy",
    )

    buckets_path = run_dir / "buckets.json"
    clusters_path = run_dir / "clusters.json"
    payload = result.to_dict()
    payload["kept"] = summary.kept_count
    buckets_path.write_text(json.dumps(summary.to_dict(), indent=2) + "\n", encoding="utf-8")
    clusters_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    reasons = summary.noise_reason_counts
    print(f"kept {summary.kept_count}")
    print(
        "noise "
        f"{summary.noise_count} (non_latin {reasons.get('non_latin', 0)}, "
        f"gibberish {reasons.get('gibberish', 0)}, "
        f"hinglish {reasons.get('hinglish', 0)})"
    )
    share = (
        100.0 * summary.generic_praise_count / summary.kept_count if summary.kept_count else 0.0
    )
    print(f"generic praise {summary.generic_praise_count} ({share:.1f}% of kept)")
    print(f"clusterable {summary.clusterable_count}")
    if summary.noise_topic_words:
        top_noise_topics = ", ".join(
            f"{word} {count}" for word, count in list(summary.noise_topic_words.items())[:8]
        )
        print(f"noise topic words {top_noise_topics}")
    silhouette = "n/a" if result.silhouette is None else f"{result.silhouette:.3f}"
    cache = "reused embeddings.npy" if result.cache_hit else "wrote embeddings.npy"
    print(f"k {result.k} silhouette {silhouette} {cache}")

    reviews_by_id = {review.id: review for review in buckets.clusterable}
    for cluster in result.clusters:
        topics = ", ".join(cluster.top_topic_words) or "-"
        print(
            f"cluster {cluster.id} size {cluster.size} "
            f"share_clusterable {cluster.share_of_clusterable:.1%} "
            f"share_kept {cluster.share_of_kept:.1%} "
            f"complaint {cluster.complaint_share:.1%} "
            f"topics {topics} "
            f"avg_rating {cluster.average_rating:.2f} "
            f"1-2star {cluster.one_two_star_share:.1%}"
        )
        print("  representative ids " + ", ".join(cluster.representative_ids))
        for review_id in cluster.representative_ids:
            review = reviews_by_id[review_id]
            print(f"  - {review_id} ({review.rating}★) {review.text}")

    print(f"wrote {buckets_path}")
    print(f"wrote {clusters_path}")
    print(f"wrote {run_dir / 'embeddings.npy'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

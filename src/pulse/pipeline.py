"""End-to-end pulse: filter, cluster, label, compose, assemble, validate."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import date, datetime, timezone
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

from pulse.buckets import split_buckets
from pulse.cluster import cluster_reviews, polarity_vectors_by_id
from pulse.config import (
    MIN_REVIEWS_FOR_PULSE,
    RUNS_DIR,
    WINDOW_WEEKS,
)
from pulse.filters import Funnel, apply_filters, last_full_sunday, window_bounds, word_count
from pulse.models import (
    Cluster,
    ComposeResult,
    Failure,
    PublishResult,
    PulseResult,
    Review,
    Theme,
)
from pulse.note import (
    allowed_numbers,
    assemble,
    build_quote_pool,
    checks_from_failures,
    compose,
    validate,
)
from pulse.snapshot import load_snapshot, write_snapshot
from pulse.themes import label_themes, pick_top_themes


class PulseStop(RuntimeError):
    """The run stopped before a note could be assembled."""


def run_pulse(
    snapshot: Path | str | None,
    week_ending: date | None = None,
    window_weeks: int = WINDOW_WEEKS,
    *,
    run_dir: Path | None = None,
    client=None,
    embed_fn=None,
    reuse_run: bool = False,
) -> PulseResult:
    """Run phases 2 to 5. On failed checks, retry compose once, then stop."""
    ending = week_ending or last_full_sunday()
    dest = Path(run_dir) if run_dir is not None else RUNS_DIR / ending.isoformat()
    dest.mkdir(parents=True, exist_ok=True)
    start, _ = window_bounds(ending, window_weeks)

    if reuse_run:
        reviews, funnel, clusters, k, silhouette = _load_run(dest)
        buckets = split_buckets(reviews)
        cache_hit_dir = dest
    else:
        if snapshot is None:
            raise PulseStop("a snapshot path is required")
        raw = load_snapshot(snapshot)
        reviews, funnel = apply_filters(raw, week_ending=ending, window_weeks=window_weeks)
        write_snapshot(dest / "reviews.jsonl", reviews)
        _write_json(dest / "funnel.json", funnel.to_dict())
        if len(reviews) < MIN_REVIEWS_FOR_PULSE:
            return _stopped(
                "not enough reviews for a pulse",
                ending,
                window_weeks,
                start,
                reviews,
                funnel,
                dest,
            )
        buckets = split_buckets(reviews)
        clustered = cluster_reviews(
            list(buckets.clusterable),
            kept_count=len(reviews),
            cache_path=dest / "embeddings.npy",
            embed_fn=embed_fn,
        )
        clusters = clustered.clusters
        k = clustered.k
        silhouette = clustered.silhouette
        cache_hit_dir = dest
        _write_json(dest / "clusters.json", clustered.to_dict())
        _write_json(dest / "buckets.json", buckets.summary().to_dict())

    if len(reviews) < MIN_REVIEWS_FOR_PULSE:
        return _stopped(
            "not enough reviews for a pulse",
            ending,
            window_weeks,
            start,
            reviews,
            funnel,
            dest,
            buckets=buckets.summary(),
        )

    themes = label_themes(clusters, reviews, client=client)
    top = tuple(pick_top_themes(themes))
    vectors = polarity_vectors_by_id(
        list(buckets.clusterable),
        cache_path=cache_hit_dir / "embeddings.npy",
        embed_fn=embed_fn,
    )
    pool = build_quote_pool(top, reviews, vectors)
    themed_quotes = {candidate.theme for candidate in pool}
    if sum(1 for theme in top if theme.name in themed_quotes) < 3:
        _write_themes(dest, themes, top, k, silhouette, ending)
        return _stopped(
            "fewer than 3 themes have a quote candidate",
            ending,
            window_weeks,
            start,
            reviews,
            funnel,
            dest,
            buckets=buckets.summary(),
            themes=themes,
            top_themes=top,
            k=k,
            silhouette=silhouette,
        )

    composed, failures, note, allowed = _compose_and_validate(
        top, pool, reviews, ending, window_weeks, client=client
    )
    result = _build_result(
        ending=ending,
        window_weeks=window_weeks,
        start=start,
        note=note,
        failures=failures,
        funnel=funnel,
        buckets=buckets.summary(),
        themes=themes,
        top=top,
        compose=composed,
        reviews=reviews,
        dest=dest,
        k=k,
        silhouette=silhouette,
        allowed=allowed,
    )
    _write_artifacts(result)
    return replace(result, zip_path=_zip_run(dest))


def _compose_and_validate(
    top: tuple[Theme, ...],
    pool,
    reviews: list[Review],
    ending: date,
    window_weeks: int,
    *,
    client=None,
) -> tuple[ComposeResult, tuple[Failure, ...], str, tuple[str, ...]]:
    composed = compose(top, pool, client=client)
    note, allowed, failures = _assemble_once(top, composed, reviews, ending, window_weeks)
    if failures:
        composed = compose(top, pool, client=client, failures=failures)
        note, allowed, failures = _assemble_once(top, composed, reviews, ending, window_weeks)
    return composed, tuple(failures), note, allowed


def _assemble_once(
    top: tuple[Theme, ...],
    composed: ComposeResult,
    reviews: list[Review],
    ending: date,
    window_weeks: int,
) -> tuple[str, tuple[str, ...], list[Failure]]:
    note = assemble(
        top,
        composed,
        reviews,
        week_ending=ending,
        window_weeks=window_weeks,
    )
    allowed = allowed_numbers(
        note_week_ending=ending,
        window_weeks=window_weeks,
        reviews=reviews,
        themes=top,
        compose=composed,
    )
    draft = PulseResult(
        week_ending=ending,
        window_weeks=window_weeks,
        window_start=window_bounds(ending, window_weeks)[0],
        note=note,
        word_count=word_count(note),
        failures=(),
        checks=(),
        funnel=None,
        buckets=None,
        themes=top,
        top_themes=top,
        compose=composed,
        reviews=tuple(reviews),
        run_dir=Path(),
        zip_path=None,
        k=0,
        silhouette=None,
        allowed_numbers=tuple(sorted(allowed)),
    )
    return note, tuple(sorted(allowed)), validate(note, draft)


def _build_result(
    *,
    ending: date,
    window_weeks: int,
    start: date,
    note: str,
    failures: tuple[Failure, ...],
    funnel,
    buckets,
    themes: tuple[Theme, ...],
    top: tuple[Theme, ...],
    compose: ComposeResult | None,
    reviews: list[Review],
    dest: Path,
    k: int,
    silhouette: float | None,
    allowed: tuple[str, ...],
    stop_reason: str = "",
) -> PulseResult:
    return PulseResult(
        week_ending=ending,
        window_weeks=window_weeks,
        window_start=start,
        note=note,
        word_count=word_count(note) if note else 0,
        failures=failures,
        checks=checks_from_failures(failures),
        funnel=funnel,
        buckets=buckets,
        themes=themes,
        top_themes=top,
        compose=compose,
        reviews=tuple(reviews),
        run_dir=dest,
        zip_path=None,
        k=k,
        silhouette=silhouette,
        allowed_numbers=allowed,
        stop_reason=stop_reason,
    )


def _stopped(
    message: str,
    ending: date,
    window_weeks: int,
    start: date,
    reviews: list[Review],
    funnel,
    dest: Path,
    *,
    buckets=None,
    themes: tuple[Theme, ...] = (),
    top_themes: tuple[Theme, ...] = (),
    k: int = 0,
    silhouette: float | None = None,
) -> PulseResult:
    result = _build_result(
        ending=ending,
        window_weeks=window_weeks,
        start=start,
        note="",
        failures=(),
        funnel=funnel,
        buckets=buckets,
        themes=themes,
        top=top_themes,
        compose=None,
        reviews=reviews,
        dest=dest,
        k=k,
        silhouette=silhouette,
        allowed=(),
        stop_reason=message,
    )
    _write_json(dest / "funnel.json", funnel.to_dict())
    write_snapshot(dest / "reviews.jsonl", reviews)
    _write_json(
        dest / "checks.json",
        {"word_count": 0, "passed": False, "stop_reason": message, "checks": []},
    )
    return replace(result, zip_path=_zip_run(dest))


def _load_run(run_dir: Path) -> tuple[list[Review], Funnel, tuple[Cluster, ...], int, float | None]:
    reviews = load_snapshot(run_dir / "reviews.jsonl")
    funnel = Funnel.from_dict(json.loads((run_dir / "funnel.json").read_text(encoding="utf-8")))
    payload = json.loads((run_dir / "clusters.json").read_text(encoding="utf-8"))
    clusters = tuple(Cluster.from_dict(row) for row in payload["clusters"])
    silhouette = payload.get("silhouette")
    return reviews, funnel, clusters, int(payload.get("k") or len(clusters)), silhouette


def _write_artifacts(result: PulseResult) -> None:
    dest = result.run_dir
    write_snapshot(dest / "reviews.jsonl", list(result.reviews))
    if result.funnel is not None:
        _write_json(dest / "funnel.json", result.funnel.to_dict())
    _write_themes(
        dest,
        result.themes,
        result.top_themes,
        result.k,
        result.silhouette,
        result.week_ending,
    )
    (dest / "note.md").write_text(result.note, encoding="utf-8")
    _write_json(
        dest / "checks.json",
        {
            "word_count": result.word_count,
            "passed": result.passed,
            "stop_reason": result.stop_reason,
            "checks": [item.to_dict() for item in result.checks],
        },
    )


def load_publish_result(run_dir: Path) -> PublishResult | None:
    path = Path(run_dir) / "publish.json"
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return PublishResult.from_dict(payload)
    except (OSError, ValueError, TypeError, KeyError):
        return None


def record_publish_result(
    pulse: PulseResult, delivery: PublishResult
) -> PublishResult:
    """Persist the latest delivery state without losing a prior Doc append."""
    previous = load_publish_result(pulse.run_dir)
    merged = PublishResult(
        doc_link=delivery.doc_link or (previous.doc_link if previous else ""),
        doc_appended=delivery.doc_appended or bool(previous and previous.doc_appended),
        characters_appended=(
            delivery.characters_appended
            if delivery.characters_appended is not None
            else previous.characters_appended if previous else None
        ),
        draft_id=delivery.draft_id,
        error_code=delivery.error_code,
        error_message=delivery.error_message,
        failed_step=delivery.failed_step,
    )
    payload = merged.to_dict()
    payload["weekEnding"] = pulse.week_ending.isoformat()
    payload["updatedAt"] = datetime.now(timezone.utc).isoformat()
    _write_json(pulse.run_dir / "publish.json", payload)
    _zip_run(pulse.run_dir)
    return merged


def _write_themes(
    dest: Path,
    themes: tuple[Theme, ...],
    top: tuple[Theme, ...],
    k: int,
    silhouette: float | None,
    week_ending: date,
) -> None:
    rows = []
    for theme in themes:
        row = theme.to_dict()
        row.pop("centroid", None)
        row.pop("member_ids", None)
        rows.append(row)
    _write_json(
        dest / "themes.json",
        {
            "week_ending": week_ending.isoformat(),
            "k": k,
            "silhouette": silhouette,
            "top_cluster_ids": [theme.cluster_id for theme in top],
            "themes": rows,
        },
    )


def _zip_run(run_dir: Path) -> Path:
    zip_path = run_dir / "run.zip"
    with ZipFile(zip_path, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(run_dir.iterdir()):
            if path.name == "run.zip" or path.suffix == ".zip":
                continue
            archive.write(path, path.name)
    return zip_path


def _write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

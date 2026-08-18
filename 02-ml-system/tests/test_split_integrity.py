"""Split independence.

Leakage is the failure mode that makes a broken system look excellent, so
disjointness is asserted on identifiers, not assumed from the splitting code.
"""

from __future__ import annotations

import csv

from lab1.config import TEST_LABELS_FILE
from lab1.dataset import generate_source, stratified_split


def test_ids_are_pairwise_disjoint(cfg):
    splits = stratified_split(cfg, generate_source(cfg))
    train = set(splits["train"].ids.tolist())
    validation = set(splits["validation"].ids.tolist())
    test = set(splits["test"].ids.tolist())

    assert not train & validation
    assert not train & test
    assert not validation & test


def test_splits_partition_the_source_exactly(cfg):
    source = generate_source(cfg)
    splits = stratified_split(cfg, source)
    union: set[int] = set()
    for split in splits.values():
        union |= set(split.ids.tolist())
    assert union == set(source[cfg.id_column].tolist())


def test_features_travel_with_their_own_label(cfg):
    source = generate_source(cfg)
    by_id = {
        int(observation_id): int(label)
        for observation_id, label in zip(source[cfg.id_column], source[cfg.label])
    }
    for split in stratified_split(cfg, source).values():
        for observation_id, label in zip(split.ids, split.labels):
            assert by_id[int(observation_id)] == int(label)


def test_test_labels_file_covers_exactly_the_test_split(cfg, data_dir):
    splits = stratified_split(cfg, generate_source(cfg))
    with (data_dir / TEST_LABELS_FILE).open(newline="", encoding="utf-8") as handle:
        rows = [row for row in csv.reader(handle) if row]
    assert rows[0] == [cfg.id_column, cfg.label]
    assert {int(r[0]) for r in rows[1:]} == set(splits["test"].ids.tolist())


def test_rows_are_written_in_id_order(cfg):
    """File layout must not depend on how the class buckets were concatenated."""
    for split in stratified_split(cfg, generate_source(cfg)).values():
        ids = split.ids.tolist()
        assert ids == sorted(ids), split.name

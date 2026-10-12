import pytest

from agent_hub.tree import (
    build_tree,
    clip_utf8,
    compact_excerpts,
    make_leaf,
    merge_nodes,
    node_id,
    select_frontier,
)


def events(count):
    return [{"sequence": i, "id": f"event-{i}", "text": f"Original {i} " + "文" * 300} for i in range(count)]


@pytest.mark.parametrize("count", [0, 1, 2, 3, 5, 13, 31, 32, 65, 127, 128, 129])
def test_frontiers_cover_every_event_once_including_non_power_two(count):
    nodes = build_tree("alpha", events(count))
    assert len(nodes) == 2 * count - count.bit_count()
    for target in [1, 3, 8, 32]:
        view = select_frontier(nodes, target)
        covered = [i for node in view for i in range(node["lo"], node["hi"] + 1)]
        assert covered == list(range(count))
        assert len(view) <= max(target, count.bit_count())
        assert len(view) <= count


def test_recent_ranges_are_refined_first():
    view = select_frontier(build_tree("alpha", events(64)), 7)
    assert view[0]["lo"] == 0
    assert view[0]["hi"] >= 31
    assert view[-1]["lo"] == view[-1]["hi"] == 63
    assert view[-2]["lo"] == view[-2]["hi"] == 62


def test_deterministic_ids_and_summaries_are_project_scoped():
    first = build_tree("alpha", events(17))
    assert first == build_tree("alpha", events(17))
    second = build_tree("beta", events(17))
    assert {node["id"] for node in first}.isdisjoint(node["id"] for node in second)
    assert node_id("alpha", 0, 3) == node_id("alpha", 0, 3)


def test_utf8_budgets_do_not_split_codepoints_or_overrun():
    for budget in range(0, 520):
        for result in (
            clip_utf8("文😊" * 400, budget),
            compact_excerpts(["猫" * 300, "😊" * 300], budget),
        ):
            assert len(result.encode("utf-8")) <= budget
            assert result.encode("utf-8").decode("utf-8") == result


def test_verbatim_means_original_text_has_not_been_compressed():
    left = make_leaf("p", 0, "exact\nraw text")
    right = make_leaf("p", 1, "other")
    parent = merge_nodes("p", left, right)
    assert parent["mode"] == "verbatim"
    assert parent["summary"] == "exact\nraw text\n\nother"
    long_leaf = make_leaf("p", 0, "A" * 700)
    assert long_leaf["mode"] == "extractive"
    assert not long_leaf["original_verbatim"]
    assert len(long_leaf["summary"].encode("utf-8")) <= 512


def test_rejects_gaps_and_invalid_merges():
    with pytest.raises(ValueError):
        build_tree("p", [{"sequence": 2, "text": "missing history"}])
    with pytest.raises(ValueError):
        merge_nodes("p", make_leaf("p", 1, "a"), make_leaf("p", 2, "b"))
    with pytest.raises(ValueError):
        select_frontier([make_leaf("p", 1, "gap")])
    with pytest.raises(ValueError):
        select_frontier([], 0)

from inspectors_notebook.cache import next_to_go, plan


def cases(*specs):
    """Newest first. Each spec is an id, optionally with flags: id:pinned,exported."""
    out = []
    for spec in specs:
        name, _, flags = spec.partition(":")
        out.append({"id": name, "pinned": "pinned" in flags, "exported": "exported" in flags})
    return out


def test_nothing_is_deleted_within_the_limit():
    assert plan(cases("a", "b", "c"), None, 5) == ([], [])
    assert next_to_go(cases("a", "b", "c"), None, 5) is None


def test_the_oldest_go_first_and_only_beyond_the_limit():  # FR-29, FR-30
    metas = cases("f:exported", "e:exported", "d:exported", "c:exported", "b:exported", "a:exported", "z:exported")
    assert plan(metas, "f", 5) == (["z", "a"], [])


def test_active_and_pinned_cases_are_never_deleted():  # FR-30, FR-31
    metas = cases("e", "d", "c", "b", "a:pinned,exported", "old:exported", "older:pinned")
    assert plan(metas, "old", 5) == ([], [])
    assert plan(cases("x", "y", "active:exported"), "active", 2) == ([], [])


def test_unexported_cases_need_confirmation():  # FR-32
    metas = cases("e", "d", "c", "b", "a", "old", "older:exported")
    assert plan(metas, None, 5) == (["older"], ["old"])
    assert plan(metas, None, 5, warn_unexported=False) == (["older", "old"], [])


def test_which_case_goes_next():
    five = cases("e", "d", "c", "b", "a:exported")
    assert next_to_go(five, "e", 5) == "a"
    assert next_to_go(cases("e", "d", "c", "b", "a:pinned"), "e", 5) is None
    assert next_to_go(cases("e", "d", "c", "b", "a:pinned", "z"), "e", 5) == "z"

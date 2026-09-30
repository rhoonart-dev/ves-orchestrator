from ves.scheduler.laeebly_sync import COLS, plan


def _row(i, **kw):
    r = {k: None for k in COLS}
    r.update(id=i, title=f"작품{i}", **kw)
    return r


def test_plan_writes_changed_and_deletes_missing():
    mirror = {"a": _row("a", company="티빙"), "b": _row("b"), "gone": _row("gone")}
    source = [_row("a", company="티빙"), _row("b", company="왓챠"), _row("c"), {"id": "", "title": "x"}]
    writes, deletes = plan(source, mirror)
    assert [w["id"] for w in writes] == ["b", "c"]
    assert deletes == ["gone"]


def test_plan_empty():
    assert plan([], {}) == ([], [])


def test_plan_other_table_without_title():
    from ves.scheduler.laeebly_sync import APP_COLS
    src = [{k: None for k in APP_COLS} | {"id": "x", "status": True}]
    writes, deletes = plan(src, {"old": {"id": "old"}}, APP_COLS)
    assert [w["id"] for w in writes] == ["x"] and deletes == ["old"]

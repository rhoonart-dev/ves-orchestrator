from ves.scheduler.drive_watch import active_works


def test_active_works_skips_paused_channels():
    chans = [{"token_slug": "A", "works": ["가왕쇼", "참교육"]},
             {"token_slug": "B", "works": ["참교육", "김부장"]},
             {"token_slug": "C", "works": ["혼자만"]}]
    live, any_live = active_works(chans, {"A", "C"})
    assert live == {"참교육", "김부장"} and any_live      # 참교육은 B 가 쉬지 않아 받는다
    live, any_live = active_works(chans, {"A", "B", "C"})
    assert live == set() and not any_live
    assert active_works(chans, set())[0] == {"가왕쇼", "참교육", "김부장", "혼자만"}
    assert active_works([], None) == (set(), False)

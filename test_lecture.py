"""Self-check for the non-audio logic. Run: python test_lecture.py"""
import datetime, json, tempfile
from pathlib import Path
from types import SimpleNamespace as S
import lecture

with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)
    lecture.NOTES_DIR = t / "Classes"; lecture.NOTES_DIR.mkdir()
    lecture.SCHEDULE = t / "schedule.json"
    (lecture.NOTES_DIR / "Classes Home.md").write_text("# Classes\n\n- [[A Home]] A\n\nFooter.\n", encoding="utf-8")

    # add_class: folders, Home note, link right after the existing list
    d = lecture.add_class("COMP 3500", "Networks")
    assert all((d / s).is_dir() for s in lecture.CLASS_SUBFOLDERS)
    home = d / "COMP 3500 Home.md"
    assert "# COMP 3500 Networks" in home.read_text(encoding="utf-8")
    assert "- [[A Home]] A\n- [[COMP 3500 Home]] Networks\n\nFooter." in (lecture.NOTES_DIR / "Classes Home.md").read_text(encoding="utf-8")
    try:
        lecture.add_class("COMP 3500", "Networks"); raise AssertionError("duplicate allowed")
    except ValueError:
        pass
    assert lecture.list_classes() == ["COMP 3500 Networks"]
    assert lecture.find_class("3500") == d

    # works without a Classes Home.md too
    (lecture.NOTES_DIR / "Classes Home.md").unlink()
    lecture.add_class("", "Biology")
    assert (lecture.NOTES_DIR / "Biology" / "Biology Home.md").exists()

    # link_home: heading created once, links stack under it, before the next section
    lecture.link_home(home, "2026-11-12 Locks")
    lecture.link_home(home, "2026-11-13 Paging")
    txt = home.read_text(encoding="utf-8")
    assert txt.count("## Recorded lectures") == 1
    assert "## Recorded lectures\n- [[2026-11-12 Locks]]\n- [[2026-11-13 Paging]]\n" in txt
    home.write_text("# X\n\n## Recorded lectures\n- [[a]]\n\n## Other\nz\n", encoding="utf-8")
    lecture.link_home(home, "b")
    assert "- [[a]]\n- [[b]]\n\n## Other" in home.read_text(encoding="utf-8")

    # class_now: Thursday 2026-11-12, 10-minute early window, end inclusive, other days ignored
    lecture.SCHEDULE.write_text(json.dumps({"OS": ["Thu 08:00-09:30"], "SE": ["Tue 8:00-9:30"]}), encoding="utf-8")
    at = lambda h, m: datetime.datetime(2026, 11, 12, h, m)
    assert lecture.class_now(at(7, 55)) == "OS"
    assert lecture.class_now(at(9, 30)) == "OS"
    assert lecture.class_now(at(7, 45)) is None
    assert lecture.class_now(at(9, 31)) is None
    assert lecture.class_now(datetime.datetime(2026, 11, 10, 8, 5)) == "SE"

# _flag: bookmark marks the segment being spoken at that second
segs = [S(start=0, text="a"), S(start=5, text="b"), S(start=10, text="c")]
assert lecture._flag(segs, [6]) == "a [IMPORTANT] b c"
assert lecture._flag(segs, [0.5, 99]) == "[IMPORTANT] a b [IMPORTANT] c"
print("ok")

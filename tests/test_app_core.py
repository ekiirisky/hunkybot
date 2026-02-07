import json
from datetime import timedelta

import app


def make_repo(tmp_path, auto_delete_after_hours=3):
    return app.MeetingRepository(
        str(tmp_path / "jadwal_test.json"),
        retention_days=30,
        auto_delete_after_hours=auto_delete_after_hours,
    )


def test_extract_first_json_object_from_fenced_block():
    text = 'hello\n```json\n{"action":"search_file","keyword":"proposal"}\n```'
    parsed = app.extract_first_json_object(text)
    assert parsed["action"] == "search_file"
    assert parsed["keyword"] == "proposal"


def test_validate_save_meeting_payload_ok():
    payload = {
        "action": "save_meeting",
        "data": {
            "date": "2026-02-08",
            "time": "09:30",
            "topic": "Daily Sync",
            "location": "Online",
            "link": "https://meet.example",
        },
    }
    ok, reason = app.validate_action_payload(payload, "120363@g.us")
    assert ok is True
    assert reason == "ok"


def test_validate_save_meeting_payload_invalid_time():
    payload = {
        "action": "save_meeting",
        "data": {"date": "2026-02-08", "time": "9 pagi", "topic": "x"},
    }
    ok, reason = app.validate_action_payload(payload, "120363@g.us")
    assert ok is False
    assert "HH:MM" in reason


def test_validate_search_file_payload_supports_nested_data_query():
    payload = {"action": "search_file", "data": {"query": "mft arrehlah wisata"}}
    ok, reason = app.validate_action_payload(payload, "120363@g.us")
    assert ok is True
    assert reason == "ok"


def test_meeting_repo_group_isolation(tmp_path):
    repo = make_repo(tmp_path)
    repo.add(
        {
            "group_id": "A@g.us",
            "date": "2026-02-08",
            "time": "09:30",
            "topic": "A meeting",
            "location": "Online",
            "link": "",
            "people_to_meet": "",
            "pic_partner": "",
            "reminded": False,
        }
    )
    repo.add(
        {
            "group_id": "B@g.us",
            "date": "2026-02-08",
            "time": "10:00",
            "topic": "B meeting",
            "location": "Online",
            "link": "",
            "people_to_meet": "",
            "pic_partner": "",
            "reminded": False,
        }
    )

    a_items = repo.list_by_group("A@g.us")
    b_items = repo.list_by_group("B@g.us")

    assert len(a_items) == 1
    assert len(b_items) == 1
    assert a_items[0]["topic"] == "A meeting"
    assert b_items[0]["topic"] == "B meeting"


def test_trigger_detection_group_vs_personal():
    assert app.is_triggered_message("62812@s.whatsapp.net", "halo") is True
    assert app.is_triggered_message("120363@g.us", "diskusi biasa") is False
    assert app.is_triggered_message("120363@g.us", "tolong cek jadwal") is True


def test_normalize_text_reply_if_json_response_key():
    raw = '{"response":"Halo! Saya HUNKY, asisten AI."}'
    assert app.normalize_text_reply_if_json(raw) == "Halo! Saya HUNKY, asisten AI."


def test_extract_drive_lookup_keyword_removes_filler_words():
    msg = "@hunky tolong ambil file mft arrehlah wisata dari google drive"
    assert app.extract_drive_lookup_keyword(msg) == "mft arrehlah wisata"


def test_is_web_lookup_intent_true_for_schedule_question():
    msg = "kapan final piala futsal asia?"
    assert app.is_web_lookup_intent(msg) is True


def test_is_web_lookup_intent_true_for_imperative_search():
    msg = "cari info puasa ramadhan di internet"
    assert app.is_web_lookup_intent(msg) is True


def test_is_web_lookup_intent_false_for_meeting_question():
    msg = "kapan jadwal meeting besok?"
    assert app.is_web_lookup_intent(msg) is False


def test_normalize_web_query_for_imperative_lookup():
    msg = "cari info puasa ramadhan di internet"
    assert app.normalize_web_query(msg) == "puasa ramadhan"


def test_route_intent_work_drive_search():
    routed = app.route_intent(
        message="tolong cari file mft arrehlah di google drive",
        sender="120363@g.us",
        has_file=False,
        triggered=True,
        has_web_context=False,
    )
    assert routed["mode"] == "work"
    assert routed["intent"] == "search_file"


def test_route_intent_general_web_search():
    routed = app.route_intent(
        message="kapan final piala futsal asia?",
        sender="628123@s.whatsapp.net",
        has_file=False,
        triggered=True,
        has_web_context=False,
    )
    assert routed["mode"] == "general"
    assert routed["intent"] == "web_search"


def test_route_intent_ambiguous_lookup():
    routed = app.route_intent(
        message="tolong cari file itu",
        sender="628123@s.whatsapp.net",
        has_file=False,
        triggered=True,
        has_web_context=False,
    )
    assert routed["mode"] == "ambiguous"
    assert routed["intent"] == "clarify_lookup_scope"


def test_route_intent_group_not_triggered_ignored():
    routed = app.route_intent(
        message="diskusi biasa",
        sender="120363@g.us",
        has_file=False,
        triggered=False,
        has_web_context=False,
    )
    assert routed["mode"] == "ignored"
    assert routed["intent"] == "ignored_text"


def test_meeting_repo_auto_delete_after_hours(tmp_path):
    repo = make_repo(tmp_path, auto_delete_after_hours=3)
    now = app.now_wib_naive()
    old_dt = now - timedelta(hours=4)
    recent_dt = now - timedelta(hours=2)

    raw_items = [
        {
            "GroupId": "120363@g.us",
            "Date": old_dt.strftime("%Y-%m-%d"),
            "Time": old_dt.strftime("%H:%M"),
            "Topic": "Expired Meeting",
            "Location": "Online",
            "Link": "",
            "reminded": False,
        },
        {
            "GroupId": "120363@g.us",
            "Date": recent_dt.strftime("%Y-%m-%d"),
            "Time": recent_dt.strftime("%H:%M"),
            "Topic": "Still Visible",
            "Location": "Online",
            "Link": "",
            "reminded": False,
        },
    ]

    with open(repo.db_path, "w", encoding="utf-8") as f:
        json.dump(raw_items, f)

    items = repo.list_by_group("120363@g.us")
    topics = [x["topic"] for x in items]
    assert "Expired Meeting" not in topics
    assert "Still Visible" in topics


def test_meeting_repo_zero_hours_purges_past_meeting_immediately(tmp_path):
    repo = make_repo(tmp_path, auto_delete_after_hours=0)
    now = app.now_wib_naive()
    old_dt = now - timedelta(hours=5)

    raw_items = [
        {
            "GroupId": "120363@g.us",
            "Date": old_dt.strftime("%Y-%m-%d"),
            "Time": old_dt.strftime("%H:%M"),
            "Topic": "Should Be Purged Immediately",
            "Location": "Online",
            "Link": "",
            "reminded": False,
        }
    ]

    with open(repo.db_path, "w", encoding="utf-8") as f:
        json.dump(raw_items, f)

    items = repo.list_by_group("120363@g.us")
    assert len(items) == 0

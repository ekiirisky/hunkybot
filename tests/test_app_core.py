import app


def make_repo(tmp_path):
    return app.MeetingRepository(str(tmp_path / "jadwal_test.json"), retention_days=30)


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

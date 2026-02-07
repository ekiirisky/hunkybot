import app


def setup_repo(tmp_path, monkeypatch):
    repo = app.MeetingRepository(str(tmp_path / "jadwal_test.json"), retention_days=30)
    monkeypatch.setattr(app, "meeting_repo", repo)
    return repo


def test_chat_fallback_text_when_non_json_ai(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_ai(*args, **kwargs):
        return "Ini jawaban biasa tanpa action"

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky apa kabar",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-1",
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "Ini jawaban biasa tanpa action"


def test_chat_save_meeting_action(tmp_path, monkeypatch):
    repo = setup_repo(tmp_path, monkeypatch)

    def fake_ai(*args, **kwargs):
        return '{"action":"save_meeting","data":{"date":"2026-02-08","time":"09:30","topic":"Kickoff","location":"Online","link":""}}'

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky catat meeting kickoff",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-2",
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert "Jadwal Meeting Tersimpan" in body["reply"]
    assert len(repo.list_by_group("120363@g.us")) == 1


def test_chat_missing_sender_returns_bad_request(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    client = app.app.test_client()
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "BAD_REQUEST"

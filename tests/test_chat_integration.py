import app
from pathlib import Path


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


def test_chat_json_non_action_falls_back_to_text(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_ai(*args, **kwargs):
        return (
            '{"action":null,"text":"Saya tidak mengenali perintah testt. '
            'Silakan beri konteks tambahan."}'
        )

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky testt",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-3",
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "Saya tidak mengenali perintah testt. Silakan beri konteks tambahan."


def test_chat_json_response_key_falls_back_to_text(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_ai(*args, **kwargs):
        return '{"response":"Halo! Apa kabar? Ada yang bisa saya bantu hari ini?"}'

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky halo",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-4",
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "Halo! Apa kabar? Ada yang bisa saya bantu hari ini?"


def test_chat_invalid_action_json_is_rewritten_as_plain_text(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    calls = {"count": 0}

    def fake_ai(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return '{"action":"web_search","data":{"query":"HUNKY AI save file to Google Drive features"}}'
        return "Iya, saya bisa bantu simpan file ke Google Drive jika Anda kirim file dengan perintah simpan."

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky kamu juga bisa menyimpan file ke google drive ya?",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-5",
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["reply"] == (
        "Iya, saya bisa bantu simpan file ke Google Drive jika Anda kirim file dengan perintah simpan."
    )


def test_chat_missing_sender_returns_bad_request(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    client = app.app.test_client()
    resp = client.post("/chat", json={"message": "hello"})
    assert resp.status_code == 400
    assert resp.get_json()["error_code"] == "BAD_REQUEST"


def test_group_file_without_bot_hit_is_ignored(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    client = app.app.test_client()

    temp_file = tmp_path / "doc.txt"
    temp_file.write_text("dummy")

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "simpan file ini",
            "file_path": str(temp_file),
            "mime_type": "text/plain",
            "bot_hit": False,
            "message_id": "m-6",
        },
    )

    assert resp.status_code == 200
    body = resp.get_json()
    assert body["status"] == "ignored_file"
    assert body["reason"] == "group_file_requires_bot_hit"
    assert Path(temp_file).exists() is False


def test_group_file_with_bot_hit_is_uploaded(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    client = app.app.test_client()

    temp_file = tmp_path / "doc2.txt"
    temp_file.write_text("dummy")

    def fake_upload(file_path, mime_type, custom_name=None, corr_id="-"):
        Path(file_path).unlink(missing_ok=True)
        return "✅ File Disimpan!"

    monkeypatch.setattr(app, "upload_ke_drive", fake_upload)

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "@hunky tolong simpan file ini",
            "file_path": str(temp_file),
            "mime_type": "text/plain",
            "bot_hit": True,
            "message_id": "m-7",
        },
    )

    assert resp.status_code == 200
    assert resp.get_json()["reply"] == "✅ File Disimpan!"


def test_chat_drive_no_access_reply_fallbacks_to_direct_drive_search(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_ai(*args, **kwargs):
        return (
            "Saya saat ini tidak memiliki akses untuk mengunduh file dari Google Drive. "
            "Silakan akses manual."
        )

    def fake_drive_search(keyword, corr_id="-"):
        assert keyword == "mft arrehlah wisata"
        return "📂 **Hasil Pencarian 'mft arrehlah wisata':**\n\n📄 mft arrehlah wisata.pdf\n🔗 https://drive.example/file"

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    monkeypatch.setattr(app, "cari_file_di_drive", fake_drive_search)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky tolong ambil file mft arrehlah wisata dari google drive",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-8",
        },
    )

    assert resp.status_code == 200
    assert "Hasil Pencarian" in resp.get_json()["reply"]


def test_personal_chat_drive_lookup_goes_direct_to_drive_search(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_drive_search(keyword, corr_id="-"):
        assert keyword == "mft arrehlah"
        return "📂 **Hasil Pencarian 'mft arrehlah':**\n\n📄 mft arrehlah.pdf\n🔗 https://drive.example/file"

    def fail_if_ai_called(*args, **kwargs):
        raise AssertionError("AI should not be called for direct drive lookup intent")

    monkeypatch.setattr(app, "cari_file_di_drive", fake_drive_search)
    monkeypatch.setattr(app, "tanya_blackbox", fail_if_ai_called)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "tolong cari file mft arrehlah di google drive",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-9",
        },
    )

    assert resp.status_code == 200
    assert "Hasil Pencarian" in resp.get_json()["reply"]


def test_chat_web_lookup_question_goes_to_web_flow(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_web_search(query, corr_id="-"):
        assert query == "kapan final piala futsal asia?"
        return "- Final AFC Futsal Asian Cup: 2026-02-15 di TBD"

    def fake_ai(*args, **kwargs):
        return "Final Piala Futsal Asia dijadwalkan pada 15 Februari 2026."

    monkeypatch.setattr(app, "cari_di_internet", fake_web_search)
    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "120363@g.us",
            "message": "hunky kapan final piala futsal asia?",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-10",
        },
    )

    assert resp.status_code == 200
    assert "15 Februari 2026" in resp.get_json()["reply"]


def test_chat_web_lookup_followup_uses_last_query(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    calls = {"queries": []}

    def fake_web_search(query, corr_id="-"):
        calls["queries"].append(query)
        return "- Hasil pencarian terbaru"

    def fake_ai(*args, **kwargs):
        return "Sudah ada info terbaru."

    monkeypatch.setattr(app, "cari_di_internet", fake_web_search)
    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    first = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "kapan final piala futsal asia?",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-11",
        },
    )
    assert first.status_code == 200

    second = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "apakah sudah ada infonya?",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-12",
        },
    )
    assert second.status_code == 200
    assert calls["queries"][0] == "kapan final piala futsal asia?"
    assert calls["queries"][1] == "kapan final piala futsal asia?"


def test_chat_web_lookup_replaces_placeholder_ai_reply_with_search_result(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_web_search(query, corr_id="-"):
        assert query == "cari info puasa ramadhan di internet"
        return "- Awal Ramadhan 1447 H diperkirakan jatuh sekitar 18 Februari 2026 (menunggu sidang isbat)."

    def fake_ai(*args, **kwargs):
        return "Tunggu sebentar ya, saya carikan informasi puasa Ramadhan dari internet."

    monkeypatch.setattr(app, "cari_di_internet", fake_web_search)
    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "cari info puasa ramadhan di internet",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-13",
        },
    )

    assert resp.status_code == 200
    assert "Awal Ramadhan 1447 H" in resp.get_json()["reply"]


def test_chat_web_lookup_replaces_no_info_ai_reply_with_search_result(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fake_web_search(query, corr_id="-"):
        assert query == "cari info puasa ramadhan di internet"
        return "- Puasa Ramadhan diperkirakan mulai pada pertengahan Februari 2026.\n  Sumber: https://example.com"

    def fake_ai(*args, **kwargs):
        return "Maaf, informasi tentang puasa Ramadan saat ini belum dapat saya temukan."

    monkeypatch.setattr(app, "cari_di_internet", fake_web_search)
    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "cari info puasa ramadhan di internet",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-14",
        },
    )

    assert resp.status_code == 200
    assert "Sumber:" in resp.get_json()["reply"]


def test_chat_ambiguous_lookup_returns_clarification(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)

    def fail_if_ai_called(*args, **kwargs):
        raise AssertionError("AI should not be called for ambiguous lookup")

    monkeypatch.setattr(app, "tanya_blackbox", fail_if_ai_called)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "tolong cari file itu",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-15",
        },
    )

    assert resp.status_code == 200
    assert "Google Drive atau internet" in resp.get_json()["reply"]


def test_chat_general_question_rewrites_no_data_template_reply(tmp_path, monkeypatch):
    setup_repo(tmp_path, monkeypatch)
    calls = {"count": 0}

    def fake_ai(*args, **kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            return (
                "Berdasarkan informasi yang tersedia, belum ada data terbaru tentang cara menjadi produktif "
                "yang dapat saya sampaikan."
            )
        return "Agar produktif: tetapkan 3 prioritas harian, blok waktu fokus 60-90 menit, dan evaluasi progres tiap malam."

    monkeypatch.setattr(app, "tanya_blackbox", fake_ai)
    client = app.app.test_client()

    resp = client.post(
        "/chat",
        json={
            "sender": "628123456789@s.whatsapp.net",
            "message": "bagaimana cara agar kita produktif?",
            "file_path": None,
            "mime_type": None,
            "message_id": "m-16",
        },
    )

    assert resp.status_code == 200
    assert "tetapkan 3 prioritas harian" in resp.get_json()["reply"]

from packages.request_handler.runtime import rows_from_doubt_friends_api, uid_flag_from_doubt_friend_row


def test_rows_from_doubt_friends_api_list() -> None:
    rows = rows_from_doubt_friends_api([{"uid": "u1"}, {"nick": "x"}])
    assert rows == [{"uid": "u1"}, {"nick": "x"}]


def test_rows_from_doubt_friends_api_data_dict() -> None:
    rows = rows_from_doubt_friends_api({"data": [{"uid": "u1"}]})
    assert rows == [{"uid": "u1"}]


def test_rows_from_doubt_friends_api_ignores_bad() -> None:
    assert rows_from_doubt_friends_api([1, "x", None]) == []
    assert rows_from_doubt_friends_api({"data": None}) == []


def test_uid_flag_prefers_flag_for_napcat() -> None:
    item = {"flag": "napcat-flag", "uid": "snowluma-uid", "user_id": 10001}
    assert uid_flag_from_doubt_friend_row(item) == ("10001", "napcat-flag")


def test_uid_flag_falls_back_to_uid_for_snowluma() -> None:
    item = {"uid": "snowluma-uid", "user_id": 10001, "nick": "xx"}
    assert uid_flag_from_doubt_friend_row(item) == ("10001", "snowluma-uid")


def test_uid_flag_falls_back_to_uin() -> None:
    item = {"uid": "snowluma-uid", "uin": 10002}
    assert uid_flag_from_doubt_friend_row(item) == ("10002", "snowluma-uid")


def test_uid_flag_missing_flag_returns_none() -> None:
    assert uid_flag_from_doubt_friend_row({"user_id": 10001}) is None


def test_uid_flag_missing_user_id_returns_none() -> None:
    assert uid_flag_from_doubt_friend_row({"uid": "snowluma-uid"}) is None

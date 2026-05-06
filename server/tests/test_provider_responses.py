from providers.index import normalize_response_content


def test_normalize_response_content_unwraps_single_object_list():
    content = [{"name": "Jessie", "description": "Team Rocket member"}]

    assert normalize_response_content(content) == {
        "name": "Jessie",
        "description": "Team Rocket member",
    }


def test_normalize_response_content_preserves_other_content_shapes():
    assert normalize_response_content("plain text") == "plain text"
    assert normalize_response_content({"name": "Jessie"}) == {"name": "Jessie"}
    assert normalize_response_content([{"a": 1}, {"b": 2}]) == [{"a": 1}, {"b": 2}]

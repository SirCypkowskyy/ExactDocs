import json

import pytest
from pydantic import ValidationError

from app.tags import Tags, dump_tags, parse_tags


def test_tags_are_lowercased_and_unique_in_order():
    tags = parse_tags('["Python", "web", "PYTHON", "Web", "api"]')
    assert isinstance(tags, Tags)
    assert tags.__root__ == ["python", "web", "api"]


def test_the_json_form_is_a_bare_list():
    assert json.loads(dump_tags(parse_tags('["A", "b"]'))) == ["a", "b"]


def test_an_object_is_not_tags():
    with pytest.raises(ValidationError):
        parse_tags('{"tags": ["a"]}')

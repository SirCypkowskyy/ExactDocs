"""The local OpenAI-compatible embeddings endpoint the Grounded Docs run serves its model at (#492).

The model is a stand-in that hashes text; the endpoint is the real one, on a loopback port.
"""

import base64
import struct
from pathlib import Path

import httpx
import pytest

from grounded_docs_stand_in import stand_in_embedding
from retrieval_eval.openai_embeddings import encoded, load_local, parse_request, serve

MODEL = stand_in_embedding()


def test_a_list_of_texts_gets_one_vector_each_with_the_tokens_counted() -> None:
    with serve(MODEL.embed, MODEL.count, MODEL.model) as endpoint:
        response = httpx.post(
            f"{endpoint.base_url}/embeddings",
            json={"input": ["one two", "three"], "model": "BAAI/bge-small-en-v1.5"},
        )

    assert response.status_code == 200
    body = response.json()
    assert [d["index"] for d in body["data"]] == [0, 1]
    assert body["data"][0]["embedding"] == MODEL.embed(["one two"])[0]
    assert body["model"] == "BAAI/bge-small-en-v1.5"
    assert body["usage"] == {"prompt_tokens": 3, "total_tokens": 3}
    assert (endpoint.served.requests, endpoint.served.texts, endpoint.served.tokens) == (1, 2, 3)


def test_one_text_and_base64_vectors_are_answered_as_the_openai_api_does() -> None:
    with serve(MODEL.embed, MODEL.count, MODEL.model) as endpoint:
        response = httpx.post(
            f"{endpoint.base_url}/embeddings",
            json={"input": "one", "model": "m", "encoding_format": "base64"},
        )

    (item,) = response.json()["data"]
    raw = base64.b64decode(item["embedding"])
    vector = struct.unpack(f"<{len(raw) // 4}f", raw)
    assert vector == pytest.approx(MODEL.embed(["one"])[0])


def test_a_request_that_is_not_text_is_refused() -> None:
    with serve(MODEL.embed, MODEL.count, MODEL.model) as endpoint:
        bad = httpx.post(f"{endpoint.base_url}/embeddings", json={"input": [[1, 2, 3]]})
        lost = httpx.post(f"{endpoint.base_url}/chat/completions", json={})
        models = httpx.get(f"{endpoint.base_url}/models")

    assert bad.status_code == 400
    assert "list of strings" in bad.json()["error"]["message"]
    assert lost.status_code == 404
    assert models.json()["data"][0]["id"] == MODEL.model
    assert endpoint.served.requests == 0
    assert len(endpoint.served.errors) == 1


def test_parse_request_reads_the_encoding_and_refuses_another() -> None:
    assert parse_request(b'{"input": "a", "model": "m"}') == (["a"], "m", "float")
    with pytest.raises(ValueError, match="encoding_format"):
        parse_request(b'{"input": "a", "encoding_format": "int8"}')
    with pytest.raises(ValueError, match="JSON object"):
        parse_request(b"[1, 2]")


def test_a_float_vector_is_sent_as_it_is() -> None:
    assert encoded([0.5, 1.0], "float") == [0.5, 1.0]


def test_a_model_that_was_not_pulled_is_refused(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match=r"exactdocs models pull BAAI/bge-small-en-v1\.5"):
        load_local(tmp_path, "BAAI/bge-small-en-v1.5")

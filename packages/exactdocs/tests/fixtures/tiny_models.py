"""Tiny ONNX stand-ins for the local models (#245): built in a test, loaded by real fastembed.

The default models (bge-small, MiniLM) are 158 MB; CI's ``[local]`` eval job runs those. Tests
use these instead: a bag-of-words embedding model and a word-overlap cross-encoder over a
word-level tokenizer whose vocabulary is the fixture docs repository's words. They go through
the very same path (fastembed, ONNX Runtime, the models directory, the marker), so a test with
sockets blocked proves the path is offline; their ranking is crude but follows shared words.

ONNX files are written by hand (protobuf wire format, a few ops of opset 13) so the tests need
no ``onnx`` package. ``register()`` adds both models to fastembed's lists, in this process.
"""

import hashlib
import json
import re
import struct
from array import array
from pathlib import Path

from fastembed import TextEmbedding
from fastembed.common.model_description import ModelSource, PoolingType
from fastembed.rerank.cross_encoder import TextCrossEncoder
from tokenizers import Tokenizer, models, normalizers, pre_tokenizers, processors

TINY_EMBEDDING = "exactdocs-test/tiny-embedding"
TINY_RERANKER = "exactdocs-test/tiny-reranker"
EMBEDDING_DIMENSIONS = 32
_RERANKER_DIMENSIONS = 64
_SPECIALS = ["[PAD]", "[UNK]", "[CLS]", "[SEP]"]
_DOCS = Path(__file__).parent / "docs-repo"
_MARKER = "exactdocs-model.json"

# ---------------------------------------------------------------- protobuf wire format


def _varint(value: int) -> bytes:
    out = bytearray()
    value &= (1 << 64) - 1
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _int(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _bytes(field: int, value: bytes | str) -> bytes:
    data = value.encode() if isinstance(value, str) else value
    return _varint(field << 3 | 2) + _varint(len(data)) + data


def _tensor(name: str, dims: list[int], data: bytes, data_type: int) -> bytes:
    return (
        b"".join(_int(1, d) for d in dims) + _int(2, data_type) + _bytes(8, name) + _bytes(9, data)
    )


def _floats(name: str, dims: list[int], values: list[float]) -> bytes:
    return _tensor(name, dims, array("f", values).tobytes(), 1)


def _int64s(name: str, values: list[int]) -> bytes:
    return _tensor(name, [len(values)], struct.pack(f"<{len(values)}q", *values), 7)


def _value_info(name: str, elem_type: int, dims: list[int | str]) -> bytes:
    shape = b"".join(_bytes(1, _bytes(2, d) if isinstance(d, str) else _int(1, d)) for d in dims)
    tensor = _int(1, elem_type) + _bytes(2, shape)
    return _bytes(1, name) + _bytes(2, _bytes(1, tensor))


def _node(op: str, inputs: list[str], outputs: list[str], **ints: int) -> bytes:
    attributes = b"".join(
        _bytes(5, _bytes(1, k) + _int(3, v) + _int(20, 2)) for k, v in ints.items()
    )
    return (
        b"".join(_bytes(1, i) for i in inputs)
        + b"".join(_bytes(2, o) for o in outputs)
        + _bytes(4, op)
        + attributes
    )


def _model(
    nodes: list[bytes], initializers: list[bytes], inputs: list[bytes], output: bytes
) -> bytes:
    graph = (
        b"".join(_bytes(1, n) for n in nodes)
        + _bytes(2, "tiny")
        + b"".join(_bytes(5, i) for i in initializers)
        + b"".join(_bytes(11, i) for i in inputs)
        + _bytes(12, output)
    )
    opset = _bytes(1, "") + _int(2, 13)
    return _int(1, 8) + _bytes(2, "exactdocs-tests") + _bytes(7, graph) + _bytes(8, opset)


# ---------------------------------------------------------------- the models


def _vocabulary() -> list[str]:
    words: set[str] = set()
    for path in _DOCS.rglob("*"):
        if path.is_file() and path.suffix in {".md", ".mdx", ".txt", ".rst", ".yaml"}:
            text = path.read_bytes().decode("utf-8", errors="ignore").lower()
            words.update(re.findall(r"\w+|[^\w\s]+", text))
    return _SPECIALS + sorted(words - set(_SPECIALS))


def _table(vocabulary: list[str], dimensions: int) -> list[float]:
    """One +-1 vector per word from its hash (zeros for the special tokens): the same every run."""
    values: list[float] = []
    for word in vocabulary:
        if word in _SPECIALS:
            values.extend([0.0] * dimensions)
            continue
        bits = int.from_bytes(hashlib.blake2b(word.encode(), digest_size=dimensions // 8).digest())
        values.extend(1.0 if bits >> i & 1 else -1.0 for i in range(dimensions))
    return values


def _embedding_onnx(vocabulary: list[str]) -> bytes:
    """Sum of the word vectors, given at every position (CLS pooling then reads the sum)."""
    rows = len(vocabulary)
    nodes = [
        _node("Gather", ["table", "input_ids"], ["words"], axis=0),
        _node("Cast", ["attention_mask"], ["mask"], to=1),
        _node("Unsqueeze", ["mask", "axis2"], ["mask3"]),
        _node("Mul", ["words", "mask3"], ["kept"]),
        _node("ReduceSum", ["kept", "axis1"], ["summed"], keepdims=1),
        _node("Shape", ["words"], ["shape"]),
        _node("Expand", ["summed", "shape"], ["last_hidden_state"]),
    ]
    initializers = [
        _floats("table", [rows, EMBEDDING_DIMENSIONS], _table(vocabulary, EMBEDDING_DIMENSIONS)),
        _int64s("axis1", [1]),
        _int64s("axis2", [2]),
    ]
    inputs = [
        _value_info("input_ids", 7, ["batch", "sequence"]),
        _value_info("attention_mask", 7, ["batch", "sequence"]),
    ]
    output = _value_info("last_hidden_state", 1, ["batch", "sequence", EMBEDDING_DIMENSIONS])
    return _model(nodes, initializers, inputs, output)


def _reranker_onnx(vocabulary: list[str]) -> bytes:
    """Dot product of the query's word sum and the document's (segment 0 and 1)."""
    rows = len(vocabulary)
    nodes = [
        _node("Gather", ["table", "input_ids"], ["words"], axis=0),
        _node("Cast", ["attention_mask"], ["mask"], to=1),
        _node("Cast", ["token_type_ids"], ["segment"], to=1),
        _node("Mul", ["mask", "segment"], ["document_mask"]),
        _node("Sub", ["mask", "document_mask"], ["query_mask"]),
        _node("Unsqueeze", ["query_mask", "axis2"], ["query_mask3"]),
        _node("Unsqueeze", ["document_mask", "axis2"], ["document_mask3"]),
        _node("Mul", ["words", "query_mask3"], ["query_words"]),
        _node("Mul", ["words", "document_mask3"], ["document_words"]),
        _node("ReduceSum", ["query_words", "axis1"], ["query"], keepdims=0),
        _node("ReduceSum", ["document_words", "axis1"], ["document"], keepdims=0),
        _node("Mul", ["query", "document"], ["product"]),
        _node("ReduceSum", ["product", "axis1"], ["logits"], keepdims=1),
    ]
    initializers = [
        _floats("table", [rows, _RERANKER_DIMENSIONS], _table(vocabulary, _RERANKER_DIMENSIONS)),
        _int64s("axis1", [1]),
        _int64s("axis2", [2]),
    ]
    inputs = [
        _value_info("input_ids", 7, ["batch", "sequence"]),
        _value_info("attention_mask", 7, ["batch", "sequence"]),
        _value_info("token_type_ids", 7, ["batch", "sequence"]),
    ]
    return _model(nodes, initializers, inputs, _value_info("logits", 1, ["batch", 1]))


def _write_tokenizer(folder: Path, vocabulary: list[str]) -> None:

    tokenizer = Tokenizer(models.WordLevel({w: i for i, w in enumerate(vocabulary)}, "[UNK]"))
    tokenizer.normalizer = normalizers.Lowercase()
    tokenizer.pre_tokenizer = pre_tokenizers.Whitespace()
    tokenizer.post_processor = processors.TemplateProcessing(
        single="[CLS] $A [SEP]",
        pair="[CLS] $A [SEP] $B:1 [SEP]:1",
        special_tokens=[("[CLS]", 2), ("[SEP]", 3)],
    )
    tokenizer.save(str(folder / "tokenizer.json"))
    (folder / "tokenizer_config.json").write_text(
        json.dumps({"model_max_length": 512, "pad_token": "[PAD]"})
    )
    (folder / "special_tokens_map.json").write_text(
        json.dumps(
            {"pad_token": "[PAD]", "unk_token": "[UNK]", "cls_token": "[CLS]", "sep_token": "[SEP]"}
        )
    )
    (folder / "config.json").write_text(json.dumps({"pad_token_id": 0}))


def register() -> None:
    """Add both stand-ins to fastembed's model lists (once per process)."""

    if not any(m["model"] == TINY_EMBEDDING for m in TextEmbedding.list_supported_models()):
        TextEmbedding.add_custom_model(
            model=TINY_EMBEDDING,
            pooling=PoolingType.CLS,
            normalization=True,
            sources=ModelSource(hf=TINY_EMBEDDING),
            dim=EMBEDDING_DIMENSIONS,
            model_file="model.onnx",
        )
    if not any(m["model"] == TINY_RERANKER for m in TextCrossEncoder.list_supported_models()):
        TextCrossEncoder.add_custom_model(
            model=TINY_RERANKER, sources=ModelSource(hf=TINY_RERANKER), model_file="model.onnx"
        )


def install(models_dir: Path, *, embedding: bool = True, reranker: bool = True) -> Path:
    """Write the stand-ins into a models directory as ``exactdocs models pull`` leaves models.

    Args:
        models_dir: The models directory.
        embedding: Write the embedding model.
        reranker: Write the cross-encoder.

    Returns:
        The models directory.
    """
    vocabulary = _vocabulary()
    wanted = [
        (TINY_EMBEDDING, "embedding", EMBEDDING_DIMENSIONS, _embedding_onnx, embedding),
        (TINY_RERANKER, "reranker", None, _reranker_onnx, reranker),
    ]
    for name, role, dimensions, build, on in wanted:
        if not on:
            continue
        folder = models_dir / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "model.onnx").write_bytes(build(vocabulary))
        _write_tokenizer(folder, vocabulary)
        marker = {"model": name, "role": role, "dimensions": dimensions, "files": ["model.onnx"]}
        (folder / _MARKER).write_text(json.dumps(marker))
    return models_dir

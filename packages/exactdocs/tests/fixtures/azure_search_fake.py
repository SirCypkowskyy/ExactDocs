"""An in-process fake of the Azure AI Search REST API, the subset the adapter uses (#353).

There is no Azure AI Search emulator, so CI runs the contract suites against this fake, plugged
in as the azure-core transport (``AsyncioRequestsTransport`` over a ``requests`` session whose
adapter answers here): the SDK, azure-core and requests all run as in production, only the
socket is replaced. The manual workflow (``.github/workflows/azure-search.yml``) runs the same
suites against a real service.

What it does for real (an adapter cannot pass by relying on the fake being lax):

- index definitions: name rules, one ``Edm.String`` key, known types and analyzers, vector
  fields (dimensions, an existing profile and algorithm), scoring profiles naming searchable
  fields; ``409`` for an existing name, ``404`` for a missing index;
- documents: ``upload`` / ``merge`` / ``mergeOrUpload`` / ``delete``, key characters, unknown
  fields and vectors of the wrong dimensions refused (``400``), at most 1,000 actions;
- writes are visible a moment later, as Azure indexes in near real time: each batch becomes
  searchable only after ``lag`` more search requests;
- OData filters (``eq`` / ``ne``, ``and`` / ``or`` / ``not``, ``search.in``, ``any`` / ``all``
  lambdas) on filterable fields only, applied before ranking and before the vector search
  (``preFilter``);
- full Lucene queries made of escaped terms only (an unescaped operator is refused, so the
  adapter must escape), analysed by the field's analyzer (``whitespace``), ranked with BM25
  (``k1`` 1.2, ``b`` 0.75, Lucene's IDF over the whole index) times the scoring profile's field
  weights; ``searchMode`` any or all;
- vector queries: exact cosine over the pre-filtered documents, scored ``1 / (1 + distance)``
  as Azure scores cosine, the ``k`` nearest; hybrid (words and vectors): reciprocal rank fusion,
  ``1 / (60 + rank)`` summed;
- ``$orderby`` (``search.score()`` and sortable fields), ``top`` / ``skip``, ``select`` of
  retrievable fields, ``$count``, facets on facetable fields (``count:N``);
- authentication: the ``api-key`` header or a bearer token, ``401`` / ``403`` otherwise.

Anything else the adapter would send is refused with ``400`` naming it, so a new use of the API
shows up here first.
"""

import io
import json
import math
import re
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import parse_qs, unquote, urlsplit

import requests
import urllib3
from azure.core.pipeline.transport import AsyncHttpTransport, AsyncioRequestsTransport
from requests.adapters import BaseAdapter

API_VERSION = "2026-04-01"
ENDPOINT = "https://fake.search.windows.net"
API_KEY = "fake-admin-key-0123456789"
TOKEN = "fake-entra-token"
K1, B = 1.2, 0.75
RRF_K = 60
MAX_ACTIONS = 1000
TYPES = {
    "Edm.String",
    "Edm.Int32",
    "Edm.Int64",
    "Edm.Double",
    "Edm.Boolean",
    "Collection(Edm.String)",
    "Collection(Edm.Single)",
}
ANALYZERS = {"whitespace", "keyword"}
LUCENE_SPECIAL = set('+-&|!(){}[]^"~*?:\\/')
KEY = re.compile(r"[A-Za-z0-9_\-=]{1,1024}")
INDEX_NAME = re.compile(r"[a-z0-9](?:-?[a-z0-9]){1,127}")
SEARCH_KEYS = {
    "search",
    "searchMode",
    "queryType",
    "searchFields",
    "scoringProfile",
    "scoringStatistics",
    "filter",
    "orderby",
    "select",
    "top",
    "skip",
    "count",
    "facets",
    "vectorQueries",
    "vectorFilterMode",
}

type Doc = dict[str, Any]


class FakeError(Exception):
    """A request the service refuses: its status and message."""

    def __init__(self, status: int, message: str, code: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.message = message
        self.code = code


# ---------------------------------------------------------------- OData filters


_TOKEN = re.compile(
    r"\s*(?:(?P<string>'(?:[^']|'')*')|(?P<word>[A-Za-z_][\w.]*)|(?P<punct>[(),:/])|(?P<number>-?\d+(?:\.\d+)?))"
)


def _tokens(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    while position < len(text):
        if text[position:].strip() == "":
            break
        match = _TOKEN.match(text, position)
        if match is None:
            raise FakeError(
                400, f"Invalid expression: syntax error at position {position} in '{text}'"
            )
        kind = match.lastgroup or ""
        value = match.group(kind)
        tokens.append((kind, value))
        position = match.end()
    return tokens


type Predicate = Callable[[Doc, Mapping[str, Any]], bool]


@dataclass(slots=True)
class _FilterParser:
    """Recursive descent over the OData subset the adapter uses; checks fields are filterable."""

    tokens: list[tuple[str, str]]
    fields: Mapping[str, Doc]
    position: int = 0
    variables: set[str] = field(default_factory=set)

    def parse(self) -> Predicate:
        predicate = self._or()
        if self.position != len(self.tokens):
            raise FakeError(400, f"Invalid expression: unexpected {self._peek()[1]!r}")
        return predicate

    def _peek(self) -> tuple[str, str]:
        return self.tokens[self.position] if self.position < len(self.tokens) else ("", "")

    def _take(self, value: str | None = None, kind: str | None = None) -> str:
        token_kind, token = self._peek()
        if (value is not None and token != value) or (kind is not None and token_kind != kind):
            raise FakeError(400, f"Invalid expression: expected {value or kind}, found {token!r}")
        self.position += 1
        return token

    def _or(self) -> Predicate:
        parts = [self._and()]
        while self._peek() == ("word", "or"):
            self._take("or")
            parts.append(self._and())
        return parts[0] if len(parts) == 1 else lambda d, env: any(p(d, env) for p in parts)

    def _and(self) -> Predicate:
        parts = [self._not()]
        while self._peek() == ("word", "and"):
            self._take("and")
            parts.append(self._not())
        return parts[0] if len(parts) == 1 else lambda d, env: all(p(d, env) for p in parts)

    def _not(self) -> Predicate:
        if self._peek() == ("word", "not"):
            self._take("not")
            inner = self._not()
            return lambda d, env: not inner(d, env)
        return self._primary()

    def _primary(self) -> Predicate:
        kind, token = self._peek()
        if token == "(":
            self._take("(")
            inner = self._or()
            self._take(")")
            return inner
        if token == "search.in":
            return self._search_in()
        name = self._take(kind="word")
        if self._peek()[1] == "/":
            return self._lambda(name)
        operator = self._take(kind="word")
        if operator not in {"eq", "ne"}:
            raise FakeError(
                400, f"Invalid expression: the fake supports eq and ne, not {operator!r}"
            )
        literal = self._literal()
        getter = self._getter(name, collection_ok=False)
        if operator == "eq":
            return lambda d, env: getter(d, env) == literal
        return lambda d, env: getter(d, env) != literal

    def _literal(self) -> Any:
        kind, token = self._peek()
        self.position += 1
        if kind == "string":
            return token[1:-1].replace("''", "'")
        if kind == "number":
            return float(token) if "." in token else int(token)
        if token in {"true", "false"}:
            return token == "true"
        if token == "null":
            return None
        raise FakeError(400, f"Invalid expression: {token!r} is not a literal")

    def _search_in(self) -> Predicate:
        self._take("search.in")
        self._take("(")
        name = self._take(kind="word")
        self._take(",")
        values_token = self._take(kind="string")[1:-1].replace("''", "'")
        delimiters = " ,"
        if self._peek()[1] == ",":
            self._take(",")
            delimiters = self._take(kind="string")[1:-1].replace("''", "'")
        self._take(")")
        pattern = "[" + re.escape(delimiters) + "]"
        values = {v for v in re.split(pattern, values_token) if v}
        getter = self._getter(name, collection_ok=False)
        return lambda d, env: getter(d, env) in values

    def _lambda(self, name: str) -> Predicate:
        spec = self.fields.get(name)
        if spec is None or not spec["type"].startswith("Collection("):
            raise FakeError(400, f"Invalid expression: {name!r} is not a collection field")
        if not spec.get("filterable"):
            raise FakeError(400, f"Invalid expression: the field {name!r} is not filterable")
        self._take("/")
        quantifier = self._take(kind="word")
        if quantifier not in {"any", "all"}:
            raise FakeError(400, f"Invalid expression: {quantifier!r} is not any or all")
        self._take("(")
        variable = self._take(kind="word")
        self._take(":")
        self.variables.add(variable)
        body = self._or()
        self.variables.discard(variable)
        self._take(")")

        def holds(d: Doc, env: Mapping[str, Any]) -> bool:
            values = d.get(name) or []
            test = lambda v: body(d, {**env, variable: v})
            return any(map(test, values)) if quantifier == "any" else all(map(test, values))

        return holds

    def _getter(self, name: str, *, collection_ok: bool) -> Callable[[Doc, Mapping[str, Any]], Any]:
        if name in self.variables:
            return lambda d, env: env[name]
        spec = self.fields.get(name)
        if spec is None:
            raise FakeError(400, f"Invalid expression: Could not find a property named '{name}'")
        if not spec.get("filterable"):
            raise FakeError(400, f"Invalid expression: the field '{name}' is not filterable")
        if spec["type"].startswith("Collection(") and not collection_ok:
            raise FakeError(400, f"Invalid expression: '{name}' is a collection: use any or all")
        return lambda d, env: d.get(name)


def parse_filter(text: str, fields: Mapping[str, Doc]) -> Predicate:
    """Parse an OData filter of the supported subset against an index's fields."""
    return _FilterParser(_tokens(text), fields).parse()


# ---------------------------------------------------------------- queries


def lucene_terms(text: str) -> list[str]:
    """Split a full Lucene query of escaped terms; refuse unescaped operators."""
    terms: list[str] = []
    current: list[str] = []
    escaped = False
    for char in text:
        if escaped:
            current.append(char)
            escaped = False
        elif char == "\\":
            escaped = True
        elif char.isspace():
            if current:
                terms.append("".join(current))
            current = []
        elif char in LUCENE_SPECIAL:
            raise FakeError(
                400, f"the fake takes escaped terms only: unescaped {char!r} in {text!r}"
            )
        else:
            current.append(char)
    if escaped:
        raise FakeError(400, f"Failed to parse query string: dangling escape in {text!r}")
    if current:
        terms.append("".join(current))
    if any(t in {"AND", "OR", "NOT", "&&", "||"} for t in terms):
        raise FakeError(400, f"the fake takes no Lucene operators: {text!r}")
    return terms


def _analyze(text: str | None, analyzer: str | None) -> list[str]:
    if not text:
        return []
    if analyzer == "keyword":
        return [text]
    return text.split()  # whitespace (the only text analyzer the fake knows)


def _cosine_similarity(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norms = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norms if norms else 0.0


# ---------------------------------------------------------------- indexes


@dataclass(slots=True)
class FakeIndex:
    """One index: its definition, its visible documents, and the writes not visible yet."""

    definition: Doc
    documents: dict[str, Doc] = field(default_factory=dict)
    pending: list[tuple[int, list[Doc]]] = field(default_factory=list)

    @property
    def fields(self) -> dict[str, Doc]:
        return {f["name"]: f for f in self.definition["fields"]}

    @property
    def key(self) -> str:
        return next(f["name"] for f in self.definition["fields"] if f.get("key"))

    def tick(self) -> None:
        """One search request went by: apply the writes whose lag ran out, in order."""
        still: list[tuple[int, list[Doc]]] = []
        due = True
        for countdown, actions in self.pending:
            if due and countdown <= 1:
                self._apply(actions)
            else:
                due = False
                still.append((countdown - 1, actions))
        self.pending = still

    def _apply(self, actions: list[Doc]) -> None:
        key = self.key
        for action in actions:
            kind = action["@search.action"]
            values = {k: v for k, v in action.items() if k != "@search.action"}
            name = values[key]
            if kind == "delete":
                self.documents.pop(name, None)
            elif kind == "upload":
                self.documents[name] = values
            else:  # merge, mergeOrUpload
                self.documents[name] = self.documents.get(name, {}) | values


def _normalised(definition: Doc) -> Doc:
    """Fill the defaults Azure fills, as a GET of the index returns them."""
    fields = []
    for spec in definition["fields"]:
        vector = spec["type"] == "Collection(Edm.Single)"
        filled = {
            "name": spec["name"],
            "type": spec["type"],
            "key": bool(spec.get("key", False)),
            "retrievable": spec.get("retrievable", True),
            "stored": spec.get("stored", True),
            "searchable": spec.get(
                "searchable",
                spec["type"].endswith("Edm.String)") or spec["type"] == "Edm.String" or vector,
            ),
            "filterable": spec.get("filterable", not vector),
            "sortable": spec.get(
                "sortable", spec["type"] != "Collection(Edm.String)" and not vector
            ),
            "facetable": spec.get("facetable", not vector),
            "analyzer": spec.get("analyzer"),
            "searchAnalyzer": spec.get("searchAnalyzer"),
            "indexAnalyzer": spec.get("indexAnalyzer"),
            "dimensions": spec.get("dimensions"),
            "vectorSearchProfile": spec.get("vectorSearchProfile"),
            "synonymMaps": [],
            "fields": [],
        }
        fields.append(filled)
    return {
        "name": definition["name"],
        "fields": fields,
        "scoringProfiles": definition.get("scoringProfiles", []),
        "defaultScoringProfile": definition.get("defaultScoringProfile"),
        "similarity": definition.get(
            "similarity", {"@odata.type": "#Microsoft.Azure.Search.BM25Similarity"}
        ),
        "vectorSearch": definition.get("vectorSearch"),
        "analyzers": [],
        "tokenizers": [],
        "tokenFilters": [],
        "charFilters": [],
        "@odata.etag": '"0x1"',
    }


def _check_definition(definition: Doc) -> Doc:
    name = definition.get("name", "")
    if not INDEX_NAME.fullmatch(name):
        raise FakeError(400, f"Invalid index name '{name}'", "InvalidRequestParameter")
    fields = definition.get("fields") or []
    keys = [f for f in fields if f.get("key")]
    if len(keys) != 1 or keys[0].get("type") != "Edm.String":
        raise FakeError(400, "The index must have exactly one key field of type Edm.String")
    names = [f.get("name") for f in fields]
    if len(set(names)) != len(names):
        raise FakeError(400, "Field names must be unique")
    normalised = _normalised(definition)
    search = definition.get("vectorSearch") or {}
    algorithms = {a["name"]: a for a in search.get("algorithms", [])}
    profiles = {p["name"]: p for p in search.get("profiles", [])}
    for spec in normalised["fields"]:
        if spec["type"] not in TYPES:
            raise FakeError(400, f"The field '{spec['name']}' has an unsupported type")
        if spec["analyzer"] is not None and spec["analyzer"] not in ANALYZERS:
            raise FakeError(400, f"Unknown analyzer '{spec['analyzer']}'")
        if spec["stored"] is False and spec["retrievable"]:
            raise FakeError(400, f"The field '{spec['name']}' cannot be retrievable and not stored")
        if spec["type"] == "Collection(Edm.Single)":
            if not 2 <= int(spec["dimensions"] or 0) <= 4096:
                raise FakeError(
                    400, f"The vector field '{spec['name']}' needs 2 to 4096 dimensions"
                )
            if (
                spec["filterable"]
                or spec["sortable"]
                or spec["facetable"]
                or not spec["searchable"]
            ):
                raise FakeError(400, f"The vector field '{spec['name']}' must be searchable only")
            profile = profiles.get(spec["vectorSearchProfile"])
            if profile is None or profile.get("algorithm") not in algorithms:
                raise FakeError(400, f"The vector field '{spec['name']}' names no known profile")
    searchable = {f["name"] for f in normalised["fields"] if f["searchable"]}
    for profile in normalised["scoringProfiles"]:
        weights = (profile.get("text") or {}).get("weights") or {}
        if not set(weights) <= searchable:
            raise FakeError(400, f"The scoring profile '{profile['name']}' weighs unknown fields")
    default = normalised["defaultScoringProfile"]
    if default and default not in {p["name"] for p in normalised["scoringProfiles"]}:
        raise FakeError(400, f"The default scoring profile '{default}' does not exist")
    return normalised


# ---------------------------------------------------------------- the service


@dataclass(slots=True)
class FakeSearchService:
    """The fake service. ``transport`` plugs it into the adapter; ``indexes`` shows its state."""

    api_key: str = API_KEY
    token: str = TOKEN
    lag: int = 2
    indexes: dict[str, FakeIndex] = field(default_factory=dict)
    unavailable: bool = False
    requests: list[tuple[str, str]] = field(default_factory=list)
    bodies: list[Doc] = field(default_factory=list)

    def transport(self) -> AsyncHttpTransport:
        """An azure-core transport whose requests this service answers (one per call)."""
        session = requests.Session()
        session.mount("https://", _Adapter(self))
        return AsyncioRequestsTransport(session=session, session_owner=True)

    def visible(self, index: str) -> dict[str, Doc]:
        """What the index returns now (its visible documents)."""
        return self.indexes[index].documents

    def flush(self) -> None:
        """Make every pending write visible."""
        for index in self.indexes.values():
            while index.pending:
                index.tick()

    # ------------------------------------------------------------ routing

    def handle(
        self, method: str, url: str, headers: Mapping[str, str], body: bytes | None
    ) -> tuple[int, Doc | None]:
        if self.unavailable:
            raise requests.ConnectionError("the fake service is switched off")
        parts = urlsplit(url)
        query = parse_qs(parts.query)
        path = unquote(parts.path)
        self.requests.append((method, path))
        if query.get("api-version") != [API_VERSION]:
            raise FakeError(400, f"Invalid or missing api-version (the fake speaks {API_VERSION})")
        self._authenticate(headers)
        payload = json.loads(body) if body else None
        if payload is not None:
            self.bodies.append(payload)
        if path == "/servicestats" and method == "GET":
            return 200, {"counters": {"indexesCount": {"usage": len(self.indexes)}}, "limits": {}}
        if path == "/indexes" and method == "GET":
            return 200, {"value": [{"name": n} for n in sorted(self.indexes)]}
        if path == "/indexes" and method == "POST":
            return self._create(payload or {})
        match = re.fullmatch(
            r"/indexes\('([^']+)'\)(/docs/(search\.index|search\.post\.search))?", path
        )
        if match is None:
            raise FakeError(400, f"the fake does not implement {method} {path}")
        name, operation = match.group(1), match.group(3)
        if operation is None and method == "GET":
            return 200, self._index(name).definition
        if operation is None and method == "DELETE":
            return (204 if self.indexes.pop(name, None) else 404), None
        if operation == "search.index" and method == "POST":
            return self._write(self._index(name), payload or {})
        if operation == "search.post.search" and method == "POST":
            return 200, self._search(self._index(name), payload or {})
        raise FakeError(400, f"the fake does not implement {method} {path}")

    def _authenticate(self, headers: Mapping[str, str]) -> None:
        key = headers.get("api-key")
        bearer = headers.get("Authorization", "")
        if key is not None:
            if key != self.api_key:
                raise FakeError(403, "Forbidden: the API key is not valid")
            return
        if bearer:
            if bearer != f"Bearer {self.token}":
                raise FakeError(401, "Unauthorized: the access token is not valid")
            return
        raise FakeError(401, "Unauthorized: no api-key header and no bearer token")

    def _index(self, name: str) -> FakeIndex:
        index = self.indexes.get(name)
        if index is None:
            raise FakeError(
                404, f"The index '{name}' for service 'fake' was not found.", "ResourceNotFound"
            )
        return index

    def _create(self, definition: Doc) -> tuple[int, Doc]:
        normalised = _check_definition(definition)
        if normalised["name"] in self.indexes:
            raise FakeError(
                409, f"Cannot create index '{normalised['name']}' because it already exists."
            )
        self.indexes[normalised["name"]] = FakeIndex(definition=normalised)
        return 201, normalised

    # ------------------------------------------------------------ documents

    def _write(self, index: FakeIndex, payload: Doc) -> tuple[int, Doc]:
        actions = payload.get("value") or []
        if len(actions) > MAX_ACTIONS:
            raise FakeError(400, f"A batch holds at most {MAX_ACTIONS} actions")
        fields = index.fields
        key = index.key
        for action in actions:
            if action.get("@search.action") not in {"upload", "merge", "mergeOrUpload", "delete"}:
                raise FakeError(400, f"Unknown action {action.get('@search.action')!r}")
            name = action.get(key)
            if not isinstance(name, str) or not KEY.fullmatch(name):
                raise FakeError(400, f"Invalid document key: '{name}'")
            for prop, value in action.items():
                if prop == "@search.action":
                    continue
                spec = fields.get(prop)
                if spec is None:
                    raise FakeError(
                        400,
                        f"The property '{prop}' does not exist on type 'search.documentFields'.",
                    )
                if spec["type"] == "Collection(Edm.Single)" and value is not None:
                    if len(value) != spec["dimensions"]:
                        raise FakeError(
                            400,
                            f"The vector field '{prop}' expects {spec['dimensions']} dimensions, not {len(value)}",
                        )
        known = set(index.documents) | {
            a[key] for _, batch in index.pending for a in batch if a["@search.action"] != "delete"
        }
        results = [
            {
                "key": a[key],
                "status": True,
                "errorMessage": None,
                "statusCode": 200 if a[key] in known or a["@search.action"] == "delete" else 201,
            }
            for a in actions
        ]
        index.pending.append((self.lag, [dict(a) for a in actions]))
        if self.lag <= 0:
            index.tick()
        return 200, {"value": results}

    # ------------------------------------------------------------ search

    def _search(self, index: FakeIndex, body: Doc) -> Doc:
        unknown = set(body) - SEARCH_KEYS
        if unknown:
            raise FakeError(400, f"the fake does not implement {sorted(unknown)}")
        index.tick()
        fields = index.fields
        documents = list(index.documents.values())
        where = parse_filter(body["filter"], fields) if body.get("filter") else None
        passing = [d for d in documents if where is None or where(d, {})]
        text = body.get("search")
        scores: dict[str, float] = {}
        key = index.key
        vector_queries = body.get("vectorQueries") or []
        text_ranked: list[str] = []
        if text and text != "*":
            if body.get("queryType") != "full":
                raise FakeError(400, "the fake implements queryType full only")
            text_scores = self._bm25(index, documents, passing, text, body)
            text_ranked = sorted(text_scores, key=lambda k: (-text_scores[k], k))
            scores = text_scores
        elif not vector_queries:
            scores = {d[key]: 1.0 for d in passing}
        if vector_queries:
            if len(vector_queries) != 1:
                raise FakeError(400, "the fake implements one vector query")
            mode = body.get("vectorFilterMode", "preFilter")
            near = self._nearest(index, documents, passing, vector_queries[0], mode)
            if text_ranked:
                fused: dict[str, float] = {}
                for ranked in (text_ranked, sorted(near, key=lambda k: (-near[k], k))):
                    for rank, name in enumerate(ranked, start=1):
                        fused[name] = fused.get(name, 0.0) + 1.0 / (RRF_K + rank)
                scores = fused
            else:
                scores = near
        matched = [index.documents[name] for name in scores]
        result: Doc = {}
        if body.get("count"):
            result["@odata.count"] = len(matched)
        if body.get("facets"):
            result["@search.facets"] = self._facets(fields, matched, body["facets"])
        ordered = self._ordered(fields, matched, scores, key, body.get("orderby"))
        skip = int(body.get("skip") or 0)
        top = int(body["top"]) if body.get("top") is not None else 50
        select = [s.strip() for s in (body.get("select") or "").split(",") if s.strip()]
        for name in select:
            if name not in fields:
                raise FakeError(
                    400, f"Invalid expression: Could not find a property named '{name}'"
                )
            if not fields[name]["retrievable"]:
                raise FakeError(400, f"The field '{name}' is not retrievable")
        shown = select or [n for n, f in fields.items() if f["retrievable"]]
        result["value"] = [
            {"@search.score": scores[d[key]]} | {n: d.get(n) for n in shown}
            for d in ordered[skip : skip + top]
        ]
        return result

    def _bm25(
        self, index: FakeIndex, documents: list[Doc], passing: list[Doc], text: str, body: Doc
    ) -> dict[str, float]:
        fields = index.fields
        terms = lucene_terms(text)
        searchable = [
            n
            for n, f in fields.items()
            if f["searchable"] and f["type"] != "Collection(Edm.Single)"
        ]
        wanted = body.get("searchFields")
        names = [s.strip() for s in wanted.split(",")] if wanted else searchable
        for name in names:
            if name not in searchable:
                raise FakeError(400, f"The field '{name}' is not searchable")
        profile_name = body.get("scoringProfile") or index.definition.get("defaultScoringProfile")
        profiles = {p["name"]: p for p in index.definition["scoringProfiles"]}
        if profile_name and profile_name not in profiles:
            raise FakeError(400, f"Unknown scoring profile '{profile_name}'")
        weights = ((profiles.get(profile_name) or {}).get("text") or {}).get("weights") or {}
        mode_all = body.get("searchMode") == "all"
        key = index.key
        scores: dict[str, float] = {}
        # Lucene's statistics over the whole index (global scoring statistics).
        for name in names:
            analyzer = fields[name]["analyzer"]
            tokens = {d[key]: _analyze(d.get(name), analyzer) for d in documents}
            with_field = [t for t in tokens.values() if t]
            total = len(documents)
            average = (sum(map(len, with_field)) / len(with_field)) if with_field else 0.0
            for term in terms:
                (analysed,) = _analyze(term, analyzer) or [""]
                containing = sum(1 for t in tokens.values() if analysed in t)
                if not containing:
                    continue
                idf = math.log(1 + (total - containing + 0.5) / (containing + 0.5))
                for d in passing:
                    counts = Counter(tokens[d[key]])
                    tf = counts.get(analysed, 0)
                    if not tf:
                        continue
                    length = len(tokens[d[key]])
                    norm = tf * (K1 + 1) / (tf + K1 * (1 - B + B * length / average))
                    scores[d[key]] = scores.get(d[key], 0.0) + idf * norm * float(
                        weights.get(name, 1.0)
                    )
        if mode_all:

            def has_all(d: Doc) -> bool:
                found = {t for n in names for t in _analyze(d.get(n), fields[n]["analyzer"])}
                return all(t in found for t in terms)

            scores = {k: s for k, s in scores.items() if has_all(index.documents[k])}
        return scores

    def _nearest(
        self, index: FakeIndex, documents: list[Doc], passing: list[Doc], query: Doc, mode: str
    ) -> dict[str, float]:
        if query.get("kind") != "vector":
            raise FakeError(
                400, f"the fake implements vector queries only, not {query.get('kind')!r}"
            )
        fields = index.fields
        name = query.get("fields")
        spec = fields.get(name or "")
        if spec is None or spec["type"] != "Collection(Edm.Single)":
            raise FakeError(400, f"The field '{name}' is not a vector field")
        vector = query.get("vector") or []
        if len(vector) != spec["dimensions"]:
            raise FakeError(
                400,
                f"The vector query has {len(vector)} dimensions, the field {spec['dimensions']}",
            )
        k = int(query.get("k") or 50)
        key = index.key
        pool = passing if mode == "preFilter" else documents
        scored = {
            d[key]: 1.0 / (1.0 + (1.0 - _cosine_similarity(vector, d[name])))
            for d in pool
            if d.get(name)
        }
        best = sorted(scored, key=lambda n: (-scored[n], n))[:k]
        if mode != "preFilter":
            allowed = {d[key] for d in passing}
            best = [n for n in best if n in allowed]
        return {n: scored[n] for n in best}

    def _facets(self, fields: Mapping[str, Doc], matched: list[Doc], facets: Sequence[str]) -> Doc:
        result: Doc = {}
        for facet in facets:
            name, *parameters = [p.strip() for p in facet.split(",")]
            spec = fields.get(name)
            if spec is None or not spec["facetable"]:
                raise FakeError(400, f"The field '{name}' is not facetable")
            options = dict(p.split(":", 1) for p in parameters)
            if set(options) - {"count"}:
                raise FakeError(400, f"the fake implements facet count only: {facet!r}")
            count = int(options.get("count", 10))
            values: Counter[str] = Counter()
            for d in matched:
                value = d.get(name)
                for v in value if isinstance(value, list) else [value]:
                    if v is not None:
                        values[v] += 1
            ordered = sorted(values.items(), key=lambda item: (-item[1], item[0]))[:count]
            result[name] = [{"value": v, "count": c} for v, c in ordered]
        return result

    def _ordered(
        self,
        fields: Mapping[str, Doc],
        matched: list[Doc],
        scores: Mapping[str, float],
        key: str,
        orderby: str | None,
    ) -> list[Doc]:
        clauses = [c.strip() for c in (orderby or "search.score() desc").split(",") if c.strip()]

        def sort_key(d: Doc) -> tuple:
            parts: list[Any] = []
            for clause in clauses:
                name, _, direction = clause.partition(" ")
                descending = direction.strip() == "desc"
                if name == "search.score()":
                    value: Any = scores[d[key]]
                else:
                    spec = fields.get(name)
                    if spec is None or not spec["sortable"]:
                        raise FakeError(400, f"The field '{name}' is not sortable")
                    value = d.get(name) or ""
                parts.append(_Reversed(value) if descending else value)
            parts.append(d[key])
            return tuple(parts)

        return sorted(matched, key=sort_key)


@dataclass(frozen=True, slots=True)
class _Reversed:
    """Sorts its value in descending order."""

    value: Any

    def __lt__(self, other: "_Reversed") -> bool:
        return self.value > other.value

    def __eq__(self, other: object) -> bool:
        return isinstance(other, _Reversed) and self.value == other.value

    def __hash__(self) -> int:
        return hash(self.value)


class _Adapter(BaseAdapter):
    """A ``requests`` transport adapter that answers from the fake service, no socket."""

    def __init__(self, service: FakeSearchService) -> None:
        super().__init__()
        self.service = service

    def send(
        self,
        request: requests.PreparedRequest,
        stream: bool = False,
        timeout: Any = None,
        verify: Any = True,
        cert: Any = None,
        proxies: Any = None,
    ) -> requests.Response:
        body = request.body
        data = body.encode() if isinstance(body, str) else body
        try:
            status, payload = self.service.handle(
                request.method or "GET", request.url or "", request.headers, data
            )
        except FakeError as error:
            status, payload = (
                error.status,
                {"error": {"code": error.code, "message": error.message}},
            )
        content = b"" if payload is None else json.dumps(payload).encode()
        response = requests.Response()
        response.status_code = status
        response.headers["Content-Type"] = "application/json; odata.metadata=minimal; charset=utf-8"
        response.headers["Content-Length"] = str(len(content))
        response.raw = urllib3.HTTPResponse(
            body=io.BytesIO(content),
            headers=dict(response.headers),
            status=status,
            preload_content=False,
        )
        response.url = request.url or ""
        response.request = request
        response.reason = "OK" if status < 400 else "Error"
        response.encoding = "utf-8"
        return response

    def close(self) -> None:
        """Nothing to release."""


def documents_of(service: FakeSearchService, index: str) -> Iterator[Doc]:
    """Every visible document of an index (pending writes applied first)."""
    service.flush()
    yield from service.visible(index).values()

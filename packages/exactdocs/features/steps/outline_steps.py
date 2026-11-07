"""Steps for outlines of a library whose chunking merges sections."""

from http import HTTPStatus

from behave import given, then
from behave.runner import Context

from steps.import_steps import LIBRARY, import_version, version_commit, wait_for_job
from steps.read_steps import INSTALL_OUTLINE, outline_nodes, outline_shape

# The anchors of docs/guide/install.md at v1.4.0, in document order (GitHub's slugs).
INSTALL_ANCHORS = [
    "guide",
    "install",
    "docker",
    "troubleshooting",
    "from-source",
    "troubleshooting-1",
]


@given('"/fixture/docs-repo" is imported at "{ref}" with min_chars {min_chars:d}')
def step_imported_merging(context: Context, ref: str, min_chars: int) -> None:
    import_version(context, ref, include_paths=["docs/"])
    assert context.job["state"] == "succeeded", context.job
    settings = context.client.get(f"/api/v1/libraries{LIBRARY}").json()["settings"]
    body = {
        "include_paths": settings["include_paths"],
        "exclude_paths": settings["exclude_paths"],
        "tag_rules": settings["tag_rules"],
        "chunking": settings["chunking"] | {"min_chars": min_chars},
    }
    response = context.client.put(f"/api/v1/libraries{LIBRARY}/settings", json=body)
    assert response.status_code == HTTPStatus.ACCEPTED, response.text
    job = wait_for_job(context, response.json()["job_id"])
    assert (job["kind"], job["state"]) == ("rechunk", "succeeded"), job
    context.commits = {ref: version_commit(context, ref)}


@then("every heading of the article is in the heading tree")
def step_every_heading(context: Context) -> None:
    result = context.mcp_result
    assert not result.is_error, result.content
    data = result.structured_content
    assert outline_shape(data["sections"]) == INSTALL_OUTLINE, data["sections"]
    assert [s["anchor"] for _, s in outline_nodes(data["sections"])] == INSTALL_ANCHORS, data
    assert data["chunks"] < len(INSTALL_ANCHORS), "the chunking merged some headings"


@then("a merged heading carries the chunk ID of the chunk that contains it and its own anchor")
def step_merged_heading(context: Context) -> None:
    nodes = outline_nodes(context.mcp_result.structured_content["sections"])
    merged = [(path, s) for path, s in nodes if not s["starts_chunk"]]
    assert merged, nodes
    starting = {s["chunk_id"]: path for path, s in nodes if s["starts_chunk"]}
    for path, section in merged:
        response = context.client.get(f"/api/v1/chunks/{section['chunk_id']}")
        assert response.status_code == HTTPStatus.OK, response.text
        chunk = response.json()
        assert chunk["article_path"] == context.read_path, chunk
        assert tuple(chunk["heading_path"]) == starting[section["chunk_id"]], (path, chunk)
        assert f"# {path[-1]}\n" in chunk["content"], (path, chunk["content"])
        assert section["anchor"] != chunk["anchor"], (path, chunk)

from types import SimpleNamespace as NS

from kbsync.chunking import CHUNKING_STRATEGY, estimate_chunks
from kbsync.vector_store import Doc, RemoteFile, VectorStoreSync, load_docs, plan_delta


def doc(aid, body="hello"):
    return Doc(aid, f"{aid}-x.md", f"# T{aid}\n\nArticle URL: https://h/{aid}\n\n{body}\n")


class FakeOpenAI:
    """Minimal stand-in for the parts of the OpenAI client we use."""

    def __init__(self, stores=()):
        self.stores = list(stores)
        self.vs_files = {}  # file_id -> attributes
        self.deleted = []
        self.uploads = []
        self.chunking = []
        fake = self

        class Files:
            def create(self, file, purpose):
                fid = f"file-{len(fake.uploads) + 1}"
                fake.uploads.append((fid, file[0]))
                return NS(id=fid)

            def delete(self, fid):
                fake.deleted.append(fid)

        class VSFiles:
            def list(self, vector_store_id, limit):
                return [NS(id=k, status="completed", attributes=v) for k, v in fake.vs_files.items()]

            def create_and_poll(self, vector_store_id, file_id, attributes, chunking_strategy):
                fake.vs_files[file_id] = attributes
                fake.chunking.append(chunking_strategy)
                return NS(id=file_id, status="completed")

            def delete(self, file_id, vector_store_id):
                fake.vs_files.pop(file_id)

        class VectorStores:
            files = VSFiles()

            def list(self, limit):
                return fake.stores

            def create(self, name, chunking_strategy):
                vs = NS(id="vs_new", name=name)
                fake.stores.append(vs)
                return vs

        self.files = Files()
        self.vector_stores = VectorStores()


def test_plan_delta_classifies_everything():
    a, b, c = doc("1"), doc("2"), doc("3")
    remote = [
        RemoteFile("f1", "1", a.content_hash),   # unchanged
        RemoteFile("f2", "2", "old-hash"),       # changed
        RemoteFile("f9", "9", "x"),              # gone from site
        RemoteFile("f1b", "1", a.content_hash),  # duplicate
    ]
    plan = plan_delta([a, b, c], remote)
    assert [d.article_id for d in plan.added] == ["3"]
    assert [(d.article_id, r.file_id) for d, r in plan.updated] == [("2", "f2")]
    assert [d.article_id for d in plan.skipped] == ["1"]
    assert sorted(r.file_id for r in plan.removed) == ["f1b", "f9"]
    assert "f9" not in [r.file_id for r in plan_delta([a, b, c], remote, prune=False).removed]


def test_first_run_uploads_all_then_second_run_skips_all():
    client = FakeOpenAI()
    sync = VectorStoreSync(client, name="kb")
    assert sync.vector_store_id == "vs_new"
    docs = [doc("1"), doc("2")]

    s1 = sync.sync(docs)
    assert (s1["added"], s1["updated"], s1["skipped"]) == (2, 0, 0)
    assert all(c == CHUNKING_STRATEGY for c in client.chunking)
    assert {v["article_id"] for v in client.vs_files.values()} == {"1", "2"}

    s2 = sync.sync(docs)
    assert (s2["added"], s2["updated"], s2["skipped"], s2["files_embedded"]) == (0, 0, 2, 0)
    assert len(client.uploads) == 2  # nothing re-uploaded


def test_update_replaces_old_file_and_prunes_removed():
    client = FakeOpenAI(stores=[NS(id="vs_old", name="kb")])
    sync = VectorStoreSync(client, name="kb")
    assert sync.vector_store_id == "vs_old"  # reuses store by name
    sync.sync([doc("1"), doc("2")])

    stats = sync.sync([doc("1", body="changed")])
    assert (stats["updated"], stats["removed"], stats["skipped"]) == (1, 1, 0)
    assert list(v["article_id"] for v in client.vs_files.values()) == ["1"]
    assert set(client.deleted) == {"file-1", "file-2"}


def test_load_docs_reads_id_url_title(tmp_path):
    (tmp_path / "360-how-to.md").write_text("# How to\n\nArticle URL: https://h/360\n\nbody\n")
    (d,) = load_docs(tmp_path)
    assert (d.article_id, d.url, d.title) == ("360", "https://h/360", "How to")
    assert d.attributes["content_hash"] == d.content_hash


def test_estimate_chunks():
    assert estimate_chunks("") == 0
    assert estimate_chunks("word " * 10) == 1
    long_text = "word " * 5000
    assert estimate_chunks(long_text) > estimate_chunks("word " * 2000) > 1

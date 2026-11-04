"""GithubRecipeRepo with RECIPES_FETCH=tarball: one archive download per run
instead of 3+ raw.githubusercontent.com requests per recipe. A recipe loaded
from the archive must be byte-identical to one fetched file by file (the
prechecks hash the recipe files), and the archive is untrusted input."""
from __future__ import annotations

import io
import tarfile
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from services.page_builder import refresh as rf
from services.page_builder.recipe import RecipeError
from services.page_builder.tests.test_map_snapshots import DS, _with_snapshot

TOP = "o-r-abc123"


def _tarball(recipes: Path, extra: list[tarfile.TarInfo | tuple[str, bytes]] = ()) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tar:
        pax = tarfile.TarInfo("pax_global_header")
        tar.addfile(pax, io.BytesIO(b""))
        for p in sorted(recipes.rglob("*")):
            if p.is_file():
                tar.add(p, arcname=f"{TOP}/recipes/{p.relative_to(recipes)}")
        readme = f"{TOP}/README.md".encode()
        tar.addfile(tarfile.TarInfo(readme.decode()), io.BytesIO(b""))
        for item in extra:
            if isinstance(item, tarfile.TarInfo):
                tar.addfile(item)
            else:
                name, data = item
                info = tarfile.TarInfo(name)
                info.size = len(data)
                tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class _R:
    def __init__(self, data=None, content=b""):
        self._data, self.content = data, content

    def json(self):
        return self._data

    def raise_for_status(self):
        pass


@pytest.fixture
def github(monkeypatch, tmp_path):
    """Fake GitHub: commits + trees API, the tarball endpoint, raw files."""
    recipes = _with_snapshot(tmp_path)
    state = {"tarball": _tarball(recipes), "calls": [], "status": 200}

    def _get(url, **kw):
        state["calls"].append(url)
        if url.endswith("/commits/main"):
            return _R({"sha": "abc123"})
        if "/git/trees/abc123" in url:
            return _R({"tree": [{"path": f"recipes/{p.relative_to(recipes)}"}
                                for p in recipes.rglob("*") if p.is_file()]})
        if url.startswith("https://raw.githubusercontent.com/o/r/abc123/recipes/"):
            rel = url.split("/recipes/", 1)[1]
            return _R(content=(recipes / rel).read_bytes())
        raise AssertionError(url)

    @contextmanager
    def _stream(method, url, **kw):
        state["calls"].append(url)
        assert method == "GET" and url == "https://api.github.com/repos/o/r/tarball/abc123"
        assert kw.get("follow_redirects") is True

        class S:
            def raise_for_status(self):
                if state["status"] != 200:
                    raise httpx.HTTPStatusError(
                        "boom", request=httpx.Request("GET", url),
                        response=httpx.Response(state["status"]),
                    )

            def iter_bytes(self):
                data = state["tarball"]
                for i in range(0, len(data), 4096):
                    yield data[i:i + 4096]

        yield S()

    monkeypatch.setattr(httpx, "get", _get)
    monkeypatch.setattr(httpx, "stream", _stream)
    state["recipes"] = recipes
    return state


def test_tarball_loads_byte_identical_recipes_with_one_download(github, tmp_path):
    tar_repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    assert tar_repo.list_ids() == [DS]
    a = tar_repo.load(DS, tmp_path / "a")
    tar_repo.load(DS, tmp_path / "a2")  # a second load downloads nothing
    tar_calls = list(github["calls"])
    assert sum("/tarball/" in c for c in tar_calls) == 1
    assert not any("raw.githubusercontent.com" in c for c in tar_calls)
    assert not any("/git/trees/" in c for c in tar_calls)  # the archive lists recipes

    files_repo = rf.GithubRecipeRepo("o/r", "main", fetch="files")
    b = files_repo.load(DS, tmp_path / "b")

    # Same files on disk, same bytes, same identity → no precheck invalidation
    # when prod switches modes.
    def listing(root):
        return {p.name: p.read_bytes() for p in root.iterdir()}

    assert listing(a.root) == listing(b.root)
    assert "geo.geojson" in listing(a.root)
    assert "coverage.json" not in listing(a.root)  # authoring-only, never loaded
    assert rf.recipe_identity(a) == rf.recipe_identity(b)


def test_tarball_source_config_reads_the_archive(github, tmp_path):
    (github["recipes"] / DS / "source.json").write_text(
        '{"provider": "boi_sdmx", "title": "t", "config": {}}', encoding="utf-8")
    github["tarball"] = _tarball(github["recipes"])
    repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    assert repo.provider_source_ids() == [DS]
    assert repo.source_config(DS).provider == "boi_sdmx"
    assert not any("raw.githubusercontent.com" in c for c in github["calls"])


def test_tarball_extracts_only_plain_recipe_files(github):
    link = tarfile.TarInfo(f"{TOP}/recipes/{DS}/evil.geojson")
    link.type, link.linkname = tarfile.SYMTYPE, "/etc/passwd"
    github["tarball"] = _tarball(github["recipes"], extra=[
        link,
        (f"{TOP}/recipes/{DS}/sub/deep.py", b"x"),        # nested: not a recipe file
        (f"{TOP}/services/x.py", b"x"),                  # outside recipes/
        (f"{TOP}/recipes/README.md", b"x"),              # not in a recipe dir
    ])
    repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    repo.list_ids()
    tree = repo._tree
    got = sorted(str(p.relative_to(tree)) for p in tree.rglob("*"))
    assert got == sorted([DS, *(f"{DS}/{p.name}" for p in (github["recipes"] / DS).iterdir())])
    assert not (tree / DS / "evil.geojson").exists()


def test_tarball_failure_fails_the_recipe_list_not_each_recipe(github):
    """A lazy failure would surface per recipe as `recipe_invalid` and open
    an authoring issue for every one; eager, it is `refresh_unavailable`."""
    github["status"] = 502
    repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    with pytest.raises(httpx.HTTPStatusError):
        repo.list_ids()


@pytest.fixture
def tmpdirs(monkeypatch, tmp_path):
    """mkdtemp under tmp_path, so the test can see what's left behind."""
    base = tmp_path / "tmp"
    base.mkdir()
    real = rf.tempfile.mkdtemp
    monkeypatch.setattr(rf.tempfile, "mkdtemp", lambda **kw: real(dir=base, **kw))
    return base


def test_tarball_size_fuse_leaves_nothing_behind(github, monkeypatch, tmpdirs):
    monkeypatch.setattr(rf.GithubRecipeRepo, "TARBALL_MAX_BYTES", 100)
    with pytest.raises(RuntimeError, match="exceeds"):
        rf.GithubRecipeRepo("o/r", "main", fetch="tarball").list_ids()
    assert list(tmpdirs.iterdir()) == []


def test_tarball_tree_is_removed_with_the_repo(github, tmpdirs):
    import gc

    repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    repo.list_ids()
    assert len(list(tmpdirs.iterdir())) == 1
    del repo
    gc.collect()
    assert list(tmpdirs.iterdir()) == []


def test_tarball_with_two_top_dirs_is_refused(github, tmpdirs):
    github["tarball"] = _tarball(github["recipes"], extra=[
        (f"other-top/recipes/{DS}/compute.py", b"print('not the pinned commit')"),
    ])
    with pytest.raises(RuntimeError, match="2 top-level dirs"):
        rf.GithubRecipeRepo("o/r", "main", fetch="tarball").list_ids()
    assert list(tmpdirs.iterdir()) == []


def test_tarball_missing_file_is_a_recipe_error(github, tmp_path):
    repo = rf.GithubRecipeRepo("o/r", "main", fetch="tarball")
    repo.list_ids()
    (repo._tree / DS / "compute.py").unlink()
    with pytest.raises(RecipeError, match="missing compute.py"):
        repo.load(DS, tmp_path / "s")


@pytest.mark.parametrize("value,mode", [(None, "files"), ("", "files"),
                                        ("tarball", "tarball"), (" TARBALL ", "tarball")])
def test_recipes_fetch_env(monkeypatch, value, mode):
    monkeypatch.delenv("RECIPES_SOURCE", raising=False)
    if value is None:
        monkeypatch.delenv("RECIPES_FETCH", raising=False)
    else:
        monkeypatch.setenv("RECIPES_FETCH", value)
    assert rf.recipe_repo_from_env().fetch == mode


def test_recipes_fetch_typo_fails_loudly(monkeypatch):
    monkeypatch.delenv("RECIPES_SOURCE", raising=False)
    monkeypatch.setenv("RECIPES_FETCH", "tarbal")
    with pytest.raises(ValueError, match="RECIPES_FETCH"):
        rf.recipe_repo_from_env()

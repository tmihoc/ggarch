"""SVG cache-key regression tests.

Postmortem (0.22.1): a renderer change shipped without a __version__ bump
and the Sphinx SVG cache kept serving the old SVGs -- the cache key had
no renderer-source component, so structural tests passed while the server
served stale diagrams. These tests pin the fix: the key now folds in a
content hash of ggarch's own source files.
"""
from ggarch import sphinxcontrib_ggarch as ext


def test_source_token_is_stable():
    # sha1 hex digest, identical on repeat calls (cached per process).
    t1 = ext._source_cache_token()
    assert len(t1) == 40
    assert ext._source_cache_token() == t1


def test_source_token_tracks_content(tmp_path):
    # Explicit dir bypasses the process cache: edits and new modules
    # must both flip the token; unchanged content must not.
    (tmp_path / "a.py").write_text("x = 1")
    (tmp_path / "b.py").write_text("y = 2")
    t1 = ext._source_cache_token(str(tmp_path))
    assert ext._source_cache_token(str(tmp_path)) == t1
    (tmp_path / "b.py").write_text("y = 3")
    t2 = ext._source_cache_token(str(tmp_path))
    assert t2 != t1
    (tmp_path / "c.py").write_text("z = 4")
    assert ext._source_cache_token(str(tmp_path)) != t2


def test_cache_key_flips_on_source_change(monkeypatch):
    # The regression class: identical code/view/version/mtime inputs must
    # produce a different cache file when ggarch source changes.
    b1 = ext._cache_basename("model code", "view", "light", "1.0")
    monkeypatch.setattr(ext, "_SOURCE_TOKEN", "deadbeef")
    b2 = ext._cache_basename("model code", "view", "light", "1.0")
    assert b2 != b1
    assert b2.startswith("ggarch-")


def test_cache_key_input_sensitivity():
    # Authoring edits (mtime), theme suffix and skip_legend still
    # differentiate cache files.
    b = ext._cache_basename("code", "v", "light", "1.0")
    assert ext._cache_basename("code", "v", "light", "2.0") != b
    assert ext._cache_basename("code", "v", "dark", "1.0") != b
    assert ext._cache_basename("code", "v", "light", "1.0", "L") != b

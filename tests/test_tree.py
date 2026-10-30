import copy

import pytest

from bookmark_fixer import tree
from bookmark_fixer.tree import Node


def build():
    """root
         bar/            a, b, sub/(c), d
         other/          e
    """
    root = Node(title="Bookmarks")
    nodes = {"root": root}

    def folder(name, parent):
        nodes[name] = Node(title=name, add_date="1", last_modified="1")
        tree.add_child(nodes[parent], nodes[name])

    def link(name, parent, url=None):
        nodes[name] = Node(title=name, url=url or f"https://{name}.example.com/")
        tree.add_child(nodes[parent], nodes[name])

    folder("bar", "root")
    link("a", "bar")
    link("b", "bar")
    folder("sub", "bar")
    link("c", "sub")
    link("d", "bar")
    folder("other", "root")
    link("e", "other")
    return nodes


def titles(folder):
    return [n.title for n in folder.children]


def test_add_child_sets_parent_and_touches_folder():
    n = build()
    bm = tree.new_bookmark("x", "https://x.com")
    tree.add_child(n["sub"], bm, 0)
    assert bm.parent is n["sub"]
    assert titles(n["sub"]) == ["x", "c"]
    assert n["sub"].last_modified != "1"


def test_add_child_rejects_bookmark_parent():
    n = build()
    with pytest.raises(ValueError):
        tree.add_child(n["a"], tree.new_bookmark("x", "https://x.com"))


def test_remove():
    n = build()
    tree.remove(n["sub"])
    assert titles(n["bar"]) == ["a", "b", "d"]
    assert n["sub"].parent is None


def test_move_to_other_folder_appends():
    n = build()
    tree.move([n["a"], n["c"]], n["other"])
    assert titles(n["other"]) == ["e", "a", "c"]
    assert titles(n["bar"]) == ["b", "sub", "d"]
    assert n["sub"].children == []


def test_move_within_same_parent_adjusts_index():
    n = build()
    # Drop a and b just before d (index 3 before the move).
    tree.move([n["a"], n["b"]], n["bar"], 3)
    assert titles(n["bar"]) == ["sub", "a", "b", "d"]


def test_move_down_to_end_of_same_parent():
    n = build()
    tree.move([n["a"]], n["bar"])
    assert titles(n["bar"]) == ["b", "sub", "d", "a"]


def test_move_rejects_folder_into_itself_or_descendant():
    n = build()
    with pytest.raises(ValueError):
        tree.move([n["bar"]], n["bar"])
    with pytest.raises(ValueError):
        tree.move([n["bar"]], n["sub"])
    # Nothing was changed by the failed moves.
    assert titles(n["root"]) == ["bar", "other"]
    assert titles(n["bar"]) == ["a", "b", "sub", "d"]


def test_move_ignores_children_of_moved_folders():
    n = build()
    tree.move([n["c"], n["sub"]], n["other"])
    assert titles(n["other"]) == ["e", "sub"]
    assert titles(n["sub"]) == ["c"]


def test_shift_up_and_down():
    n = build()
    assert tree.shift([n["d"]], -1)
    assert titles(n["bar"]) == ["a", "b", "d", "sub"]
    assert tree.shift([n["a"], n["b"]], 1)
    assert titles(n["bar"]) == ["d", "a", "b", "sub"]
    assert not tree.shift([n["d"]], -1)  # already first


def test_shift_contiguous_block_stops_at_edge():
    n = build()
    assert not tree.shift([n["a"], n["b"]], -1)
    assert titles(n["bar"]) == ["a", "b", "sub", "d"]


def test_sort_folder_folders_first_case_insensitive():
    n = build()
    n["a"].title = "Zeta"
    n["b"].title = "alpha"
    tree.sort_folder(n["bar"])
    assert titles(n["bar"]) == ["sub", "alpha", "d", "Zeta"]


def test_sort_folder_recursive():
    n = build()
    tree.add_child(n["sub"], tree.new_bookmark("a-first", "https://z.com"))
    tree.sort_folder(n["root"], recursive=True)
    assert titles(n["sub"]) == ["a-first", "c"]


@pytest.mark.parametrize("a, b", [
    ("https://Example.com/path/", "https://example.com/path"),
    ("HTTPS://EXAMPLE.COM", "https://example.com/"),
])
def test_normalize_url_equivalent(a, b):
    assert tree.normalize_url(a) == tree.normalize_url(b)


@pytest.mark.parametrize("a, b", [
    ("https://example.com/Path", "https://example.com/path"),
    ("https://example.com/?q=1", "https://example.com/?q=2"),
    ("http://example.com", "https://example.com"),
])
def test_normalize_url_distinct(a, b):
    assert tree.normalize_url(a) != tree.normalize_url(b)


def test_find_duplicates_groups_in_document_order():
    n = build()
    dup1 = tree.new_bookmark("a again", "https://A.example.com")
    dup2 = tree.new_bookmark("a third", "https://a.example.com/")
    tree.add_child(n["other"], dup1)
    tree.add_child(n["sub"], dup2)
    groups = tree.find_duplicates(n["root"])
    assert groups == [[n["a"], dup2, dup1]]


def test_counts_and_path():
    n = build()
    assert tree.counts(n["root"]) == (3, 5)
    assert tree.path_of(n["c"]) == "bar / sub"
    assert tree.path_of(n["bar"]) == ""


def test_deepcopy_snapshot_is_independent():
    n = build()
    snapshot = copy.deepcopy(n["root"])
    tree.move([n["a"]], n["other"])
    n["b"].title = "changed"
    bar = snapshot.children[0]
    assert titles(bar) == ["a", "b", "sub", "d"]
    assert bar.children[0].parent is bar
    # Ids survive the copy so expansion/selection can be restored by id.
    assert tree.find_by_id(snapshot, n["a"].id) is bar.children[0]

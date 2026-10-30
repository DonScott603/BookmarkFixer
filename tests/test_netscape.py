from pathlib import Path

import pytest

from bookmark_fixer import netscape, tree

SAMPLE_FILE = Path(__file__).resolve().parent.parent / "merged_bookmarks.html"

SMALL = """<!DOCTYPE NETSCAPE-Bookmark-file-1>
<!-- This is an automatically generated file.
     It will be read and overwritten.
     DO NOT EDIT! -->
<META HTTP-EQUIV="Content-Type" CONTENT="text/html; charset=UTF-8">
<TITLE>Bookmarks</TITLE>
<H1>Bookmarks</H1>
<DL><p>
    <DT><H3 ADD_DATE="1" LAST_MODIFIED="2" PERSONAL_TOOLBAR_FOLDER="true">Bookmarks bar</H3>
    <DL><p>
        <DT><A HREF="https://a.com/?x=1&amp;y=2" ADD_DATE="3" ICON="data:image/png;base64,AAAA">Tom &amp; Jerry &quot;Q&quot; &lt;tag&gt;</A>
        <DT><H3 ADD_DATE="4" LAST_MODIFIED="5">Empty</H3>
        <DL><p>
        </DL><p>
    </DL><p>
    <DT><A HREF="https://b.com/" ADD_DATE="6">Café – naïve</A>
</DL><p>
"""


def test_parse_small():
    root = netscape.parse(SMALL)
    bar, b = root.children
    assert bar.is_folder and bar.title == "Bookmarks bar"
    assert bar.extra_attrs == {"PERSONAL_TOOLBAR_FOLDER": "true"}
    assert (bar.add_date, bar.last_modified) == ("1", "2")
    a, empty = bar.children
    assert a.url == "https://a.com/?x=1&y=2"
    assert a.title == 'Tom & Jerry "Q" <tag>'
    assert a.icon == "data:image/png;base64,AAAA"
    assert empty.is_folder and empty.children == []
    assert b.title == "Café – naïve"
    assert a.parent is bar and bar.parent is root


def test_write_small_round_trips_exactly():
    assert netscape.write(netscape.parse(SMALL)) == SMALL


def test_written_new_items_are_escaped():
    root = tree.Node(title="Bookmarks")
    tree.add_child(root, tree.Node(title="<b>&\"'", url='https://x.com/?a="1"&b=2', add_date="7"))
    text = netscape.write(root)
    assert ('<DT><A HREF="https://x.com/?a=&quot;1&quot;&amp;b=2" ADD_DATE="7">'
            "&lt;b&gt;&amp;&quot;&#x27;</A>") in text
    again = netscape.parse(text).children[0]
    assert again.title == "<b>&\"'"
    assert again.url == 'https://x.com/?a="1"&b=2'


def test_save_and_load(tmp_path):
    path = tmp_path / "out.html"
    netscape.save(netscape.parse(SMALL), path)
    assert path.read_bytes().decode("utf-8") == SMALL
    assert netscape.load(path).children[1].title == "Café – naïve"


@pytest.mark.skipif(not SAMPLE_FILE.exists(), reason="merged_bookmarks.html not present")
def test_real_export_round_trips_exactly():
    original = SAMPLE_FILE.read_bytes().decode("utf-8").replace("\r\n", "\n")
    root = netscape.parse(original)
    assert tree.counts(root) == (71, 599)
    assert netscape.write(root) == original

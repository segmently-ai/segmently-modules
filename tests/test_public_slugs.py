"""This engine tree, scanned the way a release scans it (`tools/release.py` step 1): the
organisation of the publish repository appears only in the two public slugs — in the tracked
files and in the history. The release tests use a stand-in organisation on engine copies; this
test is the one that reads the real tree with the real slug."""
import unittest

from tests.plugin_helpers import ENGINE, load_tool


class PublicSlugsTest(unittest.TestCase):
    def test_this_tree_passes_the_organisation_scan(self):
        release, builder = load_tool("release"), load_tool("build_plugins")
        slug = builder.MARKETPLACE  # the publish repository: <org>/segmently-modules-plugins
        slugs = release.public_slugs(slug)
        self.assertEqual(sorted(slugs), sorted([slug, slug.split("/")[0] + "/segmently-modules"]))
        hits = release.org_hits(release.Repo(ENGINE, "engine"), slug.split("/")[0], slugs)
        self.assertEqual(hits, [])


if __name__ == "__main__":
    unittest.main()

"""The B runtime must not require another agent's home-directory skill install."""

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from b_ops.diagnose import ads


class PortableSpecialistTests(unittest.TestCase):
    def test_bundled_rules_load_without_home_skill(self):
        ads._specialist.cache_clear()
        with tempfile.TemporaryDirectory() as empty_home:
            with patch.dict(os.environ, {"AMAZON_ADS_SKILL_DIR": ""}):
                with patch.object(Path, "home", return_value=Path(empty_home)):
                    rules, views, digest = ads._specialist()
        ads._specialist.cache_clear()
        self.assertTrue(callable(rules.analyze_search_terms))
        self.assertTrue(callable(views.build_action_scopes))
        self.assertEqual(len(digest), 64)


if __name__ == "__main__":
    unittest.main()

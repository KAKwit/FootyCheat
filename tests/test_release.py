import unittest
from pathlib import Path

from footy_cheat import APP_ID

_ROOT = Path(__file__).resolve().parents[1]


class ReleaseTests(unittest.TestCase):
    def test_the_desktop_files_use_the_app_id(self):
        desktop = (_ROOT / "data" / f"{APP_ID}.desktop").read_text()
        metainfo = (_ROOT / "data" / f"{APP_ID}.metainfo.xml").read_text()
        manifest = (_ROOT / f"{APP_ID}.yml").read_text()
        icon = (
            _ROOT
            / "footy_cheat"
            / "assets"
            / "icons"
            / "hicolor"
            / "scalable"
            / "apps"
            / f"{APP_ID}.svg"
        )
        self.assertIn(f"Icon={APP_ID}", desktop)
        self.assertIn("Exec=footy-cheat", desktop)
        self.assertIn(f"<id>{APP_ID}</id>", metainfo)
        self.assertIn(f"<launchable type=\"desktop-id\">{APP_ID}.desktop</launchable>", metainfo)
        developer = APP_ID.rsplit(".", 1)[0]
        self.assertEqual(developer, developer.lower())
        self.assertIn(f'<developer id="{developer}">', metainfo)
        self.assertIn("<name>KAKwit</name>", metainfo)
        self.assertIn("https://github.com/KAKwit/FootyCheat", metainfo)
        self.assertIn('version="0.1.0"', metainfo)
        self.assertNotIn("<screenshots>", metainfo)
        self.assertIn(f"id: {APP_ID}", manifest)
        self.assertIn('runtime-version: "51"', manifest)
        self.assertIn("--share=network", manifest)
        self.assertTrue(icon.is_file())
        project = (_ROOT / "pyproject.toml").read_text()
        self.assertIn(f"data/{APP_ID}.desktop", project)
        self.assertIn(f"data/{APP_ID}.metainfo.xml", project)

    def test_the_shipped_crests_are_the_current_eighteen_clubs(self):
        logo_dir = _ROOT / "footy_cheat" / "assets" / "logos"
        shipped = sorted(int(path.stem) for path in logo_dir.glob("*.png"))
        self.assertEqual(shipped, list(range(1, 19)))
        for path in logo_dir.glob("*.png"):
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG"), path.name)
        self.assertFalse((logo_dir / "19.png").exists())
        notice = (logo_dir / "NOTICE").read_text()
        self.assertIn("Squiggle", notice)
        self.assertIn("GPL-3.0-or-later", notice)


if __name__ == "__main__":
    unittest.main()

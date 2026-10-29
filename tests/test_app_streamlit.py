"""Smoke test with the REAL Streamlit runtime (streamlit.testing.v1.AppTest).

Skipped automatically when Streamlit is not installed. Run it on your machine:
    pip install -r requirements.txt
    python -m unittest tests.test_app_streamlit -v
"""
import importlib.util
import os
import tempfile
import unittest
from pathlib import Path

APP = str(Path(__file__).resolve().parent.parent / "app.py")
HAS_STREAMLIT = importlib.util.find_spec("streamlit") is not None


@unittest.skipUnless(HAS_STREAMLIT, "streamlit is not installed")
class RealStreamlitSmokeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["STUDYPILOT_DATA_DIR"] = self.tmp.name

    def tearDown(self):
        os.environ.pop("STUDYPILOT_DATA_DIR", None)
        self.tmp.cleanup()

    def test_app_starts_and_demo_data_loads(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(APP, default_timeout=30).run()
        self.assertFalse(at.exception, at.exception)
        demo = next(b for b in at.sidebar.button if b.key == "load_demo")
        demo.click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(len(at.session_state.tasks), 6)

    def test_add_assignment_form(self):
        from streamlit.testing.v1 import AppTest
        at = AppTest.from_file(APP, default_timeout=30).run()
        at.text_input(key="new_name").set_value("Essay")
        at.text_input(key="new_subject").set_value("Literature")
        next(b for b in at.button if b.label == "Add assignment").click().run()
        self.assertFalse(at.exception, at.exception)
        self.assertEqual(len(at.session_state.tasks), 1)


if __name__ == "__main__":
    unittest.main()

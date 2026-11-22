import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient
from pydantic import ValidationError

from worker.media import Settings, sample_ranges
from worker.server import JobRequest, create_app
from worker.workflow import best_name, secondary_settings, tuning_settings


class WorkflowTests(unittest.TestCase):
    def test_tuning_runs_under_final_bitrate(self):
        with self.assertRaises(ValidationError):
            JobRequest(source="film.mkv", tuning_kbps=20000, expected_kbps=20000)

    def test_modes_precede_strength(self):
        modes = tuning_settings()
        self.assertEqual({s.mode for s in modes}, {1, 2, 3})
        self.assertEqual({s.strength for s in modes}, {1.0})
        secondary = secondary_settings(Settings(mode=3))
        self.assertEqual({s.mode for s in secondary}, {3})
        self.assertEqual({secondary[0].strength, secondary[1].strength}, {0.8, 1.2})
        self.assertTrue(all(settings.flags()[3].endswith(":0.00") for settings in secondary))

    def test_verification_ranges_do_not_overlap_tuning(self):
        for frame_count in (48, 149, 480, 72000):
            tuning = sample_ranges(frame_count, False)
            verification = sample_ranges(frame_count, True)
            self.assertEqual(len(tuning), len(verification))
            self.assertEqual(len(set().union(*(set(range(a,b+1)) for a,b in tuning + verification))),
                             (len(tuning) + len(verification)) * 24)
            self.assertLess(verification[-1][1], frame_count)

    def test_transparency_takes_precedence_over_severity(self):
        scores = {"a": {"verdict": "uncertain", "severity": 0},
                  "b": {"verdict": "transparent", "severity": 1}}
        self.assertEqual(best_name(scores, ["a", "b"]), "b")

    def test_worker_limits_sources_to_library_and_requires_token(self):
        with tempfile.TemporaryDirectory() as tmp, patch.dict(os.environ, {"OPENAI_API_KEY": "test"}):
            root = Path(tmp)
            library = root / "video"
            library.mkdir()
            (library / "film.mkv").touch()
            (root / "private.mkv").touch()
            app = create_app(library, library / "jobs", token="worker-secret")
            with TestClient(app) as client:
                self.assertEqual(client.get("/sources").status_code, 401)
                headers = {"Authorization": "Bearer worker-secret"}
                response = client.get("/sources", headers=headers)
                self.assertEqual(response.json(), {"sources": ["film.mkv"]})
                response = client.post("/jobs", headers=headers, json={
                    "source": "../private.mkv", "tuning_kbps": 17000, "expected_kbps": 20000,
                })
                self.assertEqual(response.status_code, 404)


if __name__ == "__main__":
    unittest.main()

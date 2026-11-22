import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from worker.cli import main


class TerminalTests(unittest.TestCase):
    def test_tune_uses_lower_bitrate_and_keeps_json_on_stdout(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "film.mkv"
            source.touch()

            def review(job, video):
                self.assertEqual(video, source.resolve())
                self.assertEqual(job.request.tuning_kbps, 18000)
                self.assertEqual(job.request.expected_kbps, 20000)
                return {"crf": 17, "sample_kbps": 19255}

            with (
                patch.dict(os.environ, {"OPENAI_API_KEY": "test-only"}),
                patch("worker.cli.Workflow", side_effect=lambda job, video: FakeRun(job, video, review)),
                contextlib.redirect_stdout(stdout),
                contextlib.redirect_stderr(stderr),
            ):
                code = main(["tune", str(source), "--expected-kbps", "20000",
                             "--work", str(Path(root) / "jobs"), "--json"])

            self.assertEqual(code, 0, stderr.getvalue())
            result = json.loads(stdout.getvalue())
            self.assertEqual(result["report"]["crf"], 17)
            self.assertTrue((Path(result["job_directory"]) / "job.json").is_file())
            self.assertIn("18,000 kb/s", stderr.getvalue())

    def test_invalid_crop_stops_before_encoding(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as raised:
            main(["tune", "film.mkv", "--expected-kbps", "20000", "--crop", "61,0,60,0"])
        self.assertEqual(raised.exception.code, 2)


class FakeRun:
    def __init__(self, job, video, review):
        self.job = job
        self.video = video
        self.review = review

    def run(self):
        return self.review(self.job, self.video)

from __future__ import annotations

from dataclasses import asdict, replace
from pathlib import Path

from .media import (
    FIXED, FRAMES_PER_REGION, Runner, Settings, color_tags, command_text,
    detect_crop, frame_types, frames_from_y4m, inspect_source, make_comparison,
    png_url, quote_avs, render_frame, sample_lines, sample_ranges, source_lines,
)
from .review import Reviewer


def tuning_settings() -> list[Settings]:
    anchor = Settings()
    return [
        anchor, replace(anchor, mode=1), replace(anchor, mode=3),
    ]


def secondary_settings(mode: Settings) -> list[Settings]:
    return [
        replace(mode, strength=0.8), replace(mode, strength=1.2),
        replace(mode, deblock="-1:-1"), replace(mode, deblock="1:1"),
        replace(mode, psy=0.8), replace(mode, psy=1.2),
    ]


def best_name(scored: dict, names: list[str]) -> str:
    return min(names, key=lambda name: (
        {"transparent": 0, "uncertain": 1, "visible_loss": 2}[scored[name]["verdict"]],
        scored[name]["severity"],
    ))


class Workflow:
    def __init__(self, job, source: Path):
        self.job = job
        self.source = source
        self.runner = Runner(job.directory, job.cancelled)
        self.reviewer = None
        self.video = {}
        self.base = []
        self.prepared = []
        self.completed = {}

    def stage(self, step: str, message: str, progress: float):
        self.runner.check()
        self.job.update(stage=step, message=message, progress=progress)

    def encode(self, name: str, script: Path, settings: Settings, bitrate=None, crf=None) -> Path:
        output = self.job.directory / f"{name}.mkv"
        args = [*self.base, *settings.flags()]
        producer = ["avs2yuv", str(script), "-o", "-"]
        if bitrate is not None:
            import os
            args += ["--bitrate", str(bitrate), "--stats", str(output.with_suffix(".stats"))]
            self.runner.run([producer, ["x264", *args, "--slow-firstpass", "--pass", "1",
                                        "--output", os.devnull, "-"]])
            args += ["--pass", "2"]
        else:
            args += ["--crf", str(crf)]
        self.runner.run([producer, ["x264", *args, "--output", str(output), "-"]])
        self.completed[name] = output
        return output

    def prepare(self, rate, length: int) -> tuple[list[int], str, str]:
        self.stage("source", "Measuring source borders and inspecting scan type", 0.08)
        tune = sample_ranges(length, False)
        base = source_lines(self.source, self.runner)
        normalize = f"AssumeFPS({rate.numerator}, {rate.denominator})"
        preview_base = [*base, "ConvertBits(8)", "ConvertToYUV420()", normalize]
        scan_y4m = self.runner.y4m(self.runner.avs("source-scan", sample_lines(preview_base, tune)))
        count = len(tune) * FRAMES_PER_REGION
        try:
            detected = detect_crop(scan_y4m, count, 24 if self.video.get("colour_range") != "Full" else 12)
            option = self.job.request.scan
            if option == "auto":
                images = []
                places = {i * FRAMES_PER_REGION + 12 for i in range(len(tune))}
                for _, width, height, raw in frames_from_y4m(scan_y4m, places):
                    frame = render_frame(width, height, raw, self.video)
                    w, h = min(width, 640), min(height, 384)
                    images.append(png_url(frame.crop(((width-w)//2, (height-h)//2, (width+w)//2, (height+h)//2))))
                metadata = " ".join(str(self.video.get(k, "")) for k in ("ScanType", "ScanOrder")).strip()
                self.runner.check()
                scan = self.reviewer.scan(images, metadata)
                declared_interlaced = any(t in metadata.lower() for t in ("interlac", "mbaff", "tff", "bff"))
                if scan["verdict"] == "combing" or (scan["verdict"] == "uncertain" and declared_interlaced):
                    option = "bff" if "bff" in metadata.lower() else "tff"
                else:
                    option = "progressive"
                scan_note = f"MediaInfo {metadata or 'unspecified'}. {scan['observation']}"
            else:
                scan_note = f"Scan mode selected in the job: {option}."
        finally:
            scan_y4m.unlink(missing_ok=True)
        crop = self.job.request.crop if self.job.request.crop is not None else detected
        width, height = int(self.video["Width"]), int(self.video["Height"])
        left, top, right, bottom = crop
        if any(n < 0 or n % 2 for n in crop) or width - left - right < 16 or height - top - bottom < 16:
            raise ValueError("Crop amounts must be even, nonnegative and leave at least a 16×16 image.")
        self.prepared = base[:]
        if option in ("tff", "bff"):
            import os
            plugin = os.environ.get("ENCODEASSISTANT_YADIF_PLUGIN")
            if plugin:
                self.prepared.insert(0, f"LoadPlugin({quote_avs(Path(plugin).resolve())})")
            self.prepared.append(f"Yadifmod2(mode=0, order={int(option == 'tff')})")
        self.prepared += ["ConvertBits(8)", "ConvertToYUV420()", normalize]
        if any(crop):
            self.prepared.append(f"Crop({left}, {top}, {-right}, {-bottom})")
        return crop, option, scan_note

    def review(self, script: Path, names: list[str], rate, count: int, stage: str, progress: float) -> tuple[dict, int, int]:
        shared = set.intersection(*(frame_types(self.runner, self.completed[n], rate, count) for n in names))
        if not shared:
            raise ValueError("The candidates have no shared interior B-frames. Use a longer source.")
        chosen = set()
        for offset in range(0, count, FRAMES_PER_REGION):
            available = [i for i in shared if offset <= i < offset + FRAMES_PER_REGION]
            if available:
                chosen.add(min(available, key=lambda i: abs(i - offset - FRAMES_PER_REGION // 2)))
        if len(chosen) < 2 and count > FRAMES_PER_REGION:
            raise ValueError("Too few source ranges contain shared B-frames for this comparison.")
        source_y4m = self.runner.y4m(script)
        try:
            sources = {i: render_frame(w, h, data, self.video)
                       for i, w, h, data in frames_from_y4m(source_y4m, chosen)}
        finally:
            source_y4m.unlink(missing_ok=True)
        if sources.keys() != chosen:
            raise ValueError("The source pipe did not contain all matched sample frames.")
        scores = {}
        for name in names:
            self.stage(stage, f"Visually comparing {name} on {len(chosen)} shared B-frame timestamps", progress)
            decode = self.runner.avs(f"decode-{name}", source_lines(self.completed[name], self.runner))
            video = self.runner.y4m(decode)
            try:
                panels = []
                for i, w, h, data in frames_from_y4m(video, chosen):
                    panel = make_comparison(sources[i], render_frame(w, h, data, self.video))
                    panel.save(self.job.directory / f"comparison-{name}-{i}.png")
                    panels.append((i, png_url(panel)))
                if len(panels) != len(chosen):
                    raise ValueError("The candidate pipe did not contain all matched frames.")
                scores[name] = self.reviewer.compare(panels)
            finally:
                video.unlink(missing_ok=True)
        return scores, len(shared), len(chosen)

    def run(self):
        self.stage("source", "Reading full-source MediaInfo", 0.03)
        self.video, rate, length = inspect_source(self.runner, self.source)
        if self.job.request.full_encode and self.video.get("FrameRate_Mode") == "VFR":
            raise ValueError("The worker's full encode uses a constant frame rate. Use a CFR source for full encoding.")
        self.reviewer = Reviewer()
        self.base = [*FIXED, *color_tags(self.video)]
        crop, scan, scan_note = self.prepare(rate, length)
        tune_ranges, verify_ranges = sample_ranges(length, False), sample_ranges(length, True)
        tune = self.runner.avs("tuning", sample_lines(self.prepared, tune_ranges))
        verify = self.runner.avs("verification", sample_lines(self.prepared, verify_ranges))
        tune_count, verify_count = len(tune_ranges)*FRAMES_PER_REGION, len(verify_ranges)*FRAMES_PER_REGION
        bitrate = self.job.request.tuning_kbps
        candidates = {}
        for settings in tuning_settings():
            name = f"aq-mode-{settings.mode}"
            self.stage("aq-mode", f"Encoding AQ mode {settings.mode} at {bitrate:,} kb/s", 0.17)
            self.encode(name, tune, settings, bitrate=bitrate)
            candidates[name] = settings
        mode_scores, _, _ = self.review(tune, list(candidates), rate, tune_count, "aq-mode", 0.24)
        mode_name = best_name(mode_scores, list(candidates))
        mode = candidates[mode_name]

        for i, settings in enumerate(secondary_settings(mode)):
            name = f"tuning-{i+1}"
            self.stage("tuning", f"Encoding tuning candidate {i+1} of 6", 0.29 + i * 0.026)
            self.encode(name, tune, settings, bitrate=bitrate)
            candidates[name] = settings
        secondary = [mode_name, *(f"tuning-{i+1}" for i in range(6))]
        scores, tune_shared, tune_inspected = self.review(tune, secondary, rate, tune_count, "tuning", 0.46)
        combined = replace(
            mode, strength=candidates[best_name(scores, [mode_name,"tuning-1","tuning-2"])].strength,
            deblock=candidates[best_name(scores, [mode_name,"tuning-3","tuning-4"])].deblock,
            psy=candidates[best_name(scores, [mode_name,"tuning-5","tuning-6"])].psy,
        )
        finalists = list(secondary)
        if combined not in (candidates[name] for name in finalists):
            self.stage("tuning", "Encoding the combined settings", 0.51)
            self.encode("combined", tune, combined, bitrate=bitrate)
            candidates["combined"] = combined
            finalists.append("combined")
            scores, tune_shared, tune_inspected = self.review(tune, finalists, rate, tune_count, "tuning", 0.53)
        locked_name = best_name(scores, finalists)
        locked = candidates[locked_name]

        verify_kbps = self.job.request.expected_kbps
        report = {
            "media": {k: self.video.get(k) for k in ("Width", "Height", "ScanType", "FrameRate", "colour_range",
                                                    "colour_primaries", "transfer_characteristics", "matrix_coefficients")},
            "crop": crop, "scan": scan, "scan_note": scan_note, "settings": asdict(locked),
            "tuning_kbps": bitrate, "tuning_shared_b_frames": tune_shared,
            "tuning_inspected_b_frames": tune_inspected, "model": self.reviewer.model,
            "aq_mode_reviews": mode_scores,
            "tuning_reviews": {name: {"settings": asdict(candidates[name]), **value} for name, value in scores.items()},
            "verification_kbps": verify_kbps,
        }
        self.stage("verification", f"Checking the locked settings at {verify_kbps:,} kb/s", 0.60)
        self.encode("verification-candidate", verify, locked, bitrate=verify_kbps)
        verification, _, _ = self.review(verify, ["verification-candidate"], rate, verify_count, "verification", 0.64)
        report["verification"] = verification["verification-candidate"]
        if report["verification"]["verdict"] != "transparent":
            report["message"] = "The two-pass verification did not establish transparency. Review the evidence before a CRF sweep."
            report["comparison_files"] = self.comparisons("verification-candidate")
            return report

        values = [16.0, 17.0, 17.5, 18.0]
        tested = {}

        def sweep(new_values):
            for crf in new_values:
                name = f"crf-{crf:g}"
                self.stage("crf", f"Encoding CRF {crf:g} with the locked settings", 0.72)
                tested[crf] = name
                self.encode(name, verify, locked, crf=crf)
            return self.review(verify, list(tested.values()), rate, verify_count, "crf", 0.83)

        reviews, shared, inspected = sweep(values)
        passes = [crf for crf, name in tested.items() if reviews[name]["verdict"] == "transparent"]
        if not passes:
            reviews, shared, inspected = sweep([12.0, 14.0, 15.0])
        elif max(passes) == max(tested):
            reviews, shared, inspected = sweep([19.0, 20.0, 22.0])
        passes = [crf for crf, name in tested.items() if reviews[name]["verdict"] == "transparent"]
        if passes:
            highest = max(passes)
            upper = min((v for v in tested if v > highest), default=highest)
            if upper - highest > 0.5:
                mid = (highest + upper) / 2
                reviews, shared, inspected = sweep([mid])
                passes = [crf for crf, name in tested.items() if reviews[name]["verdict"] == "transparent"]
        report.update(crf_reviews={str(crf): reviews[name] for crf, name in sorted(tested.items())},
                      crf_shared_b_frames=shared, crf_inspected_b_frames=inspected)
        if not passes:
            report["message"] = "The inspected CRF trials did not establish visual transparency."
            report["comparison_files"] = self.comparisons(tested[min(tested)])
            return report

        chosen = max(passes)
        name = tested[chosen]
        rate_info = self.runner.json([
            "ffprobe", "-v", "error", "-show_entries", "format=bit_rate", "-of", "json",
            str(self.completed[name]),
        ])
        movie = self.runner.avs("movie", self.prepared)
        report.update(
            crf=chosen, highest_test_value=max(tested),
            sample_kbps=int(rate_info["format"]["bit_rate"]) / 1000,
            command=command_text(str(movie), [*self.base, *locked.flags(), "--crf", str(chosen)],
                                 str(self.job.directory / "video.mkv")),
            script=movie.read_text(encoding="utf-8"), sample_file=self.completed[name].name,
            comparison_files=self.comparisons(name),
        )
        if self.job.request.full_encode:
            self.stage("full-encode", f"Encoding the full source at CRF {chosen:g}", 0.93)
            path = self.encode("video", movie, locked, crf=chosen)
            report["output_file"] = path.name
        return report

    def comparisons(self, name: str) -> list[str]:
        return [path.name for path in sorted(self.job.directory.glob(f"comparison-{name}-*.png"))]

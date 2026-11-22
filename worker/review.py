from __future__ import annotations

import json
import os

import httpx


REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["transparent", "visible_loss", "uncertain"]},
        "severity": {"type": "integer", "minimum": 0, "maximum": 100},
        "findings": {"type": "array", "items": {"type": "object", "properties": {
            "frame": {"type": "integer"},
            "category": {"type": "string", "enum": [
                "hair", "shadows", "faces", "background", "banding", "grain", "other",
            ]},
            "observation": {"type": "string"},
        }, "required": ["frame", "category", "observation"], "additionalProperties": False}},
        "summary": {"type": "string"},
    },
    "required": ["verdict", "severity", "findings", "summary"],
    "additionalProperties": False,
}
SCAN_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string", "enum": ["combing", "progressive", "uncertain"]},
        "observation": {"type": "string"},
    },
    "required": ["verdict", "observation"],
    "additionalProperties": False,
}

class Reviewer:
    def __init__(self):
        self.key = os.environ.get("OPENAI_API_KEY")
        if not self.key:
            raise RuntimeError("Set OPENAI_API_KEY on the encoding worker before running a job.")
        self.model = os.environ.get("ENCODEASSISTANT_MODEL", "gpt-6.2-sol")

    def request(self, instructions: str, inputs: list, name: str, schema: dict) -> dict:
        response = httpx.post(
            "https://api.openai.com/v1/responses",
            headers={"Authorization": f"Bearer {self.key}"},
            json={
                "model": self.model, "store": False,
                "instructions": instructions,
                "input": [{"role": "user", "content": inputs}],
                "text": {"format": {"type": "json_schema", "name": name, "strict": True, "schema": schema}},
            },
            timeout=180,
        )
        if response.is_error:
            try:
                message = response.json()["error"]["message"]
            except (ValueError, KeyError, TypeError):
                message = response.reason_phrase
            raise RuntimeError(f"OpenAI API {response.status_code}: {message}")
        result = response.json()
        for item in result.get("output", []):
            if item.get("type") == "message":
                for content in item.get("content", []):
                    if content.get("type") == "output_text":
                        return json.loads(content["text"])
        raise RuntimeError(f"The OpenAI API did not return a completed {name} verdict.")

    def scan(self, images: list[str], metadata: str) -> dict:
        inputs = [{"type": "input_text", "text": f"MediaInfo scan description: {metadata}. Inspect these source frames."}]
        inputs.extend({"type": "input_image", "image_url": image, "detail": "high"} for image in images)
        return self.request(
            "Inspect stills extracted without deinterlacing. Look for repeated one-line combing on "
            "moving edges. Choose uncertain when the evidence is inconclusive. Report the visible evidence.",
            inputs, "source_scan", SCAN_SCHEMA,
        )

    def compare(self, panels: list[tuple[int, str]]) -> dict:
        inputs = []
        for frame, image in panels:
            inputs.extend([
                {"type": "input_text", "text": f"Matched presentation frame {frame}."},
                {"type": "input_image", "image_url": image, "detail": "high"},
            ])
        result = self.request(
            "Assess whether a candidate x264 encode looks transparent on the inspected frames. "
            "Every panel shows the cropped source on the left and the candidate on the right, "
            "with a context thumbnail above paired native-pixel texture, shadow and center crops. "
            "The frames and regions are aligned. Compare visible fine hair, shadows, close-up skin, "
            "distant backgrounds, banding in smooth areas and matching grain. Require visible evidence "
            "before assigning loss. Use uncertain for subtle ambiguous differences. Severity is 0 for "
            "indistinguishable and 100 for severe degradation. Use only the supplied frame numbers, "
            "record concrete observations and describe results for these images only.",
            inputs, "encode_review", REVIEW_SCHEMA,
        )
        allowed_frames = {frame for frame, _ in panels}
        if any(finding["frame"] not in allowed_frames for finding in result["findings"]):
            raise RuntimeError("Visual review referenced a frame outside the inspected set.")
        return result

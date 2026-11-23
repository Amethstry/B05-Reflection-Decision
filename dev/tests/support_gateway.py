"""Scripted HTTP service for testing the support-ticket agent. No model inference."""

import argparse
import json
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Lock

TEST_MODEL = "b05-http-test-model"
TEST_TOKEN = "b05-local-test-token"
INITIAL = {"ticket-01": "account", "ticket-02": "account", "ticket-03": "schedule", "ticket-04": "other"}


def review_label(case_id, number, prior):
    if case_id == "ticket-01":
        return "materials"
    if case_id == "ticket-02":
        has_evidence = any(row["case_id"] == "ticket-01" and row["status"] == "verified" for row in prior)
        return "materials" if has_evidence else "other"
    if case_id == "ticket-04":
        return "account" if number >= 2 else "schedule"
    return "other"


class Gateway(BaseHTTPRequestHandler):
    faulted = set()
    fault_lock = Lock()

    def log_message(self, format, *args):
        pass

    def send_json(self, status, body, retry_after=None):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            if retry_after is not None:
                self.send_header("Retry-After", str(retry_after))
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            return

    def do_POST(self):
        if self.path != "/v1/chat/completions":
            self.send_json(404, {"error": "test route missing"})
            return
        if self.headers.get("Authorization") != f"Bearer {TEST_TOKEN}":
            self.send_json(401, {"error": "test token missing"})
            return
        try:
            request = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            if request["model"] != TEST_MODEL:
                raise ValueError
            data = json.loads(request["messages"][-1]["content"])
            stage = data["stage"]
            case_id = data["case"]["id"]
            if set(data["case"]) != {"id", "topic", "text", "features"}:
                raise ValueError
            keys = {"stage", "case", "labels"}
            prior = []
            number = 0
            feedback = None
            if stage == "review":
                keys |= {"round", "preliminary", "previous", "feedback", "prior_lessons"}
                if set(data["feedback"]) != {"correct", "incorrect_labels"}:
                    raise ValueError
                feedback = data["feedback"]["correct"]
                if any(label not in data["labels"] for label in data["feedback"]["incorrect_labels"]):
                    raise ValueError
                prior = data["prior_lessons"]
                number = data["round"]
                if any("expected_label" in row or row["status"] not in ("verified", "unverified") for row in prior):
                    raise ValueError
            elif stage != "initial":
                raise ValueError
            if set(data) != keys:
                raise ValueError
            response_format = request.get("response_format")
            if response_format is not None:
                schema = response_format["json_schema"]
                if schema["name"] != stage or schema["strict"] is not True:
                    raise ValueError
                if set(schema["schema"]["properties"]["label"]["enum"]) != set(data["labels"]):
                    raise ValueError
        except (ValueError, KeyError, IndexError, TypeError):
            self.send_json(400, {"error": "invalid test request"})
            return

        print(json.dumps({
            "stage": stage, "round": number, "case_id": case_id, "feedback": feedback,
            "prior_case_ids": [row["case_id"] for row in prior],
            "incorrect_labels": data.get("feedback", {}).get("incorrect_labels", []),
            "json_schema": response_format is not None,
        }), flush=True)

        if stage == "initial":
            result = {"label": INITIAL.get(case_id, "other"), "reason": "测试端点的预设初判。"}
        else:
            result = {
                "label": review_label(case_id, number, prior),
                "review": "测试端点的预设复核。",
                "knowledge": {
                    "problem": "识别请求中的主要症状。",
                    "lesson": "按主要症状区分类别。此文字由测试端点生成。",
                    "applies_when": "存在已记录的特征时。",
                },
            }

        if stage == "review" and case_id in ("test-retry-once", "test-resume-once"):
            with self.fault_lock:
                first = case_id not in self.faulted
                self.faulted.add(case_id)
            if first and case_id == "test-retry-once":
                self.send_json(503, {"error": "test retry"}, retry_after=0)
                return
            if first:
                time.sleep(0.4)
                self.send_json(429, {"error": "test checkpoint"}, retry_after=30)
                return
        if stage == "review" and case_id == "test-http-error":
            self.send_json(503, {"error": "test service failure"})
            return
        if stage == "review" and case_id == "test-timeout":
            time.sleep(0.5)
        content = json.dumps(result, ensure_ascii=False)
        if stage == "review" and case_id == "test-invalid-json":
            content = "invalid JSON from test gateway"
        elif response_format is None:
            fence = chr(96) * 3
            content = f"{fence}json\n{content}\n{fence}"
        self.send_json(200, {"choices": [{"message": {"content": content}}]})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    args = parser.parse_args()
    with ThreadingHTTPServer((args.bind, args.port), Gateway) as server:
        print(f"TEST_GATEWAY_PORT={server.server_port}", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()

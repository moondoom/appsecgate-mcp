#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


def _call(call_id, name, arguments):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": json.dumps(arguments)},
    }


class Handler(BaseHTTPRequestHandler):
    counter = 0

    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        messages = payload["messages"]
        latest = next((item for item in reversed(messages) if item["role"] == "tool"), None)
        if latest is None:
            name, arguments = "get_finding_batch", {"cursor": 0, "limit": 20}
        elif latest["name"] == "get_finding_batch":
            result = json.loads(latest["content"])
            verdicts = [
                {
                    "finding_id": item["finding_id"],
                    "verdict": "TRUE_POSITIVE",
                    "explanation": "Deterministic gate-test verdict",
                    "evidence": [],
                }
                for item in result.get("findings", [])
            ]
            name, arguments = "submit_verdicts", {"verdicts": verdicts}
        elif latest["name"] == "submit_verdicts":
            result = json.loads(latest["content"])
            pending = result.get("pending_total", 0)
            if pending:
                total = json.loads(messages[1]["content"])["inventory"]["total"]
                name, arguments = "get_finding_batch", {
                    "cursor": total - pending,
                    "limit": 20,
                }
            else:
                name = ""
        else:
            name, arguments = "submit_verdicts", {"verdicts": []}
        if name:
            type(self).counter += 1
            message = {
                "role": "assistant",
                "content": None,
                "tool_calls": [_call(f"mock-{self.counter}", name, arguments)],
            }
            finish_reason = "tool_calls"
        else:
            message = {"role": "assistant", "content": "All findings triaged"}
            finish_reason = "stop"
        response = {
            "id": "mock-completion",
            "object": "chat.completion",
            "created": 0,
            "model": payload["model"],
            "choices": [{"index": 0, "finish_reason": finish_reason, "message": message}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }
        encoded = json.dumps(response).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def log_message(self, format, *args):
        return


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=4001)
    args = parser.parse_args()
    ThreadingHTTPServer(("0.0.0.0", args.port), Handler).serve_forever()

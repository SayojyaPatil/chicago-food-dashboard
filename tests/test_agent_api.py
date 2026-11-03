"""The /agent/ask endpoint: streaming events, backend gate and rate limit."""

import json
import os
import unittest
from unittest.mock import patch

from fastapi.testclient import TestClient

from backend import main
from backend.agent import tools
from backend.agent.loop import Agent
from tests.fakes import FakeWarehouse, ScriptedModel, answer, call


def fake_agent():
    model = ScriptedModel([call("citywide_summary", year=2025), answer("72.1% passed in 2025.")])
    return Agent(model, tools.DATA_TOOLS, FakeWarehouse([{"pass_rate_pct": 72.1}]), "2026-11-01")


class AskEndpointTests(unittest.TestCase):
    def setUp(self):
        main._recent.clear()
        self.client = TestClient(main.app)

    def test_disabled_on_postgres_backend(self):
        with patch.dict(os.environ, {"DATA_BACKEND": "postgres"}):
            response = self.client.post("/agent/ask", json={"question": "pass rate?"})
        self.assertEqual(response.status_code, 503)

    def test_streams_tool_events_then_answer(self):
        with patch.dict(os.environ, {"DATA_BACKEND": "bigquery"}), \
             patch.object(main, "get_agent", side_effect=fake_agent):
            response = self.client.post("/agent/ask", json={"question": "Pass rate in 2025?"})
        self.assertEqual(response.status_code, 200)
        events = [json.loads(line) for line in response.text.splitlines()]
        self.assertEqual([e["type"] for e in events], ["tool_start", "tool_end", "answer"])
        self.assertEqual(events[-1]["answer"], "72.1% passed in 2025.")
        self.assertNotIn("tool_results", events[-1])

    def test_rate_limit(self):
        with patch.dict(os.environ, {"DATA_BACKEND": "bigquery"}), \
             patch.object(main, "get_agent", side_effect=fake_agent), \
             patch.object(main, "ASK_LIMIT", 2):
            codes = [self.client.post("/agent/ask", json={"question": "Pass rate in 2025?"})
                     .status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])



class AgentStartupFailureTests(unittest.TestCase):
    def test_returns_503_json_when_agent_cannot_start(self):
        main._recent.clear()
        client = TestClient(main.app)
        with patch.dict(os.environ, {"DATA_BACKEND": "bigquery"}), \
             patch.object(main, "get_agent", side_effect=RuntimeError("no credentials")):
            response = client.post("/agent/ask", json={"question": "Pass rate in 2025?"})
        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json()["detail"], "The agent is not available right now.")


if __name__ == "__main__":
    unittest.main()

"""GeminiSession parsing, using real SDK types and a fake client (no network)."""

import unittest

from google.genai import types

from backend.agent.model import GeminiModel
from backend.agent.tools import DATA_TOOLS


def response(*parts):
    return types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=list(parts)))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=120, candidates_token_count=15))


class FakeModels:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []

    def generate_content(self, model, contents, config):
        self.requests.append((model, list(contents), config))
        return self.responses.pop(0)


class FakeClient:
    def __init__(self, responses):
        self.models = FakeModels(responses)


class GeminiAdapterTests(unittest.TestCase):
    def test_function_call_round_trip(self):
        client = FakeClient([
            response(types.Part(function_call=types.FunctionCall(
                name="citywide_summary", args={"year": 2025}, id="c1"))),
            response(types.Part(text="Thinking...", thought=True),
                     types.Part(text="72.1% passed.")),
        ])
        session = GeminiModel(model="gemini-test", client=client).start("sys", DATA_TOOLS)
        first = session.send_user("pass rate 2025?")
        self.assertEqual(first.calls[0].name, "citywide_summary")
        self.assertEqual(first.calls[0].args, {"year": 2025})
        self.assertEqual(first.usage, {"input_tokens": 120, "output_tokens": 15})

        second = session.send_tool_results([(first.calls[0], {"rows": [{"pass_rate_pct": 72.1}]})])
        self.assertEqual(second.text, "72.1% passed.")  # thought text excluded
        self.assertEqual(second.calls, [])

        _, contents, config = client.models.requests[1]
        roles = [c.role for c in contents]
        self.assertEqual(roles, ["user", "model", "user"])
        self.assertEqual(contents[2].parts[0].function_response.name, "citywide_summary")
        declared = [f.name for f in config.tools[0].function_declarations]
        self.assertEqual(declared, [t.name for t in DATA_TOOLS])
        self.assertTrue(config.automatic_function_calling.disable)


if __name__ == "__main__":
    unittest.main()

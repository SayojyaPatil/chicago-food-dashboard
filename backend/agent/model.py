"""Model adapter: Gemini on Vertex AI with manual function calling.

The agent loop talks to a small session interface instead of the SDK directly:

    session = model.start(system_prompt, tools)
    reply = session.send_user("question")          -> Reply(text, calls)
    reply = session.send_tool_results([...])       -> Reply(text, calls)

The session keeps the SDK's own message objects so details the API needs on
the next turn (such as thought signatures on function calls) are preserved.
Tests replace this with a scripted fake.
"""

import os
from dataclasses import dataclass, field

DEFAULT_MODEL = os.getenv("AGENT_MODEL", "gemini-3.8-flash")
# Gemini 3 models think before answering. "low" keeps answers fast for a
# tool-using agent; set AGENT_THINKING=default to leave it to the model.
THINKING = os.getenv("AGENT_THINKING", "low").strip().lower()


@dataclass
class ToolCall:
    name: str
    args: dict
    id: str | None = None


@dataclass
class Reply:
    text: str = ""
    calls: list[ToolCall] = field(default_factory=list)
    usage: dict = field(default_factory=dict)


class GeminiModel:
    def __init__(self, model: str = DEFAULT_MODEL, client=None):
        self.model = model
        self._client = client

    @property
    def client(self):
        if self._client is None:
            from google import genai
            self._client = genai.Client(
                vertexai=True,
                project=os.environ.get("GCP_PROJECT"),
                location=os.getenv("VERTEX_LOCATION", "global"),
            )
        return self._client

    def start(self, system_prompt: str, tools: list) -> "GeminiSession":
        return GeminiSession(self, system_prompt, tools)


class GeminiSession:
    def __init__(self, model: GeminiModel, system_prompt: str, tools: list):
        from google.genai import types
        self.types = types
        self.model = model
        self.contents = []
        self.config = types.GenerateContentConfig(
            system_instruction=system_prompt,
            tools=[types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t.name, description=t.description,
                                          parameters_json_schema=t.parameters)
                for t in tools])],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
            max_output_tokens=2048,
        )
        if THINKING in ("minimal", "low", "medium", "high") and model.model.startswith("gemini-3"):
            self.config.thinking_config = types.ThinkingConfig(thinking_level=THINKING.upper())

    def _generate(self) -> Reply:
        response = self.model.client.models.generate_content(
            model=self.model.model, contents=self.contents, config=self.config)
        candidate = response.candidates[0] if response.candidates else None
        if candidate is None or candidate.content is None:
            return Reply(text="")
        self.contents.append(candidate.content)  # keep the native object
        calls, texts = [], []
        for part in candidate.content.parts or []:
            if part.function_call:
                calls.append(ToolCall(part.function_call.name,
                                      dict(part.function_call.args or {}),
                                      part.function_call.id))
            elif part.text and not getattr(part, "thought", False):
                texts.append(part.text)
        usage = {}
        if response.usage_metadata:
            usage = {"input_tokens": response.usage_metadata.prompt_token_count,
                     "output_tokens": response.usage_metadata.candidates_token_count}
        return Reply(text="".join(texts).strip(), calls=calls, usage=usage)

    def send_user(self, text: str) -> Reply:
        self.contents.append(self.types.Content(
            role="user", parts=[self.types.Part.from_text(text=text)]))
        return self._generate()

    def send_tool_results(self, results: list[tuple[ToolCall, dict]]) -> Reply:
        parts = [self.types.Part.from_function_response(name=call.name, response=payload)
                 for call, payload in results]
        self.contents.append(self.types.Content(role="user", parts=parts))
        return self._generate()

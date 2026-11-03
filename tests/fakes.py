"""Test doubles: a scripted model, a recording warehouse, a word-count embedder."""

import re
from collections import Counter

from backend.agent.model import Reply, ToolCall


class FakeWarehouse:
    def __init__(self, rows=None):
        self.rows = rows if rows is not None else [{"value": 1}]
        self.calls = []

    def table(self, name):
        return f"`test.ds.{name}`"

    def run(self, sql, params=None):
        self.calls.append((sql, params or {}))
        return list(self.rows)


class ScriptedSession:
    def __init__(self, replies, log):
        self.replies, self.log = list(replies), log

    def _next(self):
        return self.replies.pop(0) if self.replies else Reply(text="done")

    def send_user(self, text):
        self.log.append(("user", text))
        return self._next()

    def send_tool_results(self, results):
        self.log.append(("tools", results))
        return self._next()


class ScriptedModel:
    """Replays a fixed list of replies; records what the agent sent."""

    model = "scripted"

    def __init__(self, replies):
        self.replies, self.log, self.system = replies, [], None

    def start(self, system_prompt, tools):
        self.system = system_prompt
        self.tool_names = [t.name for t in tools]
        return ScriptedSession(self.replies, self.log)


def call(name, **args):
    return Reply(calls=[ToolCall(name, args)])


def answer(text):
    return Reply(text=text)


VOCAB = ["cold", "hot", "temperature", "41", "135", "hand", "wash", "sink",
         "pest", "rodent", "insects", "allergen", "label", "certificate", "manager"]


class WordEmbedder:
    def embed(self, texts, task):
        out = []
        for text in texts:
            words = Counter(re.findall(r"[a-z0-9]+", text.lower()))
            out.append([float(words[w]) + 0.01 for w in VOCAB])
        return out

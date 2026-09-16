"""Pluggable model backends for the prompt tuner.

A backend is any callable:  generate_fn(prompt_text) -> reply_text
"""

import json
import subprocess
import urllib.request


class StubGenerator:
    """TEST ONLY — deterministic canned replies for harness self-tests.

    Never use for a real evaluation: it knows the answers by construction.
    """

    def __init__(self, reply_fn):
        self._fn = reply_fn

    def __call__(self, prompt):
        return self._fn(prompt)


class CommandGenerator:
    """Pipes the prompt to a CLI model on stdin, reads stdout.

    Example: CommandGenerator(["ollama", "run", "qwen3:0.6b"])
    A non-zero exit or timeout raises, which the classifier turns into
    "unknown" (fail-closed).
    """

    def __init__(self, argv, timeout=180):
        self.argv = list(argv)
        self.timeout = timeout

    def __call__(self, prompt):
        p = subprocess.run(
            self.argv,
            input=prompt.encode("utf-8"),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
        )
        if p.returncode != 0:
            raise RuntimeError(
                "model exited %d: %s" % (p.returncode, p.stderr.decode("utf-8", "replace")[:200])
            )
        return p.stdout.decode("utf-8", "replace")


class HTTPGenerator:
    """OpenAI-compatible chat completions over stdlib urllib.

    Works with anything serving /v1/chat/completions (e.g. `ollama serve`).
    Greedy decoding (temperature 0), short replies — this is classification,
    not chat.
    """

    def __init__(self, base_url, model, api_key=None, timeout=180, max_tokens=16):
        self.url = base_url.rstrip("/") + "/chat/completions"
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.max_tokens = max_tokens

    def __call__(self, prompt):
        body = {
            "model": self.model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": self.max_tokens,
            "temperature": 0,
        }
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = "Bearer " + self.api_key
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode("utf-8"), headers=headers
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
        try:
            return data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, TypeError) as e:
            raise RuntimeError("unexpected chat-completions response: %s" % e)

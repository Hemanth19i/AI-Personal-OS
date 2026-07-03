"""Contract tests for the LLM abstraction (T3.3).

The Ollama backend is a system dependency covered by the injectable ``LLM``
protocol and the fakes used in the answering tests; these pin the contract.
"""

import unittest

from aipos.llm import LLM, OllamaLLM
from tests.llm_fakes import FailingLLM, FakeLLM


class LLMContractTests(unittest.TestCase):
    def test_ollama_llm_satisfies_protocol(self) -> None:
        self.assertIsInstance(OllamaLLM("llama3.1"), LLM)

    def test_fakes_satisfy_protocol(self) -> None:
        self.assertIsInstance(FakeLLM(), LLM)
        self.assertIsInstance(FailingLLM(), LLM)

    def test_construction_does_not_touch_backend(self) -> None:
        # Constructing must not import ollama, so the app loads without it.
        self.assertIsInstance(OllamaLLM("llama3.1", host="http://localhost:11434"), LLM)


if __name__ == "__main__":
    unittest.main()

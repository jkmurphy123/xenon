# llm_interface.py
import re
import random
from dataclasses import dataclass
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal, pyqtSlot

try:
    from llama_cpp import Llama
except Exception:  # package not present or failed to import
    Llama = None


@dataclass
class LLMConfig:
    model_path: str
    n_ctx: int = 4096
    n_threads: int = 4
    n_gpu_layers: int = 0   # set >0 if using cuBLAS build


class LLMInterface:
    """Thin wrapper around llama-cpp-python with a safe fallback."""
    def __init__(self, cfg: LLMConfig):
        self.cfg = cfg
        self._llm = None
        self._available = False
        if Llama is not None and cfg.model_path:
            try:
                self._llm = Llama(
                    model_path=cfg.model_path,
                    n_ctx=cfg.n_ctx,
                    n_threads=cfg.n_threads,
                    n_gpu_layers=cfg.n_gpu_layers,
                )
                self._available = True
            except Exception as e:
                print(f"[LLMInterface] Failed to load model: {e}")
        else:
            print("[LLMInterface] Llama not available; using dummy generator.")

    def available(self) -> bool:
        return self._available

    def generate(self, prompt: str, max_tokens: int = 512) -> str:
        if not self._available:
            return self._dummy_generate(prompt)
        try:
            out = self._llm(
                prompt=prompt,
                max_tokens=max_tokens,
                stop=["</END>", "###"],
                temperature=0.8,
                top_p=0.95,
            )
            return out["choices"][0]["text"].strip()
        except Exception as e:
            print(f"[LLMInterface] Generation error: {e}")
            return self._dummy_generate(prompt)

    def generate_topic(self) -> str:
        topic_prompt = (
            "You are a random topic generator. Return ONE short topic only (3-6 words), "
            "no punctuation, no quotes. Example: amusement parks\nTopic:"
        )
        raw = self.generate(topic_prompt, max_tokens=24)
        # sanitize to a short line
        line = re.sub(r"\s+", " ", raw).strip()
        line = re.sub(r"[^\w\s\-]", "", line)
        return line[:64] if line else random.choice([
            "amusement parks", "rainy sidewalks", "old libraries", "lost satellites"
        ])

    @staticmethod
    def _dummy_generate(prompt: str) -> str:
        seed = sum(ord(c) for c in prompt) % 1000
        random.seed(seed)
        samples = [
            "The mind wanders like a loose thread, catching on unrelated memories until a small story forms.",
            "I trace the edges of an idea and find it mirrors the ordinary: a kettle, a key, a cat in a sunbeam.",
            "Between cause and effect there is a hallway of choices; today I walk it slowly, counting the doors.",
        ]
        return "\n\n".join(random.sample(samples, k=len(samples)))


class LLMWorker(QObject):
    generated = pyqtSignal(str)
    status = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, llm: LLMInterface):
        super().__init__()
        self.llm = llm

    @pyqtSlot(str, int)
    def generate(self, prompt: str, max_tokens: int = 512):
        try:
            self.status.emit("Generating text…")
            text = self.llm.generate(prompt, max_tokens=max_tokens)
            self.generated.emit(text)
        except Exception as e:
            self.error.emit(str(e))

    @pyqtSlot()
    def gen_topic(self):
        try:
            self.status.emit("Choosing a topic…")
            topic = self.llm.generate_topic()
            self.generated.emit(topic)
        except Exception as e:
            self.error.emit(str(e))
## main.py
import os
import sys
import random
import re
from dataclasses import dataclass
from typing import List, Dict, Any

import yaml
from PyQt5.QtCore import QThread, QObject, pyqtSignal
from PyQt5.QtWidgets import QApplication

from ui_renderer import UIRenderer
from llm_interface import LLMInterface, LLMConfig, LLMWorker


# ----- Chunking -----
_SENT_RE = re.compile(r"(?<=[.!?])\s+")
# The above pattern is intentionally broken to remind us to fix it? No! We'll make it correct below.

# Correct sentence boundary splitter (kept separate to avoid accidental edits)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")


def split_into_sentence_chunks(text: str, max_words: int) -> List[str]:
    """Pack complete sentences into chunks up to ~max_words.
    If a single sentence exceeds max_words, hard-split it by words.
    """
    if not text:
        return []
    # Normalize whitespace
    t = re.sub(r"\s+", " ", text.strip())
    # Split into sentences using regex (keeps punctuation via lookbehind)
    sentences = re.split(r"(?<=[.!?])\s+", t)
    chunks = []
    cur = []
    cur_words = 0

    def flush():
        nonlocal cur, cur_words
        if cur:
            chunks.append(" ".join(cur).strip())
            cur = []
            cur_words = 0

    for s in sentences:
        w = s.split()
        if not w:
            continue
        if len(w) > max_words:
            # Hard split this long sentence
            flush()
            for i in range(0, len(w), max_words):
                chunks.append(" ".join(w[i:i+max_words]))
            continue
        if cur_words + len(w) <= max_words:
            cur.append(s)
            cur_words += len(w)
        else:
            flush()
            cur = [s]
            cur_words = len(w)
    flush()
    return chunks


# ----- Persona prompt builder -----

def build_prompt(persona: Dict[str, Any], topic: str) -> str:
    persona_txt = persona.get("prompt_persona", "").strip()
    style_rules = persona.get("style_rules", [])
    examples = persona.get("examples", [])

    rules = "\n".join(f"- {r}" for r in style_rules)
    ex = "\n".join(f"• {e}" for e in examples)

    # Simple instruction template (chatty but single-shot)
    return f"""
You adopt the following voice:
{persona_txt}

Style rules:
{rules}

Examples of the voice:
{ex}

Now, reflect in 2–4 paragraphs about the topic below in that voice. Do not include headings. Avoid bullet lists. Conclude with a crisp image or turn of phrase.

Topic: {topic}

</END>
""".strip()


# ----- App Controller -----
@dataclass
class PersonaState:
    persona: Dict[str, Any]
    topic: str = ""
    text: str = ""


class AppController(QObject):
    def __init__(self, cfg: Dict[str, Any], ui: UIRenderer, worker: LLMWorker):
        super().__init__()
        self.cfg = cfg
        self.ui = ui
        self.worker = worker

        self.persona_states: List[PersonaState] = []
        self._idx = -1
        self._awaiting = None  # 'topic' | 'text'

        # Wire signals
        self.worker.generated.connect(self._on_worker_generated)
        self.worker.status.connect(self.ui.show_status)
        self.worker.error.connect(self._on_worker_error)
        self.ui.chunkPlaybackFinished.connect(self._on_chunk_finished)

    def start(self):
        ui_cfg = self.cfg.get("ui", {})
        startup_img = os.path.join("assets", "startup.jpg")
        self.ui.set_background(startup_img if os.path.exists(startup_img) else None)
        self.ui.show_status("App started… Initializing LLM…")
        self._prepare_personas()
        self._next_persona()

    def _prepare_personas(self):
        plist = list(self.cfg.get("personalities", []))
        random.shuffle(plist)
        n = int(self.cfg.get("num_characters", 1))
        plist = plist[: max(1, n)]
        self.persona_states = [PersonaState(p) for p in plist]

    def _next_persona(self):
        self._idx += 1
        if self._idx >= len(self.persona_states):
            self.ui.show_status("All personas complete. Goodbye.")
            return
        st = self.persona_states[self._idx]
        p = st.persona
        # Background and balloon geometry
        img = os.path.join("assets", p.get("image_file_name", ""))
        self.ui.set_background(img if os.path.exists(img) else None)

        rect = p.get("speech_balloon", {"x_pos": 80, "y_pos": 80, "width": 864, "height": 560})
        self.ui.set_balloon_rect_design(rect.get("x_pos", 80), rect.get("y_pos", 80), rect.get("width", 864), rect.get("height", 560))

        self.ui.show_status(f"Persona: {p.get('display_name', p.get('name','?'))} — choosing topic…")
        self._awaiting = 'topic'
        self.worker.gen_topic()

    def _on_worker_generated(self, text: str):
        if self._awaiting == 'topic':
            st = self.persona_states[self._idx]
            st.topic = text if text else "amusement parks"
            self.ui.show_status(f"Topic: {st.topic} — generating monologue…")
            prompt = build_prompt(st.persona, st.topic)
            self._awaiting = 'text'
            self.worker.generate(prompt, max_tokens=700)
        elif self._awaiting == 'text':
            st = self.persona_states[self._idx]
            st.text = text
            # Show ready background (optional)
            ready = os.path.join("assets", "ready.jpg")
            if os.path.exists(ready):
                self.ui.set_background(ready)
            # Chunk & play
            mw = int(st.persona.get("max_words_per_chunk", 120))
            chunks = split_into_sentence_chunks(st.text, max(40, mw))
            self.ui.show_status(f"Displaying {len(chunks)} chunks…")
            self.ui.play_chunks(chunks)
            self._awaiting = None

    def _on_chunk_finished(self):
        self.ui.show_status("Persona finished. Moving on…")
        self._next_persona()

    def _on_worker_error(self, msg: str):
        self.ui.show_status(f"Error: {msg}")
        # Skip to next persona on error
        self._next_persona()


# ----- Entrypoint -----

def load_config(path: str) -> Dict[str, Any]:
    with open(path, 'r') as f:
        return yaml.safe_load(f) or {}


def main():
    cfg = load_config('config.yaml')

    app = QApplication(sys.argv)
    ui = UIRenderer(cfg.get('ui', {}))
    ui.show()

    # LLM init on main thread (reused in worker)
    llm_cfg = LLMConfig(
        model_path=cfg.get('model_path', ''),
        n_ctx=4096,
        n_threads=4,
        n_gpu_layers=0,
    )
    llm = LLMInterface(llm_cfg)

    # Long-lived worker thread
    thread = QThread()
    worker = LLMWorker(llm)
    worker.moveToThread(thread)
    thread.setObjectName('llm-worker')
    thread.start()

    ctrl = AppController(cfg, ui, worker)
    QTimer.singleShot(0, ctrl.start)

    rc = app.exec_()

    thread.quit()
    thread.wait(2000)
    sys.exit(rc)


if __name__ == '__main__':
    from PyQt5.QtCore import QTimer
    main()
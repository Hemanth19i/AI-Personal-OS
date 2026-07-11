"""Model evaluation harness for AI Personal OS (M7.1).

Benchmarks candidate local LLMs against the *real* pipeline — same ingest and
answer code paths, only the LLM model name changes (a config lever, no code
change; embeddings stay ``nomic-embed-text``). This is measurement tooling, not
part of the app: it only calls the public API surface, so it touches none of the
Architecture Freeze v1.0 boundaries.

The corpus is a coherent *fictional* company (``fixtures/fictional_company.pdf``).
Fictional entities force every model to answer from the retrieved context rather
than from pretraining, so this compares retrieval + reasoning, not memorised
facts. The three questions have known ground-truth answers, giving an objective
correctness check on top of the human-judged samples.

Usage (from the repo root, with the project venv):
    python benchmarks/benchmark_models.py llama3.2:3b qwen2.5:3b gemma3:4b
    python benchmarks/benchmark_models.py --regen-fixture   # rebuild the PDF

Quality is deliberately NOT scored automatically beyond correctness: extraction
and answer *quality* are shown as real samples in each results/<model>.md for a
human to judge. There is no honest offline quality score.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes
import io
import subprocess
import sys
import time
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

BENCH_DIR = Path(__file__).resolve().parent
REPO = BENCH_DIR.parent
FIXTURE = BENCH_DIR / "fixtures" / "fictional_company.pdf"
RESULTS = BENCH_DIR / "results"
sys.path.insert(0, str(REPO))

# The fictional corpus. Kept here so the fixture is regenerable and the
# ground-truth questions stay next to the text they are drawn from.
CORPUS = (
    "The Meridian Project was founded by Dr. Elena Vasquez at the Kestrel Institute in 2019. "
    "Elena Vasquez leads the research team. The team includes Marcus Chen, a specialist in vector "
    "databases, and Priya Nair, who designed the knowledge graph module. The Meridian Project builds "
    "an offline knowledge system called Lumen. Lumen uses a component named GraphCore, written by "
    "Priya Nair, to connect entities across documents. Marcus Chen maintains the VectorStore module, "
    "which depends on the Kestrel embedding model. The Kestrel Institute is located in Portland and "
    "collaborates with the Aurora Lab on privacy research. The Aurora Lab is directed by James Okafor. "
    "James Okafor previously worked with Elena Vasquez on a project called Beacon, which studied "
    "federated retrieval. GraphCore was inspired by Beacon's design. Lumen stores its documents using "
    "the VectorStore module and queries them through GraphCore. Priya Nair reports to Elena Vasquez. "
    "Marcus Chen and Priya Nair both joined the Kestrel Institute in 2020. The Aurora Lab provided the "
    "Kestrel embedding model to the Meridian Project under a research agreement signed in 2021. "
    "Lumen runs entirely offline and never sends user data to any external service. "
) * 3  # ~4.7k chars -> ~6 chunks

# (question, ground-truth substring that a correct answer must contain)
QUERIES = [
    ("Who designed the knowledge graph module?", "Priya Nair"),
    ("What does the VectorStore module depend on?", "Kestrel embedding model"),
    ("Who directs the Aurora Lab?", "Okafor"),
]


# ---------- OS measurement helpers (Windows) ----------
class _PMC(ctypes.Structure):
    _fields_ = [("cb", ctypes.wintypes.DWORD), ("PageFaultCount", ctypes.wintypes.DWORD),
        ("PeakWorkingSetSize", ctypes.c_size_t), ("WorkingSetSize", ctypes.c_size_t),
        ("QuotaPeakPagedPoolUsage", ctypes.c_size_t), ("QuotaPagedPoolUsage", ctypes.c_size_t),
        ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t), ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
        ("PagefileUsage", ctypes.c_size_t), ("PeakPagefileUsage", ctypes.c_size_t)]

_k32 = ctypes.windll.kernel32
_psapi = ctypes.windll.psapi
_k32.GetCurrentProcess.restype = ctypes.c_void_p
_psapi.GetProcessMemoryInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(_PMC), ctypes.wintypes.DWORD]
_psapi.GetProcessMemoryInfo.restype = ctypes.wintypes.BOOL


def app_peak_ws_mb() -> float:
    c = _PMC(); c.cb = ctypes.sizeof(c)
    if not _psapi.GetProcessMemoryInfo(_k32.GetCurrentProcess(), ctypes.byref(c), c.cb):
        return -1.0
    return c.PeakWorkingSetSize / 2**20


def gpu_mem_used_mb() -> float:
    try:
        out = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
        return float(out[0]) if out else -1.0
    except Exception:  # noqa: BLE001
        return -1.0


def ollama_proc_rss_mb() -> float:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
            "(Get-Process | Where-Object { $_.ProcessName -like '*ollama*' } |"
            " Measure-Object -Property WorkingSet64 -Sum).Sum"],
            capture_output=True, text=True, timeout=15).stdout.strip()
        return float(out) / 2**20 if out else -1.0
    except Exception:  # noqa: BLE001
        return -1.0


def processor_of(ps_line: str) -> str:
    """Extract the GPU/CPU split from an `ollama ps` line (e.g. '100% GPU').

    The processor tokens sit between the 'GB' size unit and the numeric context
    length: '... 2.2 GB 100% GPU 4096 ...' -> '100% GPU';
    '... 5.6 GB 25%/75% CPU/GPU 4096 ...' -> '25%/75% CPU/GPU'.
    """
    toks = ps_line.split()
    if "GB" not in toks:
        return "?"
    out = []
    for t in toks[toks.index("GB") + 1:]:
        if t.isdigit():  # reached the context-length column
            break
        out.append(t)
    return " ".join(out) or "?"


def ollama_ps_line(model: str) -> str:
    try:
        out = subprocess.run(["ollama", "ps"], capture_output=True, text=True, timeout=15).stdout
        for line in out.splitlines():
            if model.split(":")[0] in line:
                return " ".join(line.split())
        return "(model not resident)"
    except Exception as e:  # noqa: BLE001
        return f"(ollama ps failed: {e})"


# ---------- timing ----------
class Acc:
    def __init__(self): self.t = 0.0; self.n = 0
    def add(self, dt): self.t += dt; self.n += 1


class TExtractor:
    def __init__(self, inner, acc): self._i, self._a, self.first, self.errors = inner, acc, None, 0
    def extract(self, text):
        s = time.perf_counter()
        try:
            r = self._i.extract(text)
        except Exception:
            self.errors += 1
            raise
        self._a.add(time.perf_counter() - s)
        if self.first is None:
            self.first = (text, r)
        return r


class TEmbedder:
    def __init__(self, inner, acc): self._i, self._a = inner, acc
    def embed(self, texts):
        s = time.perf_counter(); r = self._i.embed(texts); self._a.add(time.perf_counter() - s); return r


class TLLM:
    def __init__(self, inner, acc): self._i, self._a = inner, acc
    def generate(self, p):
        s = time.perf_counter(); r = self._i.generate(p); self._a.add(time.perf_counter() - s); return r


@dataclass
class ModelResult:
    model: str
    status: str = ""
    chunks: int = 0
    ingest_total: float = 0.0
    extract_total: float = 0.0
    extract_calls: int = 0
    extract_errors: int = 0
    embed_total: float = 0.0
    entities: int = 0
    relationships: int = 0
    ps_line: str = ""
    gpu_mem_mb: float = 0.0
    app_peak_mb: float = 0.0
    ollama_rss_mb: float = 0.0
    sample_extraction: str = ""
    queries: list = field(default_factory=list)  # dicts

    @property
    def slug(self) -> str:
        return self.model.replace(":", "-").replace("/", "-")

    @property
    def extract_per_chunk(self) -> float:
        return self.extract_total / self.extract_calls if self.extract_calls else 0.0

    @property
    def embed_per_chunk(self) -> float:
        return self.embed_total / self.chunks if self.chunks else 0.0

    @property
    def query_avg(self) -> float:
        return sum(q["total"] for q in self.queries) / len(self.queries) if self.queries else 0.0

    @property
    def correct(self) -> int:
        return sum(1 for q in self.queries if q["correct"])


def regen_fixture() -> None:
    from tests.pdf_fixtures import make_text_pdf
    from pypdf import PdfReader, PdfWriter
    w = PdfWriter()
    w.add_page(PdfReader(io.BytesIO(make_text_pdf(CORPUS))).pages[0])
    FIXTURE.parent.mkdir(parents=True, exist_ok=True)
    with FIXTURE.open("wb") as fh:
        w.write(fh)
    print(f"wrote {FIXTURE} ({FIXTURE.stat().st_size} bytes)")


def eval_model(model: str) -> ModelResult:
    import aipos.ingest as ingest
    from aipos.answering import AnswerService
    from aipos.config import load_config
    from aipos.embedding import OllamaEmbedder
    from aipos.extraction import LLMEntityExtractor
    from aipos.graph_retrieval import GraphExpander, GraphRetriever, RoutedRetriever
    from aipos.hashing import sha256_file
    from aipos.intent import HeuristicIntentRouter
    from aipos.llm import OllamaLLM
    from aipos.ocr import TesseractOcr
    from aipos.reranking import LexicalReranker
    from aipos.retrieval import SemanticRetriever
    from aipos.storage import SQLiteStorage
    from aipos.vector_store import LanceVectorStore

    cfg = load_config(REPO)
    res = ModelResult(model=model)
    llm = OllamaLLM(model)
    try:
        llm.generate("Reply with the single word: ready")  # warm (exclude cold load)
    except Exception as e:  # noqa: BLE001
        res.status = f"SKIP (load failed: {e})"
        return res

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        pdf = root / "corpus.pdf"; pdf.write_bytes(FIXTURE.read_bytes())
        st = SQLiteStorage(root / "aipos.db"); st.connect()
        vs = LanceVectorStore(root / "vectors"); vs.connect()
        emb_a, ext_a = Acc(), Acc()
        embedder = TEmbedder(OllamaEmbedder(cfg.embedding_model), emb_a)
        extractor = TExtractor(LLMEntityExtractor(llm), ext_a)

        t0 = time.perf_counter()
        ingest.process_file(pdf, st, embedder, vs, TesseractOcr(), extractor)
        res.ingest_total = time.perf_counter() - t0

        res.gpu_mem_mb = gpu_mem_used_mb()
        res.ollama_rss_mb = ollama_proc_rss_mb()
        res.ps_line = ollama_ps_line(model)

        rec = st.get_file_by_hash(sha256_file(pdf))
        res.status = str(rec.status)
        res.chunks = len(st.get_chunk_records(rec.id))
        res.extract_total, res.extract_calls, res.extract_errors = ext_a.t, ext_a.n, extractor.errors
        res.embed_total = emb_a.t
        res.entities = len({e.name for e in st.get_edges()}) if False else 0
        res.relationships = len(st.get_edges())
        if extractor.first:
            ftext, fr = extractor.first
            lines = [f"entities ({len(fr.entities)}): " + ", ".join(
                f"{e.name}[{e.type}]" for e in fr.entities[:15])]
            lines.append(f"relationships ({len(fr.relationships)}):")
            lines += [f"  {r.source} --{r.relation}--> {r.target}" for r in fr.relationships[:12]]
            res.sample_extraction = "\n".join(lines)

        llm_a = Acc()
        semantic = SemanticRetriever(embedder, vs, st)
        graph = GraphRetriever(semantic, GraphExpander(st))
        retriever = RoutedRetriever(HeuristicIntentRouter(), semantic, graph)
        service = AnswerService(retriever, LexicalReranker(), TLLM(llm, llm_a), st)
        for q, truth in QUERIES:
            llm_a.t = 0.0
            t0 = time.perf_counter(); ans = service.answer(q); tot = time.perf_counter() - t0
            res.queries.append({
                "q": q, "answer": ans.answer.strip(), "total": tot, "llm_gen": llm_a.t,
                "grounded": ans.grounded, "cites": len(ans.sources),
                "strategy": ans.explanation.strategy,
                "correct": truth.lower() in ans.answer.lower(),
            })
        res.app_peak_mb = app_peak_ws_mb()
        st.close()
    return res


def write_model_md(r: ModelResult) -> None:
    RESULTS.mkdir(parents=True, exist_ok=True)
    q_rows = "\n".join(
        f"| {i+1} | {q['strategy']} | {q['total']:.2f}s | {q['llm_gen']:.2f}s | "
        f"{q['grounded']} | {q['cites']} | {'✅' if q['correct'] else '❌'} |"
        for i, q in enumerate(r.queries))
    samples = "\n\n".join(
        f"**Q{i+1}: {q['q']}**  \n_{q['total']:.2f}s · grounded={q['grounded']} · "
        f"correct={'✅' if q['correct'] else '❌'}_\n\n> {q['answer'][:600]}"
        for i, q in enumerate(r.queries))
    md = f"""# Model benchmark — `{r.model}`

_Fixture: `fixtures/fictional_company.pdf` · embeddings: nomic-embed-text · same pipeline, LLM swapped._

## Status
- ingest status: **{r.status}**, chunks: {r.chunks}, extraction errors: {r.extract_errors}

## Hardware / fit (while model resident)
- `ollama ps`: `{r.ps_line}`
- GPU memory used (total): {r.gpu_mem_mb:.0f} MiB
- Ollama server RSS: {r.ollama_rss_mb:.0f} MB
- Benchmark app-process peak WS: {r.app_peak_mb:.0f} MB

## Ingest
- total: **{r.ingest_total:.2f}s**  (PRD target for 100 pages: <10s)
- extraction: {r.extract_total:.2f}s over {r.extract_calls} calls = **{r.extract_per_chunk:.2f}s/chunk**
- embedding: {r.embed_total:.2f}s = {r.embed_per_chunk:.3f}s/chunk
- graph edges persisted: {r.relationships}

## Query  (avg total {r.query_avg:.2f}s · correctness {r.correct}/{len(r.queries)})
| # | strategy | total | llm_gen | grounded | cites | correct |
|---|---|---|---|---|---|---|
{q_rows}

## Sample extraction (chunk 0)
```
{r.sample_extraction}
```

## Sample answers (judge quality here)
{samples}
"""
    (RESULTS / f"{r.slug}.md").write_text(md, encoding="utf-8")
    print(f"  wrote results/{r.slug}.md")


def write_comparison(results: list[ModelResult]) -> None:
    rows = "\n".join(
        f"| `{r.model}` | {r.status} | {r.ingest_total:.1f}s | {r.extract_per_chunk:.2f}s | "
        f"{r.query_avg:.1f}s | {r.correct}/{len(r.queries)} | {r.relationships} | "
        f"`{processor_of(r.ps_line)}` |"
        for r in results)
    md = f"""# Model comparison — AI Personal OS (M7.1)

_Same pipeline, same fixture (`fixtures/fictional_company.pdf`), same 3 questions.
Only the LLM changed. Embeddings: nomic-embed-text throughout._

PRD targets: 100-page ingest <10s, query <2s. (This fixture is ~6 chunks, not 100
pages — use per-chunk extraction time to project, and see the T7.1 report for the
100-page arithmetic.)

| Model | status | ingest | extract/chunk | query avg | correct | edges | processor |
|---|---|---|---|---|---|---|---|
{rows}

Objective winners (measured):
- **Fastest ingest:** {min(results, key=lambda r: r.ingest_total).model}
- **Fastest query:** {min(results, key=lambda r: r.query_avg).model}
- **Most answers correct:** {max(results, key=lambda r: r.correct).model} ({max(r.correct for r in results)}/{len(QUERIES)})
- **Most relationships extracted:** {max(results, key=lambda r: r.relationships).model}

Quality (extraction depth, answer phrasing) is judged from the per-model sample
sections — see each `results/<model>.md`. This file is objective metrics only.
"""
    (RESULTS / "comparison.md").write_text(md, encoding="utf-8")
    print("  wrote results/comparison.md")


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    if "--regen-fixture" in args:
        regen_fixture()
        sys.exit(0)
    models = args or ["llama3.2:3b", "qwen2.5:3b", "gemma3:4b"]
    if not FIXTURE.exists():
        print("fixture missing; generating it first"); regen_fixture()
    print(f"Evaluating: {models}")
    results = []
    for m in models:
        print(f"\n=== {m} ===")
        r = eval_model(m)
        results.append(r)
        write_model_md(r)
        print(f"  status={r.status} ingest={r.ingest_total:.1f}s "
              f"extract/chunk={r.extract_per_chunk:.2f}s query_avg={r.query_avg:.1f}s "
              f"correct={r.correct}/{len(QUERIES)}")
    write_comparison(results)
    print("\nDONE")

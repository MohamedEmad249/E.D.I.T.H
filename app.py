import os

# ── Silence noisy loggers ────────────────────────────────────────────────────
os.environ["GRPC_VERBOSITY"] = "ERROR"
os.environ["GLOG_minloglevel"] = "2"
os.environ["GRPC_TRACE"] = ""
os.environ["HF_HUB_DISABLE_TELEMETRY"] = "1"
os.environ["HF_HUB_DISABLE_PROGRESS_BARS"] = "1"
os.environ["TOKENIZERS_PARALLELISM"] = "false"
os.environ["HF_HUB_ENABLE_HF_TRANSFER"] = "false"

import json
import re
import threading
import uuid
from pathlib import Path
from typing import Callable, Iterator, Optional
from collections import defaultdict
from dataclasses import dataclass

import httpx
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from dotenv import load_dotenv
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

import ingest

load_dotenv()

# ── Local LLM via Ollama ──────────────────────────────────────────────────────
# The model runs inside Ollama (llama.cpp, quantized) — much faster on CPU than
# PyTorch float32. Install Ollama, then:  ollama pull qwen2.5:1.5b-instruct
# Override with OLLAMA_MODEL / OLLAMA_URL in .env (LLM_MODEL is no longer used).
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:1.5b-instruct")
MAX_NEW_TOKENS = int(os.getenv("MAX_NEW_TOKENS", "384"))
NUM_CTX = int(os.getenv("NUM_CTX", "4096"))   # prompt + answer must fit in here

# CPU generation is slow and parallel requests just slow each other down,
# so run one generation at a time.
GENERATION_LOCK = threading.Lock()


class OllamaError(Exception):
    pass


def check_ollama() -> None:
    """Startup check: fail loudly (but don't crash) if Ollama/model is missing."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=5)
        names = [m.get("name", "") for m in r.json().get("models", [])]
        if not any(n == OLLAMA_MODEL or n.split(":")[0] == OLLAMA_MODEL for n in names):
            print(f"[warn] Model '{OLLAMA_MODEL}' not found in Ollama. Run:  ollama pull {OLLAMA_MODEL}")
        else:
            print(f"Ollama OK — using model '{OLLAMA_MODEL}' (num_ctx={NUM_CTX}, max_new_tokens={MAX_NEW_TOKENS})")
    except Exception as exc:
        print(f"[warn] Cannot reach Ollama at {OLLAMA_URL} ({exc}). Start Ollama before chatting.")


check_ollama()

embeddings = HuggingFaceEmbeddings(model_name=ingest.EMBEDDING_MODEL)

db = Chroma(persist_directory=ingest.PERSIST_DIR, embedding_function=embeddings)
os.makedirs(ingest.DATA_DIR, exist_ok=True)

UPLOAD_MAX_BYTES = int(os.getenv("UPLOAD_MAX_MB", "30")) * 1024 * 1024
INGEST_LOCK = threading.Lock()   # one upload/delete changes the vector store at a time

RETRIEVAL_K = 3                  # fewer chunks = smaller prompt = faster generation
# Measured on this corpus: real document questions score 0.32–0.71, unrelated ones
# 0.85+. 0.78 sits in the middle of that gap (check with GET /debug/retrieve?q=...).
RELEVANCE_DISTANCE_THRESHOLD = 0.78
# Summaries run once per source document (so documents never get blended):
SUMMARY_CHUNKS_PER_SOURCE = 6    # excerpts sampled per document
SUMMARY_CHUNK_CHARS = 900        # each excerpt is trimmed to this; keeps the prompt inside NUM_CTX
SUMMARY_MAX_TOKENS = 220         # per document

# ── Session store (kept in memory, saved to a JSON file so chats survive restarts) ──
# sessions: { session_id: [ {"role": "user"|"assistant", "content": str,
#                            "sources": [...]  (assistant turns only)} ] }
# Insertion order = least → most recently used.
SESSIONS_FILE = os.getenv("SESSIONS_FILE", "chat_sessions.json")
MAX_HISTORY_TURNS = 5      # turns sent to the model (keeps prompts small)
MAX_STORED_TURNS = 100     # turns kept per session for display / persistence
SESSIONS_LOCK = threading.Lock()


def load_sessions() -> tuple[dict[str, list[dict]], dict[str, str]]:
    """Returns (sessions, custom titles). Reads both the current file format
    {"sessions": {...}, "titles": {...}} and the older plain {session_id: turns}."""
    try:
        with open(SESSIONS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data.get("sessions"), dict):
            raw, titles = data["sessions"], data.get("titles") or {}
        else:
            raw, titles = data, {}
        chats = {sid: turns for sid, turns in raw.items() if isinstance(turns, list)}
        return chats, {sid: str(t) for sid, t in titles.items() if sid in chats}
    except FileNotFoundError:
        return {}, {}
    except Exception as exc:   # corrupt file: keep it for inspection, start fresh
        print(f"[warn] Could not read {SESSIONS_FILE} ({exc}); starting with no saved chats.")
        return {}, {}


def save_sessions() -> None:
    """Atomic write (temp file + rename) so a crash can't leave a half-written file."""
    with SESSIONS_LOCK:
        tmp = SESSIONS_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"sessions": sessions, "titles": session_titles}, f, ensure_ascii=False)
        os.replace(tmp, SESSIONS_FILE)


sessions, session_titles = load_sessions()   # session_titles: {session_id: renamed title}
print(f"Loaded {len(sessions)} saved chat(s) from {SESSIONS_FILE}")


# ── Stopping work in progress ────────────────────────────────────────────────
class StopHandle:
    """Lets another request stop a running generation: set the event and close
    the open Ollama connection (which also makes Ollama stop generating)."""
    def __init__(self) -> None:
        self.event = threading.Event()
        self.response: Optional[httpx.Response] = None

    @property
    def stopped(self) -> bool:
        return self.event.is_set()

    def stop(self) -> None:
        self.event.set()
        if self.response is not None:
            try:
                self.response.close()
            except Exception:
                pass


ACTIVE_CHATS: dict[str, StopHandle] = {}          # request_id → handle
UPLOAD_CANCELS: dict[str, threading.Event] = {}   # upload_id → cancel flag

# ── App ──────────────────────────────────────────────────────────────────────
app = FastAPI(title=f"E.D.I.T.H — {OLLAMA_MODEL}", version="4.0.0")

# Only the local frontend may call the API from a browser (override with CORS_ORIGINS=a,b).
CORS_ORIGINS = [o.strip() for o in os.getenv(
    "CORS_ORIGINS", "http://127.0.0.1:5173,http://localhost:5173").split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Schemas ──────────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    question: str
    session_id: Optional[str] = None   # omit to start a new session
    sources: Optional[list[str]] = None   # PDF file names to answer from; omit = all documents
    request_id: Optional[str] = None      # client-chosen id, used by POST /chat/stop


class StopRequest(BaseModel):
    request_id: str


class RenameRequest(BaseModel):
    title: str


class ChatResponse(BaseModel):
    session_id: str
    answer: str
    sources: list[dict]                 # [{content, page, source}]
    history_length: int


class SessionClear(BaseModel):
    session_id: str


# ── Prompts ──────────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """You are a helpful study assistant. The student has uploaded their \
study documents and you help them understand and learn the material.

How to behave:
1. When the question relates to the document context provided, answer primarily \
from that context — explain it clearly, use examples, and make it easy to understand.
2. When the message says no relevant document content was found, answer directly \
from your general knowledge, helpfully and accurately. Do NOT say the topic is \
missing from the documents — the app already tells the student that.
3. You MAY use prior conversation turns to follow up on previous topics naturally.
4. Be conversational and encouraging — you are a tutor, not a search engine.
5. Use markdown where it aids clarity (bullet points, bold terms, simple formulas).
6. Keep answers focused and concise — a student's time is valuable. Aim for under \
150 words unless the student asks to go deeper. Avoid long tables and long \
step-by-step calculations; give one short example instead."""


SUMMARY_SYSTEM_PROMPT = """You are a document summarization assistant. You will be \
given several excerpts from a document, separated by "---". Each excerpt is a \
distinct section or slide.

Your task: write ONE bullet point per excerpt, covering ALL excerpts given — \
not just the ones that seem most important. Write exactly as many bullets as \
there are excerpts. Do not skip any. Do not merge multiple excerpts into one bullet.

Rules:
1. Output ONLY the bullet list. Do not restate the instruction, do not say \
"Here is a summary", do not describe what you are about to do.
2. Each bullet should be one short sentence naming that excerpt's specific \
topic and its key point.
3. Base every bullet only on its corresponding excerpt — do not add outside \
information.
4. It is fine if some bullets are very short — brevity is better than skipping \
an excerpt."""


def build_summary_messages(context: str, n_excerpts: int) -> list[dict]:
    return [
        {"role": "system", "content": SUMMARY_SYSTEM_PROMPT},
        {"role": "user", "content": (
            f"Document excerpts ({n_excerpts} in total):\n{context}\n\n"
            f"Bullet summary ({n_excerpts} bullets, one per excerpt):")},
    ]


def build_messages(question: str, context: str | None, history: list[dict]) -> list[dict]:
    """Build a chat-template message list: system + prior turns + current turn.

    context=None means the question scored below the relevance threshold —
    the model should answer from general knowledge and flag it.
    History is stored as clean question/answer pairs (no stale context baked in).
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]

    for turn in history[-MAX_HISTORY_TURNS * 2:]:
        messages.append({"role": turn["role"], "content": turn["content"]})

    if context:
        user_content = (
            f"Study document context:\n{context}\n\n"
            f"Student question: {question}"
        )
    else:
        user_content = (
            f"[No relevant content found in the student's documents for this question. "
            f"Answer from general knowledge without mentioning the documents.]\n\n"
            f"Student question: {question}"
        )

    messages.append({"role": "user", "content": user_content})
    return messages


# ── Ollama calls ─────────────────────────────────────────────────────────────
def _ollama_payload(messages: list[dict], max_new_tokens: int, stream: bool) -> dict:
    return {
        "model": OLLAMA_MODEL,
        "messages": messages,
        "stream": stream,
        "keep_alive": "30m",   # keep the model loaded between questions
        "options": {
            "num_ctx": NUM_CTX,
            "num_predict": max_new_tokens,
            "temperature": 0,  # greedy: most faithful for RAG
        },
    }


def stream_answer(messages: list[dict], max_new_tokens: int = MAX_NEW_TOKENS,
                  info: Optional[dict] = None,
                  stop: Optional[StopHandle] = None) -> Iterator[str]:
    """Yield the answer piece by piece as Ollama generates it.
    If `info` is given, info["truncated"] is set when the token limit cut the answer off.
    If `stop` is given, stop.stop() ends the generation early (no error raised)."""
    with GENERATION_LOCK:
        if stop and stop.stopped:
            return
        try:
            with httpx.stream(
                "POST", f"{OLLAMA_URL}/api/chat",
                json=_ollama_payload(messages, max_new_tokens, True),
                timeout=httpx.Timeout(900, connect=5),
            ) as r:
                if stop:
                    stop.response = r
                if r.status_code != 200:
                    r.read()
                    if r.status_code == 404:
                        raise OllamaError(f"Model '{OLLAMA_MODEL}' not found. Run:  ollama pull {OLLAMA_MODEL}")
                    raise OllamaError(f"Ollama returned HTTP {r.status_code}: {r.text[:200]}")
                for line in r.iter_lines():
                    if stop and stop.stopped:
                        break
                    if not line:
                        continue
                    data = json.loads(line)
                    if data.get("error"):
                        raise OllamaError(data["error"])
                    piece = (data.get("message") or {}).get("content", "")
                    if piece:
                        yield piece
                    if data.get("done"):
                        if info is not None:
                            info["truncated"] = data.get("done_reason") == "length"
                        break
        except httpx.ConnectError:
            raise OllamaError(f"Cannot reach Ollama at {OLLAMA_URL}. Is Ollama running?")
        except Exception as exc:
            # Closing the connection from stop() makes the read fail: that's the
            # stop working, not an error.
            if stop and stop.stopped:
                return
            if isinstance(exc, (OllamaError, GeneratorExit)):
                raise
            raise OllamaError(f"Lost the connection to Ollama: {exc}")
        finally:
            if stop:
                stop.response = None


# ── Request preparation (shared by /chat and /chat/stream) ───────────────────
NOT_COVERED_PREFIX = "This isn't covered in your documents, but:\n\n"

# Words that mean "this question refers to what we were just talking about".
FOLLOWUP_WORDS = {
    "it", "its", "this", "that", "these", "those", "they", "them", "their",
    "above", "previous", "earlier", "more", "again", "another", "else",
}


def retrieval_query(question: str, history: list[dict]) -> str | None:
    """For follow-ups ("give an example of it") return the previous user question
    joined with this one, so the vector search knows what "it" is. Returns None
    when the question stands on its own."""
    last_user = next((t["content"] for t in reversed(history) if t["role"] == "user"), None)
    if not last_user:
        return None
    words = re.findall(r"[a-z']+", question.lower())
    if len(words) <= 3 or FOLLOWUP_WORDS.intersection(words):
        return f"{last_user}\n{question}"
    return None


def selected_sources(names: Optional[list[str]]) -> Optional[list[str]]:
    """File names from the client → the 'source' values stored in the vector DB.
    None means "no restriction" (all documents)."""
    if names is None:
        return None
    return [ingest.source_key(Path(n.replace("\\", "/")).name) for n in names if n]


def retrieve(question: str, history: list[dict], only: Optional[list[str]] = None):
    """Return (route, results, query_used). route is "doc" or "general".
    `only` restricts the search to those sources (an empty list = no documents)."""
    if only is not None and not only:
        return "general", [], question
    flt = {"source": {"$in": only}} if only is not None else None
    results = db.similarity_search_with_score(question, k=RETRIEVAL_K, filter=flt)
    query_used = question

    followup_query = retrieval_query(question, history)
    if followup_query:
        alt = db.similarity_search_with_score(followup_query, k=RETRIEVAL_K, filter=flt)
        if alt and (not results or alt[0][1] < results[0][1]):
            results, query_used = alt, followup_query

    if results and results[0][1] <= RELEVANCE_DISTANCE_THRESHOLD:
        return "doc", results, query_used
    return "general", results, query_used


def clean_bullet(line: str) -> str | None:
    """Keep only bullet lines (the small model sometimes invents headings)."""
    m = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.*\S)\s*$", line)
    return f"- {m.group(1)}" if m else None


def bullet_stream(pieces: Iterator[str], info: dict) -> Iterator[str]:
    """Re-emit model output one complete, cleaned bullet line at a time.
    A final line cut off by the token limit is dropped instead of shown half-written."""
    buf = ""
    for piece in pieces:
        buf += piece
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            bullet = clean_bullet(line)
            if bullet:
                yield bullet + "\n"
    if buf.strip() and not info.get("truncated"):
        bullet = clean_bullet(buf)
        if bullet:
            yield bullet + "\n"


def summary_stream(jobs: list[tuple[str, list[str]]],
                   stop: Optional[StopHandle] = None) -> Iterator[str]:
    """One short section per source document, each summarised separately so the
    model never blends unrelated documents together."""
    for title, texts in jobs:
        if stop and stop.stopped:
            return
        yield f"**{title}**\n\n"
        context = "\n\n---\n\n".join(t[:SUMMARY_CHUNK_CHARS] for t in texts)
        info: dict = {}
        pieces = stream_answer(build_summary_messages(context, len(texts)),
                               SUMMARY_MAX_TOKENS, info, stop)
        yield from bullet_stream(pieces, info)
        yield "\n"


def answer_stream(messages: list[dict], prefix: str = "",
                  stop: Optional[StopHandle] = None) -> Iterator[str]:
    if prefix:
        yield prefix
    info: dict = {}
    yield from stream_answer(messages, MAX_NEW_TOKENS, info, stop)
    if info.get("truncated"):
        yield "\n\n*(The answer was cut off — ask me to continue.)*"


@dataclass
class Prepared:
    session_id: str
    question: str
    sources: list[dict]
    route: str                              # "doc" | "general" | "summary"
    # generate(stop) yields the answer text piece by piece
    generate: Callable[[Optional[StopHandle]], Iterator[str]]


NO_DOCS_SELECTED_PREFIX = "No documents are selected, so this is from general knowledge:\n\n"


def prepare(req: ChatRequest) -> Prepared:
    session_id = req.session_id or str(uuid.uuid4())
    history = sessions.get(session_id, [])
    only = selected_sources(req.sources)     # None = all documents

    # ── Summary path ─────────────────────────────────────────────────────────
    if is_summary_request(req.question):
        all_docs = db.get()
        all_texts = all_docs.get("documents") or []
        all_metas = all_docs.get("metadatas") or []

        if not all_texts:
            raise HTTPException(status_code=404, detail="No document content available.")

        by_source: dict[str, list[int]] = defaultdict(list)
        for idx, meta in enumerate(all_metas):
            source = (meta or {}).get("source", "unknown")
            if only is None or source in only:
                by_source[source].append(idx)

        if not by_source:
            raise HTTPException(status_code=400,
                                detail="Select at least one document to summarize.")

        jobs: list[tuple[str, list[str]]] = []
        sources: list[dict] = []
        for source, idx_list in by_source.items():
            idx_list = sorted(idx_list)
            n = len(idx_list)
            if n <= SUMMARY_CHUNKS_PER_SOURCE:
                picked = idx_list
            else:   # evenly spaced through the document
                step = n / SUMMARY_CHUNKS_PER_SOURCE
                picked = [idx_list[int(i * step)] for i in range(SUMMARY_CHUNKS_PER_SOURCE)]
            title = Path(source).stem
            jobs.append((title, [all_texts[i] for i in picked]))
            sources.extend(
                {"content": all_texts[i][:300], "page": (all_metas[i] or {}).get("page", "unknown"),
                 "source": source}
                for i in picked
            )

        print(f"[summary] total_chunks={len(all_texts)} sources={len(jobs)} sampled={len(sources)}")
        return Prepared(session_id, req.question, sources, "summary",
                        lambda stop=None: summary_stream(jobs, stop))

    # ── Relevance check — soft router, not a hard block ───────────────────────
    # Good match → answer from the document. No good match → still answer, but
    # from general knowledge, with a notice that we add ourselves (a 1.5B model
    # doesn't reliably follow "start with this sentence").
    route, results, query_used = retrieve(req.question, history, only)
    best = results[0][1] if results else float("nan")
    print(f"[relevance] q={req.question!r} best={best:.4f} route={route}"
          f"{' (follow-up query)' if query_used != req.question else ''}")

    if route == "doc":
        context = "\n\n---\n\n".join(doc.page_content for doc, _ in results)
        sources = [
            {
                "content": doc.page_content[:300],
                "page": (doc.metadata or {}).get("page", "unknown"),
                "source": (doc.metadata or {}).get("source", "unknown"),
            }
            for doc, _ in results
        ]
        prefix = ""
    else:
        context, sources = None, []
        prefix = NO_DOCS_SELECTED_PREFIX if only is not None and not only else NOT_COVERED_PREFIX

    messages = build_messages(req.question, context, history)
    return Prepared(session_id, req.question, sources, route,
                    lambda stop=None: answer_stream(messages, prefix, stop))


def remember(session_id: str, question: str, answer: str, sources: Optional[list] = None) -> int:
    history = sessions.pop(session_id, [])     # pop + re-insert = move to "most recent"
    history.append({"role": "user", "content": question})
    history.append({"role": "assistant", "content": answer, "sources": sources or []})
    sessions[session_id] = history[-(MAX_STORED_TURNS * 2):]
    save_sessions()
    return len(sessions[session_id]) // 2


# ── Routes ───────────────────────────────────────────────────────────────────
@app.get("/")
def home():
    return {"message": "E.D.I.T.H API v4 — the web UI runs separately (see frontend/). Docs at /docs."}


SUMMARY_TRIGGER_PHRASES = (
    "summarize the document", "summarize this document", "summarize it",
    "give me a summary", "what is this document about",
    "what is the document about", "tl;dr", "overview of the document",
)


def is_summary_request(question: str) -> bool:
    q = question.strip().lower()
    return any(phrase in q for phrase in SUMMARY_TRIGGER_PHRASES)


@app.post("/chat", response_model=ChatResponse)
def chat(req: ChatRequest):
    """Non-streaming endpoint: returns the full answer at once."""
    p = prepare(req)
    try:
        answer = "".join(p.generate()).strip()
    except OllamaError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    turns = remember(p.session_id, p.question, answer, p.sources)
    return ChatResponse(session_id=p.session_id, answer=answer,
                        sources=p.sources, history_length=turns)


@app.post("/chat/stream")
def chat_stream(req: ChatRequest):
    """Streaming endpoint (newline-delimited JSON events):
         {"type":"meta","session_id":...,"sources":[...]}   – first
         {"type":"token","text":"..."}                       – many
         {"type":"done","history_length":N}                  – last
         {"type":"error","detail":"..."}                     – on failure
    """
    p = prepare(req)   # raises HTTPException (e.g. 404) before streaming starts
    stop = StopHandle()
    if req.request_id:
        ACTIVE_CHATS[req.request_id] = stop

    def event(obj: dict) -> str:
        return json.dumps(obj) + "\n"

    def gen():
        parts: list[str] = []
        turns = len(sessions.get(p.session_id, [])) // 2
        try:
            yield event({"type": "meta", "session_id": p.session_id, "sources": p.sources})
            for piece in p.generate(stop):
                parts.append(piece)
                yield event({"type": "token", "text": piece})
        except OllamaError as exc:
            yield event({"type": "error", "detail": str(exc)})
            return
        finally:
            # Also runs when the answer is stopped or the client disconnects:
            # stop Ollama, and keep whatever was already said.
            if req.request_id:
                ACTIVE_CHATS.pop(req.request_id, None)
            was_stopped = stop.stopped
            stop.stop()
            answer = "".join(parts).strip()
            if answer:
                turns = remember(p.session_id, p.question, answer, p.sources)
        yield event({"type": "done", "history_length": turns, "stopped": was_stopped})

    return StreamingResponse(gen(), media_type="application/x-ndjson")


@app.post("/chat/stop")
def chat_stop(body: StopRequest):
    """Stop a running /chat/stream answer (identified by the request_id it was sent with)."""
    handle = ACTIVE_CHATS.get(body.request_id)
    if handle:
        handle.stop()
    return {"stopped": handle is not None}


@app.get("/debug/retrieve")
def debug_retrieve(q: str, session_id: Optional[str] = None):
    """Diagnostic: show how a question would be routed (no generation, instant)."""
    history = sessions.get(session_id, []) if session_id else []
    route, results, query_used = retrieve(q, history)
    return {
        "route": route,
        "threshold": RELEVANCE_DISTANCE_THRESHOLD,
        "followup_query_used": query_used != q,
        "results": [
            {"distance": round(float(score), 4),
             "source": Path((d.metadata or {}).get("source", "?")).name,
             "page": (d.metadata or {}).get("page", "?")}
            for d, score in results
        ],
    }


@app.delete("/session")
def clear_session(body: SessionClear):
    if body.session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    del sessions[body.session_id]
    session_titles.pop(body.session_id, None)
    save_sessions()
    return {"message": f"Session {body.session_id} cleared."}


@app.patch("/session/{session_id}")
def rename_session(session_id: str, body: RenameRequest):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    title = " ".join(body.title.split())[:80]
    if not title:
        raise HTTPException(status_code=400, detail="The name can't be empty.")
    session_titles[session_id] = title
    save_sessions()
    return {"session_id": session_id, "title": title}


@app.get("/session/{session_id}/history")
def get_history(session_id: str):
    if session_id not in sessions:
        raise HTTPException(status_code=404, detail="Session not found.")
    return {
        "session_id": session_id,
        "turns": len(sessions[session_id]) // 2,
        "history": sessions[session_id],
    }


@app.get("/debug/collection")
def debug_collection():
    """Diagnostic: reports chunk count and flags exact-duplicate content,
    which happens if ingest.py was run more than once against the same
    persist_directory without clearing it first."""
    data = db.get()
    texts = data.get("documents") or []
    metas = data.get("metadatas") or []

    seen = {}
    duplicate_groups = 0
    duplicate_total = 0
    for text in texts:
        seen[text] = seen.get(text, 0) + 1
    for text, count in seen.items():
        if count > 1:
            duplicate_groups += 1
            duplicate_total += count

    return {
        "total_chunks": len(texts),
        "unique_chunks": len(seen),
        "duplicate_groups": duplicate_groups,
        "duplicate_chunk_instances": duplicate_total,
        "likely_double_ingested": duplicate_groups > 0,
        "sample_pages": [m.get("page", "?") for m in metas[:10]],
    }


@app.get("/sessions")
def list_sessions():
    """Saved chats, most recent first, each with a title (its first question)."""
    items = []
    for sid, turns in reversed(list(sessions.items())):
        if not turns:
            continue
        first_q = next((t["content"] for t in turns if t["role"] == "user"), "")
        items.append({"session_id": sid, "title": session_titles.get(sid) or first_q[:60],
                      "turns": len(turns) // 2})
    return {
        "active_sessions": len(items),
        "session_ids": [i["session_id"] for i in items],
        "sessions": items,
    }


# ── Documents (upload / list / delete — no restart needed) ───────────────────
def safe_pdf_name(raw: Optional[str]) -> str:
    """Strip any path, keep it a plain *.pdf file name."""
    name = Path((raw or "").replace("\\", "/")).name.strip()
    name = re.sub(r"[^\w .()\-\[\]]", "_", name)       # no odd characters
    if not name.lower().endswith(".pdf") or len(name) <= 4 or name.startswith("."):
        raise HTTPException(status_code=400, detail="Please upload a .pdf file.")
    return name[:120]


@app.get("/documents")
def list_documents():
    meta = db.get(include=["metadatas"]).get("metadatas") or []
    docs: dict[str, dict] = {}
    for m in meta:
        src = (m or {}).get("source", "unknown")
        d = docs.setdefault(src, {"filename": Path(src).name, "chunks": 0, "pages": 0})
        d["chunks"] += 1
        d["pages"] = max(d["pages"], int((m or {}).get("page", 0)) + 1)
    # Newest first, by when the PDF file was last written.
    for d in docs.values():
        try:
            d["added"] = os.path.getmtime(os.path.join(ingest.DATA_DIR, d["filename"]))
        except OSError:
            d["added"] = 0.0
    return {"documents": sorted(docs.values(), key=lambda d: (-d["added"], d["filename"].lower()))}


@app.delete("/documents/uploads/{upload_id}")
def cancel_upload(upload_id: str):
    """Cancel a running upload (identified by the upload_id it was sent with)."""
    flag = UPLOAD_CANCELS.get(upload_id)
    if flag:
        flag.set()
    return {"cancelled": flag is not None}


@app.post("/documents")
def upload_document(file: UploadFile = File(...), upload_id: Optional[str] = None):
    """Upload a PDF; it is chunked, embedded and searchable as soon as this returns.
    Uploading a file with an existing name replaces it. (Embedding runs on your CPU:
    allow a few seconds per page.) Pass ?upload_id=... to be able to cancel it."""
    cancel = threading.Event()
    if upload_id:
        UPLOAD_CANCELS[upload_id] = cancel
    try:
        return _ingest_upload(file, cancel)
    finally:
        if upload_id:
            UPLOAD_CANCELS.pop(upload_id, None)


def _ingest_upload(file: UploadFile, cancel: threading.Event) -> dict:
    name = safe_pdf_name(file.filename)
    data = file.file.read(UPLOAD_MAX_BYTES + 1)
    if len(data) > UPLOAD_MAX_BYTES:
        raise HTTPException(status_code=413,
                            detail=f"File is larger than {UPLOAD_MAX_BYTES // (1024 * 1024)} MB.")
    if not data.startswith(b"%PDF"):
        raise HTTPException(status_code=400, detail="That file doesn't look like a PDF.")

    final_path = os.path.join(ingest.DATA_DIR, name)
    tmp_path = final_path + ".uploading"
    with INGEST_LOCK:
        try:
            with open(tmp_path, "wb") as f:
                f.write(data)
            chunks = ingest.add_pdf(db, tmp_path, source=ingest.source_key(name),
                                    should_cancel=cancel.is_set)
            os.replace(tmp_path, final_path)   # only keep the file once it ingested fine
        except ingest.Cancelled:
            print(f"[upload] {name}: cancelled")
            raise HTTPException(status_code=409, detail="Upload cancelled.")
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc))
        except Exception as exc:
            raise HTTPException(status_code=422, detail=f"Could not read that PDF: {exc}")
        finally:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
    print(f"[upload] {name}: {len(data)} bytes, {chunks} chunks")
    return {"filename": name, "chunks": chunks}


@app.delete("/documents/{filename}")
def delete_document(filename: str):
    name = Path(filename.replace("\\", "/")).name     # never a path
    source = ingest.source_key(name)
    with INGEST_LOCK:
        existing = db.get(where={"source": source}, include=[]).get("ids") or []
        if not existing:
            raise HTTPException(status_code=404, detail="Document not found.")
        ingest.remove_source(db, source)
        path = os.path.join(ingest.DATA_DIR, name)
        if os.path.exists(path):
            os.remove(path)
    return {"message": f"Removed {name}", "chunks_removed": len(existing)}

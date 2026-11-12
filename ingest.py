"""PDF ingestion for E.D.I.T.H.

Two ways to use it:
  * Command line:  py -3.13 ingest.py      – wipe chroma_db/ and rebuild it from data/*.pdf
                                              (stop the server first: it keeps the DB open)
  * From the app:  split_pdf() / add_pdf() / remove_source() – used by the upload API
                   so documents can be added or removed without restarting the server.
"""
import glob
import os
import shutil

from langchain_chroma import Chroma
from langchain_community.document_loaders import PyPDFLoader
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter

PERSIST_DIR = "chroma_db"
DATA_DIR = "data"
EMBEDDING_MODEL = "BAAI/bge-small-en-v1.5"

# Long individual pages (e.g. a dense text page rather than a slide) still get
# split further so no single chunk overwhelms the model's context window.
# Most single-topic slides will fit in one chunk and stay intact.
MAX_CHUNK_SIZE = 1200
CHUNK_OVERLAP = 150

_splitter = RecursiveCharacterTextSplitter(chunk_size=MAX_CHUNK_SIZE, chunk_overlap=CHUNK_OVERLAP)


def source_key(filename: str) -> str:
    """The metadata 'source' value stored for a PDF in DATA_DIR. Matches what
    PyPDFLoader records when it is given os.path.join(DATA_DIR, filename)."""
    return os.path.join(DATA_DIR, os.path.basename(filename))


def split_pdf(path: str):
    """Load one PDF (one Document per page, so each slide stays a unit) and split
    only the unusually long pages. Returns (chunks, page_count)."""
    pages = PyPDFLoader(path).load()
    return _splitter.split_documents(pages), len(pages)


class Cancelled(Exception):
    """Raised by add_pdf when should_cancel() turns true."""


EMBED_BATCH = 8   # chunks embedded between cancel checks


def add_pdf(db: Chroma, path: str, source: str | None = None, should_cancel=None) -> int:
    """Add (or replace) one PDF in an open Chroma store. Returns the chunk count.
    `source` is the name recorded in metadata (defaults to `path`).
    `should_cancel` is an optional callable checked between batches; when it
    returns True the new chunks are removed again and Cancelled is raised.
    An existing document with the same source is only replaced once the new
    one is fully in, so a cancelled or failed upload never loses the old copy."""
    chunks, _ = split_pdf(path)
    if not chunks:
        raise ValueError("No extractable text found (is this a scanned PDF?).")
    source = source or path
    for c in chunks:
        c.metadata["source"] = source

    old_ids = db.get(where={"source": source}, include=[]).get("ids") or []
    new_ids: list[str] = []
    try:
        for i in range(0, len(chunks), EMBED_BATCH):
            if should_cancel and should_cancel():
                raise Cancelled()
            new_ids += db.add_documents(chunks[i:i + EMBED_BATCH])
        if should_cancel and should_cancel():
            raise Cancelled()
    except BaseException:
        if new_ids:
            db.delete(ids=new_ids)
        raise
    if old_ids:
        db.delete(ids=old_ids)       # replacing a file must not duplicate its chunks
    return len(chunks)


def remove_source(db: Chroma, source: str) -> None:
    db._collection.delete(where={"source": source})


def main() -> None:
    # Wipe any existing collection first. Chroma.from_documents() APPENDS to an
    # existing persist_directory rather than replacing it — running this script
    # more than once without clearing the folder would duplicate every chunk.
    if os.path.exists(PERSIST_DIR):
        try:
            shutil.rmtree(PERSIST_DIR)
            print(f"Cleared existing collection at {PERSIST_DIR}/")
        except PermissionError:
            raise SystemExit(
                f"\nCould not delete '{PERSIST_DIR}/' — it's still open by another "
                "process (most likely your uvicorn server, which keeps a Chroma "
                "connection open the whole time it runs).\n\n"
                "Fix: stop uvicorn (Ctrl+C in that terminal), then run this script "
                "again. Restart uvicorn afterward.\n"
                "(Tip: PDFs uploaded through the web UI are added live and need no re-ingest.)\n"
            )

    pdf_paths = sorted(glob.glob(os.path.join(DATA_DIR, "*.pdf")))
    if not pdf_paths:
        raise SystemExit(
            f"\nNo PDF files found in '{DATA_DIR}/'. Add one or more .pdf files "
            "there and run this script again.\n"
        )

    print(f"Found {len(pdf_paths)} PDF file(s):")
    all_chunks = []
    total_pages = 0
    for path in pdf_paths:
        chunks, pages = split_pdf(path)
        all_chunks.extend(chunks)
        total_pages += pages
        print(f"  - {path}: {pages} page(s), {len(chunks)} chunk(s)")

    # All files go into one collection. Each chunk's metadata still carries its
    # source filename and page number, so per-document filtering stays possible.
    Chroma.from_documents(
        documents=all_chunks,
        embedding=HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL),
        persist_directory=PERSIST_DIR,
    )
    print(f"\nStored {len(all_chunks)} chunks from {len(pdf_paths)} file(s) ({total_pages} total pages).")


if __name__ == "__main__":
    main()

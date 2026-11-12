# E.D.I.T.H — a local study chatbot for your PDFs

## Every Document Indexed To Help

Ask questions about your own PDFs. Everything runs on your machine, on CPU:

- **Chat model:** Qwen2.5 1.5B through [Ollama](https://ollama.com) (streamed, so words appear as they are generated)
- **Search:** BGE-small embeddings + ChromaDB
- **Backend:** FastAPI (`app.py`) · **Frontend:** React + Vite (`frontend/`)

Answers come from your documents when they match; otherwise the bot answers from general
knowledge and says so ("This isn't covered in your documents, but: …").

## Features

- Ask questions about uploaded PDFs and see source citations with document names and page numbers.
- Upload, select, and remove PDFs from the sidebar. The included `data/` PDFs can also be indexed locally.
- Keep multiple conversations, switch between them, and rename or delete saved chats.
- Use the dark midnight navy and cyan theme or switch to the cool-toned light theme. Dark mode includes the supplied HUD workspace background; light mode hides it.
- Run the chat model and document search locally. The app does not require a hosted AI API.

## Project layout

| Path | Purpose |
|---|---|
| `app.py` | FastAPI backend, chat endpoints, document management, and saved sessions |
| `ingest.py` | Index PDFs from `data/` into the local ChromaDB collection |
| `data/` | Sample PDF documents included with the project |
| `models/` | Model configuration/reference scripts |
| `frontend/` | React + Vite user interface |
| `frontend/public/images/edith-hud-bg.jpg` | HUD background used by the dark chat workspace |
| `.env.example` | Optional backend configuration defaults |
| `frontend/.env.example` | Optional frontend configuration defaults |

The ChromaDB index, chat history, and local `.env` files are excluded from Git. PDFs in `data/` are tracked project files; PDFs uploaded through the UI are also saved in that folder. The ChromaDB index is created locally when PDFs are ingested or uploaded.

## One-time setup

1. Install **Python 3.13** (3.14 lacks wheels for some dependencies) and **Node.js**.
2. Install **Ollama** and pull the model (~1 GB):
   ```bash
   ollama pull qwen2.5:1.5b-instruct
   ```
3. Python dependencies:
   ```bash
   py -3.13 -m pip install -r requirements.txt
   ```
4. Frontend dependencies:
   ```bash
   cd frontend && npm install
   ```
5. *(Optional)* copy `.env.example` to `.env` to change the model or limits.

## Run it

Make sure Ollama is running (it starts with Windows), then in two terminals:

```bash
py -3.13 -m uvicorn app:app --host 127.0.0.1 --port 8000
```
```bash
cd frontend && npm run dev
```

Open http://127.0.0.1:5173. Keep uvicorn at **one worker** (each worker would load its own copy of the embedding model).

## Adding documents

- **From the UI:** use *Documents → Upload PDF* in the sidebar. It is searchable as soon as the upload finishes (allow a few seconds per page on CPU). Uploading the same file name replaces it; the × removes it.
- **From the command line:** put PDFs in `data/` and run `py -3.13 ingest.py`. This wipes and rebuilds `chroma_db/`, so **stop the server first**.

Scanned PDFs (images with no text layer) can't be read.

## Useful endpoints

| | |
|---|---|
| `POST /chat/stream` | streamed answer (what the UI uses); `POST /chat` returns it all at once |
| `GET/POST/DELETE /documents` | list / upload / remove PDFs |
| `GET /sessions`, `GET /session/{id}/history`, `DELETE /session` | saved chats (stored in `chat_sessions.json`) |
| `GET /debug/retrieve?q=...` | how a question would be routed + its distances (cutoff 0.78) |
| `GET /debug/collection` | chunk counts / duplicate check |
| `GET /docs` | interactive API docs |

## Notes

- The model is small. Expect occasional wrong details, especially in summaries and formulas.
- Typical speed on a 2-core laptop: first word in ~4–8 s, full answer 10–40 s, "Summarize the document" ~1–2 min.
- Chats are saved to `chat_sessions.json` next to `app.py`; delete the file to clear all history.

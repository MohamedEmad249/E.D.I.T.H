# E.D.I.T.H — React Frontend

Standalone React + Vite + Framer Motion client for the RAG chatbot backend.

## Setup

```bash
cd frontend
npm install
npm run dev
```

Opens at `http://localhost:5173`. Make sure the FastAPI backend is running
at `http://127.0.0.1:8000` (CORS is already open on the backend).

## Build for production

```bash
npm run build
```

Outputs to `frontend/dist/`. Serve that as a static site, or copy its
contents into the backend's `ui/` folder if you want FastAPI to serve it
directly (the backend auto-detects any `.html` file in `ui/`).

## Structure

```
frontend/
├── src/
│   ├── App.jsx              orchestrates chat state, sessions
│   ├── App.css               layout, sidebar, bubbles, input
│   ├── index.css             global tokens/reset
│   ├── api.js                 fetch wrappers for /chat, /session
│   └── components/
│       ├── Sidebar.jsx
│       ├── Message.jsx
│       ├── SourceList.jsx
│       ├── TypingIndicator.jsx
│       ├── EmptyState.jsx
│       ├── InputBar.jsx
│       └── Toast.jsx
├── index.html
├── vite.config.js
└── package.json
```

# Web UI and API Integration

Ragdoll provides two ways to run the system outside of the command-line interface: a simple built-in web application, and an OpenAI-compatible REST API for drop-in use with advanced clients.

## Built-in Web UI (Gradio)

If you want a quick, ChatGPT-style web interface that you can run locally, Ragdoll comes with a built-in UI powered by Gradio.

Start it with:

```bash
pixi run ragdoll ui
```

You can optionally specify a port:
```bash
pixi run ragdoll ui --port 7860
```

Once running, navigate to `http://localhost:7860` in your browser. The UI automatically maintains chat history and queries your local JIRA tickets and PDFs just like the CLI.

---

## Open WebUI Integration (REST API)

If you are using a dedicated LLM interface like [Open WebUI](https://github.com/open-webui/open-webui), you can connect it directly to Ragdoll. Open WebUI cannot natively search your `ragdoll` ChromaDB vector database, but Ragdoll can expose itself as an OpenAI-compatible API.

### 1. Start the Ragdoll API
Run the following command to start a lightweight FastAPI server:

```bash
pixi run ragdoll serve
```

*By default, this runs on `http://0.0.0.0:8000`.*

### 2. Connect Open WebUI
1. Open your Open WebUI dashboard.
2. Go to **Settings** (gear icon) -> **Connections**.
3. Under the **OpenAI API** section, click the `+` button to add a new connection.
4. Set the **API Base URL** to `http://host.docker.internal:8000/v1` (assuming Open WebUI runs in Docker on the same machine). If running bare-metal, use `http://127.0.0.1:8000/v1`.
5. Set the **API Key** to `dummy-key` (Ragdoll does not enforce authentication locally).
6. Click **Save**.

You will now see a new model option in Open WebUI. Selecting it will route all Open WebUI messages through Ragdoll's semantic search and Ollama backend, providing you with a premium UI backed by your personal repository context.

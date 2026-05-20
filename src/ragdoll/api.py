import json
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse

from ragdoll.query.rag import chat_with_context

app = FastAPI(title="Ragdoll API", description="OpenAI-compatible local RAG API")

@app.get("/v1/models")
async def list_models():
    """Returns a dummy model list so Open WebUI can populate its model dropdown."""
    return {
        "object": "list",
        "data": [
            {
                "id": "ragdoll-context-engine",
                "object": "model",
                "created": 1700000000,
                "owned_by": "ragdoll",
            }
        ]
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """OpenAI-compatible endpoint for chat completions.

    Allows drop-in integration with Open WebUI and other AI frontends.

    Args:
        request (Request): The incoming FastAPI request object containing the JSON payload with messages.

    Returns:
        StreamingResponse: An SSE streaming response containing the generated text chunks.
    """
    body = await request.json()
    messages = body.get("messages", [])
    
    # We only support streaming for now, to provide the best UX
    # If the client didn't request a stream, we could collect it, but streaming is standard for Web UIs.
    
    def token_generator():
        # Chat_with_context expects standard OpenAI message format
        for chunk in chat_with_context(messages, stream=True):
            # Format the output as an OpenAI-compatible SSE stream
            response_obj = {
                "choices": [{"delta": {"content": chunk}}]
            }
            yield f"data: {json.dumps(response_obj)}\n\n"
        yield "data: [DONE]\n\n"

    return StreamingResponse(token_generator(), media_type="text/event-stream")

def run_server(host: str = "0.0.0.0", port: int = 8000):
    """Start the FastAPI uvicorn server."""
    import uvicorn
    uvicorn.run(app, host=host, port=port)

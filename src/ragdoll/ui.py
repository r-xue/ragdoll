import gradio as gr
from ragdoll.query.rag import chat_with_context

def predict(message, history):
    """
    Convert Gradio's history (list of [user, bot] pairs) to ragdoll's expected format.
    """
    messages = []
    for user_msg, bot_msg in history:
        messages.append({"role": "user", "content": user_msg})
        messages.append({"role": "assistant", "content": bot_msg})
        
    # Append the new user message
    messages.append({"role": "user", "content": message})
    
    # Query ragdoll backend with streaming enabled
    response_generator = chat_with_context(messages, stream=True)
    
    # Yield tokens one by one for a smooth typing effect
    partial_message = ""
    for token in response_generator:
        partial_message += token
        yield partial_message

def launch_ui(port: int = 7860):
    """Launch the Gradio ChatInterface."""
    demo = gr.ChatInterface(
        fn=predict,
        title="🧶 Ragdoll Web Chat",
        description="Ask questions about your ingested JIRA tickets, PDFs, and code.",
        examples=[
            "Who worked on the tickets related to imaging?",
            "Summarize the recent changes to the pipeline configuration.",
            "What does the VLASS-SE product naming convention say?"
        ]
    )
    demo.launch(server_port=port)

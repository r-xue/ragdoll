# Extending Ragdoll

Ragdoll is designed to be easily extensible. The most common way developers extend Ragdoll is by adding new data sources to ingest.

## Adding a Custom Data Source

To add a new data source, you need to create a new module in `ragdoll.ingest` that implements a subclass of `ragdoll.ingest.base.BaseIngestor`.

### Step 1: Create the Ingestor

Create a new file `src/ragdoll/ingest/my_source.py`:

```python
from typing import Iterator
from ragdoll.ingest.base import BaseIngestor
from ragdoll.models import Document

class MySourceIngestor(BaseIngestor):
    def __init__(self, my_param: str):
        self.my_param = my_param
        
    def extract(self) -> Iterator[Document]:
        # Your custom logic to fetch data
        yield Document(
            text="Hello world",
            metadata={
                "source": "my_source",
                "custom_field": self.my_param
            }
        )
```

### Step 2: Register the CLI Command

Update `src/ragdoll/cli.py` to expose your ingestor as a subcommand under the `ingest` group:

```python
import click
from ragdoll.ingest.my_source import MySourceIngestor
from ragdoll.store.vectordb import ChromaStore

@ingest.command("my-source")
@click.argument("my_param")
def ingest_my_source(my_param: str):
    """Ingest data from my custom source."""
    store = ChromaStore()
    ingestor = MySourceIngestor(my_param)
    
    # BaseIngestor provides the .ingest() method which handles chunking and storing!
    count = ingestor.ingest(store)
    click.echo(f"Successfully ingested {count} chunks.")
```

That's it! Your new data source is now fully integrated with Ragdoll's chunking, embedding, and storage pipeline.

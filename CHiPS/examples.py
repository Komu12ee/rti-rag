"""
Examples of service communication in Docker and local development

This module demonstrates how to connect to and use external services
(Qdrant, Ollama) in both Docker containers and local environments.
"""

from service_config import ServiceConfig
import requests
from typing import List, Dict, Any


class RAGService:
    """Example RAG service using Qdrant and Ollama."""
    
    def __init__(self):
        """Initialize service with configuration."""
        self.config = ServiceConfig()
        self.qdrant_client = self.config.get_qdrant_client()
        self.ollama_url = self.config.get_ollama_url()
        
        # Print configuration for verification
        print("RAG Service initialized with:")
        print(f"  - Qdrant: {self.config.qdrant_host}:{self.config.qdrant_port}")
        print(f"  - Ollama: {self.ollama_url} (enabled: {self.config.is_ollama_enabled()})")
        print(f"  - Embedding Model: {self.config.get_embedding_model_name()}")
    
    def get_qdrant_collections(self) -> List[str]:
        """
        Fetch available collections from Qdrant.
        
        Returns:
            List of collection names
        """
        try:
            collections = self.qdrant_client.get_collections()
            return [col.name for col in collections.collections]
        except Exception as e:
            print(f"Error fetching Qdrant collections: {e}")
            return []
    
    def call_ollama(self, prompt: str, model: str = "llama2") -> str:
        """
        Call Ollama for text generation.
        
        Args:
            prompt: Input prompt
            model: Model name (default: llama2)
            
        Returns:
            Generated response
        """
        if not self.config.is_ollama_enabled():
            print("Ollama is disabled")
            return None
        
        try:
            url = f"{self.ollama_url}/api/generate"
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False
            }
            response = requests.post(url, json=payload, timeout=300)
            response.raise_for_status()
            return response.json().get("response", "")
        except Exception as e:
            print(f"Error calling Ollama: {e}")
            return None
    
    def get_available_ollama_models(self) -> List[str]:
        """
        Fetch available models from Ollama.
        
        Returns:
            List of available model names
        """
        if not self.config.is_ollama_enabled():
            return []
        
        try:
            url = f"{self.ollama_url}/api/tags"
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            models = response.json().get("models", [])
            return [m.get("name") for m in models]
        except Exception as e:
            print(f"Error fetching Ollama models: {e}")
            return []


# ============================================================================
# USAGE EXAMPLES
# ============================================================================

def example_local_development():
    """
    Example: Local development environment
    
    Run locally:
        # Terminal 1: Start Qdrant
        docker run -p 6333:6333 qdrant/qdrant
        
        # Terminal 2: Start Ollama
        docker run -p 11434:11434 ollama/ollama
        
        # Terminal 3: Run this script
        python examples.py
    
    Configuration (.env):
        QDRANT_HOST=localhost
        OLLAMA_HOST=http://localhost:11434
    """
    print("\n" + "="*60)
    print("EXAMPLE: Local Development")
    print("="*60)
    
    service = RAGService()
    
    # Check Qdrant collections
    collections = service.get_qdrant_collections()
    print(f"Qdrant collections: {collections}")
    
    # Check Ollama models
    if service.config.is_ollama_enabled():
        models = service.get_available_ollama_models()
        print(f"Ollama models: {models}")
        
        # Try a simple generation
        if models:
            response = service.call_ollama("What is Docker?", model=models[0])
            print(f"Ollama response: {response[:100]}...")


def example_docker_compose():
    """
    Example: Docker Compose environment
    
    Run with Docker Compose:
        docker-compose up -d
    
    Then access:
        - Web UI: http://localhost:5000
        - Qdrant API: http://localhost:6333
        - Ollama API: http://localhost:11434
    
    Configuration (.env):
        QDRANT_HOST=qdrant
        OLLAMA_HOST=http://ollama:11434
        
    Services communicate using hostnames (service names from docker-compose.yml)
    """
    print("\n" + "="*60)
    print("EXAMPLE: Docker Compose")
    print("="*60)
    print("""
Services are configured to communicate via hostname:
- Qdrant service is accessible at: qdrant:6333 (not localhost:6333)
- Ollama service is accessible at: http://ollama:11434 (not http://localhost:11434)

This configuration is set in docker-compose.yml environment variables:
    environment:
      - QDRANT_HOST=qdrant
      - OLLAMA_HOST=http://ollama:11434
    """)
    
    service = RAGService()
    service.config.print_config()


def example_usage_in_pipeline():
    """
    Example: Using services in pipeline stages
    """
    print("\n" + "="*60)
    print("EXAMPLE: Using in Pipeline Stages")
    print("="*60)
    
    config = ServiceConfig()
    
    # Stage 1: Upload embeddings to Qdrant
    print("\n1. Using Qdrant in Stage 4 (Embeddings):")
    print("   from service_config import ServiceConfig")
    print("   config = ServiceConfig()")
    print("   client = config.get_qdrant_client()")
    print("   # Upload vectors to collections")
    
    # Stage 5: Query with LLM enhancement via Ollama
    print("\n2. Using Ollama in Stage 5 (Web UI):")
    print("   from service_config import ServiceConfig")
    print("   config = ServiceConfig()")
    print("   if config.is_ollama_enabled():")
    print("       url = config.get_ollama_url()")
    print("       # Call LLM for query expansion or response generation")
    
    # Use embedding model
    print("\n3. Using configured models:")
    print(f"   embedding_model = config.get_embedding_model_name()")
    print(f"   # Result: {config.get_embedding_model_name()}")
    print(f"   reranker_model = config.get_reranker_model_name()")
    print(f"   # Result: {config.get_reranker_model_name()}")


if __name__ == "__main__":
    example_local_development()
    example_docker_compose()
    example_usage_in_pipeline()

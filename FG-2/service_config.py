"""
Service Configuration Manager
Handles connections to external services (Qdrant, Ollama, etc.)
Supports both local development and Docker container communication.

Usage:
    from service_config import ServiceConfig
    
    config = ServiceConfig()
    qdrant_client = config.get_qdrant_client()
    ollama_url = config.get_ollama_url()
"""

import os
from typing import Optional
from dotenv import load_dotenv

# Load environment variables from .env if it exists
load_dotenv()


class ServiceConfig:
    """Centralized configuration for external services."""
    
    def __init__(self):
        """Initialize service configuration from environment variables."""
        # Qdrant Configuration
        self.qdrant_host = os.getenv("QDRANT_HOST", "localhost")
        self.qdrant_port = int(os.getenv("QDRANT_PORT", "6333"))
        self.qdrant_api_key = os.getenv("QDRANT_API_KEY", None)
        self.qdrant_timeout = int(os.getenv("QDRANT_TIMEOUT", "60"))
        
        # Groq API Configuration (replaces Ollama)
        self.groq_api_key = os.getenv("GROQ_API_KEY", None)
        self.groq_model = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")
        self.groq_enabled = os.getenv("GROQ_ENABLED", "true").lower() == "true"
        
        # Embedding Model Configuration
        self.embedding_model = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
        self.reranker_model = os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-large")
        
        # OCR Configuration
        self.ocr_engine = os.getenv("OCR_ENGINE", "docling")
        
        # Processing Configuration
        self.max_workers = int(os.getenv("MAX_WORKERS", "4"))
        self.batch_size = int(os.getenv("BATCH_SIZE", "32"))
        self.chunk_size = int(os.getenv("CHUNK_SIZE", "1024"))
        self.chunk_overlap = int(os.getenv("CHUNK_OVERLAP", "128"))
        
        # OpenAI Configuration (optional)
        self.openai_api_key = os.getenv("OPENAI_API_KEY", None)
        
        # Application Configuration
        self.environment = os.getenv("ENVIRONMENT", "development")
        self.log_level = os.getenv("LOG_LEVEL", "INFO")
    
    def get_qdrant_client(self):
        """
        Get initialized Qdrant client.
        
        Returns:
            QdrantClient: Connected Qdrant client
            
        Example:
            >>> config = ServiceConfig()
            >>> client = config.get_qdrant_client()
        """
        from qdrant_client import QdrantClient
        
        client = QdrantClient(
            host=self.qdrant_host,
            port=self.qdrant_port,
            api_key=self.qdrant_api_key,
            timeout=self.qdrant_timeout
        )
        return client
    
    def get_groq_api_key(self) -> str:
        """
        Get Groq API key.
        
        Returns:
            str: Groq API key for authentication
        """
        return self.groq_api_key
    
    def get_groq_model(self) -> str:
        """
        Get configured Groq model name.
        
        Returns:
            str: Model identifier (e.g., llama-3.3-70b-versatile)
        """
        return self.groq_model
    
    def get_embedding_model_name(self) -> str:
        """
        Get configured embedding model name.
        
        Returns:
            str: Embedding model identifier
        """
        return self.embedding_model
    
    def get_reranker_model_name(self) -> str:
        """
        Get configured reranker model name.
        
        Returns:
            str: Reranker model identifier
        """
        return self.reranker_model
    
    def is_groq_enabled(self) -> bool:
        """
        Check if Groq API is enabled.
        
        Returns:
            bool: True if Groq is enabled and API key is set, False otherwise
        """
        return self.groq_enabled and bool(self.groq_api_key)
    
    def get_config_dict(self) -> dict:
        """
        Get all configuration as dictionary.
        
        Returns:
            dict: All configuration parameters
        """
        return {
            'qdrant': {
                'host': self.qdrant_host,
                'port': self.qdrant_port,
                'api_key': '***' if self.qdrant_api_key else None,
                'timeout': self.qdrant_timeout,
            },
            'groq': {
                'model': self.groq_model,
                'enabled': self.is_groq_enabled(),
                'has_api_key': bool(self.groq_api_key),
            },
            'models': {
                'embedding': self.embedding_model,
                'reranker': self.reranker_model,
                'ocr_engine': self.ocr_engine,
            },
            'processing': {
                'max_workers': self.max_workers,
                'batch_size': self.batch_size,
                'chunk_size': self.chunk_size,
                'chunk_overlap': self.chunk_overlap,
            },
            'application': {
                'environment': self.environment,
                'log_level': self.log_level,
            }
        }
    
    def print_config(self) -> None:
        """Print configuration for debugging."""
        import json
        config_dict = self.get_config_dict()
        print("\n" + "="*60)
        print("SERVICE CONFIGURATION")
        print("="*60)
        print(json.dumps(config_dict, indent=2))
        print("="*60 + "\n")


if __name__ == "__main__":
    # Example usage
    config = ServiceConfig()
    config.print_config()
    
    # Try connecting to services
    try:
        print("Testing Qdrant connection...")
        client = config.get_qdrant_client()
        print(f"✓ Connected to Qdrant at {config.qdrant_host}:{config.qdrant_port}")
    except Exception as e:
        print(f"✗ Qdrant connection failed: {e}")
    
    if config.is_ollama_enabled():
        try:
            import requests
            print(f"Testing Ollama connection at {config.get_ollama_url()}...")
            response = requests.get(f"{config.get_ollama_url()}/api/tags", timeout=5)
            print(f"✓ Connected to Ollama at {config.get_ollama_url()}")
        except Exception as e:
            print(f"✗ Ollama connection failed: {e}")

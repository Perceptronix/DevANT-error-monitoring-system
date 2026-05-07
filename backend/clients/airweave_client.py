"""
Airweave client for context search.

Uses the Airweave SDK to search for related code, tickets, and documentation.
This is what makes the error monitoring "intelligent" - it provides context
from your codebase and tools to help understand and resolve errors.
"""
import logging
from typing import List, Dict, Any, Optional

from config import get_config

logger = logging.getLogger(__name__)


class AirweaveClient:
    """
    Async client for searching Airweave collections.
    
    Provides methods to search for:
    - Related code from GitHub
    - Related tickets from Linear/Jira
    - Documentation from Notion/Confluence
    """
    
    def __init__(self):
        config = get_config()
        self.api_key = config.airweave.api_key
        self.api_url = config.airweave.api_url
        self.collection_id = config.airweave.collection_id
        
        self._client = None
        self._initialized = False
        
        if self.is_configured:
            logger.info(f"Airweave client configured (collection: {self.collection_id})")
        else:
            logger.warning("Airweave not configured - context search will use mock data")
    
    @property
    def is_configured(self) -> bool:
        """Check if Airweave is properly configured."""
        return bool(self.api_key and self.collection_id)
    
    async def _get_client(self):
        """Lazy-initialize the Airweave SDK client."""
        if not self._initialized and self.is_configured:
            try:
                from airweave import AsyncAirweaveSDK
                
                self._client = AsyncAirweaveSDK(
                    api_key=self.api_key,
                    base_url=self.api_url,
                    timeout=60.0,
                )
                self._initialized = True
                logger.info("Airweave SDK client initialized")
            except ImportError:
                logger.error(
                    "Airweave SDK not installed. Install with: pip install airweave"
                )
                self._client = None
            except Exception as e:
                logger.error(f"Failed to initialize Airweave client: {e}")
                self._client = None
        
        return self._client
    
    async def search(
        self,
        query: str,
        source_filter: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        Execute a search query against Airweave.
        
        Uses hybrid search (semantic + keyword) with reranking for best results.
        
        Args:
            query: Search query string
            source_filter: Optional source type filter (e.g., "linear", "github")
            limit: Maximum number of results
            
        Returns:
            List of search results with content, metadata, and scores
        """
        if not self.is_configured:
            logger.debug("Airweave not configured, returning empty results")
            return []
        
        client = await self._get_client()
        if not client:
            return []
        
        # Build filter if source specified
        filter_obj = None
        if source_filter:
            filter_obj = {
                "must": [{
                    "key": "source_name",
                    "match": {"any": [source_filter]}
                }]
            }
        
        try:
            from airweave import SearchRequest
            
            search_request = SearchRequest(
                query=query,
                limit=limit,
                filter=filter_obj,
            )
            
            response = await client.collections.search(
                readable_id=self.collection_id,
                request=search_request,
            )
            
            # Convert results to dicts
            results = []
            if hasattr(response, 'results'):
                for item in response.results:
                    result = {
                        "content": getattr(item, 'content', ''),
                        "metadata": getattr(item, 'metadata', {}),
                        "payload": getattr(item, 'payload', {}),
                        "score": getattr(item, 'score', 0),
                    }
                    results.append(result)
            
            logger.info(f"Airweave search returned {len(results)} results for: {query[:50]}...")
            return results
            
        except Exception as e:
            logger.error(f"Airweave search failed: {e}", exc_info=True)
            return []
    
    async def search_code(
        self,
        query: str,
        module: Optional[str] = None,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for related code from GitHub.
        
        Args:
            query: Search query (error message, function name, etc.)
            module: Optional module name to focus search
            limit: Maximum results
            
        Returns:
            List of code snippets with file paths and content
        """
        search_query = f"{query} {module}" if module else query
        results = await self.search(search_query, source_filter="github", limit=limit)
        
        # Format results for code context
        formatted = []
        for result in results:
            metadata = result.get("metadata", result.get("payload", {}))
            formatted.append({
                "title": metadata.get("path_in_repo", metadata.get("name", "Unknown")),
                "content": result.get("content", "")[:500],
                "source": "github",
                "url": metadata.get("url"),
                "score": result.get("score", 0),
            })
        
        return formatted
    
    async def search_tickets(
        self,
        query: str,
        limit: int = 5,
    ) -> List[Dict[str, Any]]:
        """
        Search for related tickets from Linear.
        
        Args:
            query: Search query (error description, signature, etc.)
            limit: Maximum results
            
        Returns:
            List of tickets with title, content, status, and URL
        """
        results = await self.search(query, source_filter="linear", limit=limit)
        
        # Format results for ticket context
        formatted = []
        for result in results:
            metadata = result.get("metadata", result.get("payload", {}))
            formatted.append({
                "title": metadata.get("title", "Unknown"),
                "content": result.get("content", "")[:300],
                "source": "linear",
                "url": metadata.get("url"),
                "status": metadata.get("status"),
                "identifier": metadata.get("identifier"),
                "id": metadata.get("id"),
                "score": result.get("score", 0),
            })
        
        return formatted
    
    async def search_docs(
        self,
        query: str,
        limit: int = 3,
    ) -> List[Dict[str, Any]]:
        """
        Search for related documentation.
        
        Args:
            query: Search query
            limit: Maximum results
            
        Returns:
            List of documentation results
        """
        # Search without source filter to get any documentation
        results = await self.search(query, limit=limit)
        
        # Filter out code and tickets, keep docs
        formatted = []
        for result in results:
            metadata = result.get("metadata", result.get("payload", {}))
            source = metadata.get("source_name", "unknown")
            
            # Skip code and ticket results
            if source in ["github", "linear", "jira"]:
                continue
            
            formatted.append({
                "title": metadata.get("title", "Unknown"),
                "content": result.get("content", "")[:300],
                "source": source,
                "url": metadata.get("url"),
                "score": result.get("score", 0),
            })
        
        return formatted[:limit]


# Singleton instance
_airweave_client: Optional[AirweaveClient] = None


def get_airweave_client() -> AirweaveClient:
    """Get singleton Airweave client instance."""
    global _airweave_client
    if _airweave_client is None:
        _airweave_client = AirweaveClient()
    return _airweave_client

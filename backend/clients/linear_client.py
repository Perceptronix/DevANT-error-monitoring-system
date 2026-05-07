"""
Linear API client with preview fallback.

When Linear is not configured, returns preview ticket objects instead of
creating real tickets. This allows the demo to work without Linear access.
"""
import logging
import uuid
from dataclasses import dataclass
from typing import Optional, List, Dict, Any

import httpx

from config import get_config

logger = logging.getLogger(__name__)


@dataclass
class LinearTicket:
    """Represents a Linear ticket (real or preview)."""
    id: str
    identifier: str  # e.g., "ENG-1234"
    title: str
    description: str
    url: str
    status: str
    priority: int  # 1=Urgent, 2=High, 3=Medium, 4=Low
    labels: List[str]
    is_preview: bool = False  # True if this is just a preview


class LinearClient:
    """
    Linear API client.
    
    When disabled/not configured, returns preview objects instead of 
    creating real tickets. This allows the demo to show what would happen
    without requiring Linear access.
    """
    
    def __init__(self):
        config = get_config()
        self.api_key = config.linear.api_key
        self.team_id = config.linear.team_id
        self.enabled = config.linear.enabled
        
        self._configured = self.enabled and bool(self.api_key) and bool(self.team_id)
        
        if self._configured:
            logger.info("Linear integration ENABLED - will create real tickets")
        else:
            logger.info("Linear integration DISABLED - will generate previews only")
    
    @property
    def is_configured(self) -> bool:
        """Check if Linear is properly configured."""
        return self._configured
    
    async def create_issue(
        self,
        title: str,
        description: str,
        priority: int = 3,  # 1=Urgent, 2=High, 3=Medium, 4=Low
        labels: Optional[List[str]] = None,
    ) -> LinearTicket:
        """
        Create a Linear issue, or return a preview if not configured.
        
        Args:
            title: Issue title
            description: Issue description (markdown supported)
            priority: Priority level (1-4)
            labels: Label names to add
            
        Returns:
            LinearTicket object (real or preview)
        """
        if not self._configured:
            return self._create_preview(title, description, priority, labels)
        
        try:
            mutation = """
                mutation CreateIssue($input: IssueCreateInput!) {
                    issueCreate(input: $input) {
                        success
                        issue {
                            id
                            identifier
                            title
                            url
                            state { name }
                            priority
                        }
                    }
                }
            """
            
            variables = {
                "input": {
                    "teamId": self.team_id,
                    "title": title,
                    "description": description,
                    "priority": priority,
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.linear.app/graphql",
                    headers={
                        "Authorization": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={"query": mutation, "variables": variables},
                )
                response.raise_for_status()
                data = response.json()
            
            if "errors" in data:
                logger.error(f"Linear API errors: {data['errors']}")
                return self._create_preview(title, description, priority, labels, error=str(data['errors']))
            
            issue = data["data"]["issueCreate"]["issue"]
            
            logger.info(f"Created Linear ticket: {issue['identifier']}")
            
            return LinearTicket(
                id=issue["id"],
                identifier=issue["identifier"],
                title=title,
                description=description,
                url=issue["url"],
                status=issue["state"]["name"],
                priority=priority,
                labels=labels or [],
                is_preview=False,
            )
            
        except Exception as e:
            logger.error(f"Failed to create Linear ticket: {e}")
            return self._create_preview(title, description, priority, labels, error=str(e))
    
    async def add_comment(self, issue_id: str, body: str) -> bool:
        """
        Add a comment to an existing issue.
        
        Args:
            issue_id: Linear issue ID
            body: Comment body (markdown supported)
            
        Returns:
            True if successful
        """
        if not self._configured:
            logger.info(f"[PREVIEW] Would add comment to {issue_id}: {body[:100]}...")
            return True
        
        try:
            mutation = """
                mutation AddComment($input: CommentCreateInput!) {
                    commentCreate(input: $input) {
                        success
                    }
                }
            """
            
            variables = {
                "input": {
                    "issueId": issue_id,
                    "body": body,
                }
            }
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.linear.app/graphql",
                    headers={
                        "Authorization": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={"query": mutation, "variables": variables},
                )
                response.raise_for_status()
                data = response.json()
            
            success = data.get("data", {}).get("commentCreate", {}).get("success", False)
            
            if success:
                logger.info(f"Added comment to Linear issue {issue_id}")
            else:
                logger.warning(f"Failed to add comment to {issue_id}: {data}")
            
            return success
            
        except Exception as e:
            logger.error(f"Failed to add comment: {e}")
            return False
    
    async def get_issue(self, issue_id: str) -> Optional[Dict[str, Any]]:
        """
        Get issue details.
        
        Args:
            issue_id: Linear issue ID
            
        Returns:
            Issue data dict or None
        """
        if not self._configured:
            return None
        
        try:
            query = """
                query GetIssue($id: String!) {
                    issue(id: $id) {
                        id
                        identifier
                        title
                        url
                        state { name }
                        priority
                    }
                }
            """
            
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    "https://api.linear.app/graphql",
                    headers={
                        "Authorization": self.api_key,
                        "Content-Type": "application/json",
                    },
                    json={"query": query, "variables": {"id": issue_id}},
                )
                response.raise_for_status()
                data = response.json()
            
            return data.get("data", {}).get("issue")
            
        except Exception as e:
            logger.error(f"Failed to get issue: {e}")
            return None
    
    async def update_status(self, issue_id: str, state_name: str) -> bool:
        """
        Update issue status (for reopening, etc.).
        
        Args:
            issue_id: Linear issue ID
            state_name: State name (e.g., "In Progress", "Done")
            
        Returns:
            True if successful
        """
        if not self._configured:
            logger.info(f"[PREVIEW] Would update {issue_id} to status: {state_name}")
            return True
        
        # Would need to look up state ID first
        # For now, just log
        logger.info(f"Would update issue {issue_id} to state: {state_name}")
        return True
    
    def _create_preview(
        self,
        title: str,
        description: str,
        priority: int,
        labels: Optional[List[str]] = None,
        error: Optional[str] = None,
    ) -> LinearTicket:
        """Create a preview ticket object."""
        preview_id = f"preview-{uuid.uuid4().hex[:8]}"
        
        return LinearTicket(
            id=preview_id,
            identifier=f"DEMO-{preview_id[-4:].upper()}",
            title=title,
            description=description,
            url=f"https://linear.app/demo/issue/{preview_id}",
            status="Preview" if not error else f"Error: {error[:50]}",
            priority=priority,
            labels=labels or [],
            is_preview=True,
        )


# Singleton instance
_linear_client: Optional[LinearClient] = None


def get_linear_client() -> LinearClient:
    """Get singleton Linear client instance."""
    global _linear_client
    if _linear_client is None:
        _linear_client = LinearClient()
    return _linear_client

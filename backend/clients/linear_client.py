"""
Linear client with preview-mode fallback.

When Linear is not configured (LINEAR_ENABLED=false or no API key),
returns preview ticket objects instead of creating real issues.
This allows the demo pipeline to run fully without a Linear account.
"""
import logging
import uuid
from dataclasses import dataclass, field
from typing import Optional, List

from config import get_config

logger = logging.getLogger(__name__)


@dataclass
class LinearIssue:
    """Represents a Linear issue (real or preview)."""
    id: str
    identifier: str
    title: str
    url: str
    status: str
    is_preview: bool = False


class LinearClient:
    """
    Linear GraphQL API client.

    When disabled/not configured, returns preview objects instead of
    creating real issues. The interface is identical in both modes.
    """

    def __init__(self):
        config = get_config()
        self.api_key = config.linear.api_key if hasattr(config, "linear") else None
        self.team_id = config.linear.team_id if hasattr(config, "linear") else None
        self.enabled = config.linear.enabled if hasattr(config, "linear") else False

        self._configured = (
            self.enabled
            and bool(self.api_key)
            and bool(self.team_id)
        )

        if self._configured:
            logger.info("Linear integration ENABLED — will create real issues")
        else:
            logger.info("Linear integration DISABLED — will generate previews only")

    @property
    def is_configured(self) -> bool:
        """Check if Linear is properly configured."""
        return self._configured

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def create_issue(
        self,
        title: str,
        description: str,
        priority: int = 3,
        labels: Optional[List[str]] = None,
    ) -> LinearIssue:
        """
        Create a new Linear issue, or return a preview if not configured.

        Args:
            title:       Issue title
            description: Issue description (markdown)
            priority:    Priority 1-4 (1=urgent, 4=low)
            labels:      Optional list of label names

        Returns:
            LinearIssue (real or preview)
        """
        if not self._configured:
            return self._preview_issue(title)

        try:
            return await self._create_real_issue(title, description, priority, labels or [])
        except Exception as exc:
            logger.error(f"Linear create_issue failed: {exc}")
            return self._preview_issue(title, error=str(exc))

    async def add_comment(self, issue_id: str, body: str) -> bool:
        """
        Add a comment to an existing Linear issue.

        Args:
            issue_id: Linear issue ID (UUID)
            body:     Comment body (markdown)

        Returns:
            True if successful (or preview mode)
        """
        if not self._configured:
            logger.info(f"[PREVIEW] Would comment on {issue_id}: {body[:100]}...")
            return True

        try:
            return await self._add_real_comment(issue_id, body)
        except Exception as exc:
            logger.error(f"Linear add_comment failed: {exc}")
            return False

    # ------------------------------------------------------------------
    # Internal — real API calls
    # ------------------------------------------------------------------

    async def _create_real_issue(
        self,
        title: str,
        description: str,
        priority: int,
        labels: List[str],
    ) -> LinearIssue:
        """Create issue via Linear GraphQL API."""
        import httpx

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

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.linear.app/graphql",
                json={"query": mutation, "variables": variables},
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        issue_data = data["data"]["issueCreate"]["issue"]
        return LinearIssue(
            id=issue_data["id"],
            identifier=issue_data["identifier"],
            title=issue_data["title"],
            url=issue_data["url"],
            status=issue_data["state"]["name"],
            is_preview=False,
        )

    async def _add_real_comment(self, issue_id: str, body: str) -> bool:
        """Add comment via Linear GraphQL API."""
        import httpx

        mutation = """
        mutation AddComment($input: CommentCreateInput!) {
            commentCreate(input: $input) {
                success
            }
        }
        """

        variables = {"input": {"issueId": issue_id, "body": body}}

        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                "https://api.linear.app/graphql",
                json={"query": mutation, "variables": variables},
                headers={
                    "Authorization": self.api_key,
                    "Content-Type": "application/json",
                },
            )
            resp.raise_for_status()
            data = resp.json()

        return data.get("data", {}).get("commentCreate", {}).get("success", False)

    # ------------------------------------------------------------------
    # Preview helpers
    # ------------------------------------------------------------------

    def _preview_issue(self, title: str, error: Optional[str] = None) -> LinearIssue:
        """Return a preview LinearIssue without calling the API."""
        fake_id = uuid.uuid4().hex
        identifier = f"ENG-{fake_id[:4].upper()}"
        if error:
            logger.warning(f"Returning preview issue due to error: {error}")
        return LinearIssue(
            id=fake_id,
            identifier=identifier,
            title=title[:200],
            url=f"https://linear.app/preview/issue/{identifier}",
            status="Todo",
            is_preview=True,
        )


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------
_linear_client: Optional[LinearClient] = None


def get_linear_client() -> LinearClient:
    """Get singleton Linear client instance."""
    global _linear_client
    if _linear_client is None:
        _linear_client = LinearClient()
    return _linear_client

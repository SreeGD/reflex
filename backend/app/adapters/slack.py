"""Slack adapter — receives events, forwards to chat engine, formats Block Kit responses.

This is a stub implementation defining the interface and Block Kit formatting.
Full deployment requires:
1. A Slack app created at api.slack.com/apps
2. Bot token scopes: chat:write, app_mentions:read, channels:history
3. Socket Mode enabled for local development
4. Event subscriptions: app_mention, message.im

Usage (Socket Mode, local dev):
    export SLACK_BOT_TOKEN=xoxb-...
    export SLACK_APP_TOKEN=xapp-...
    python -m backend.app.adapters.slack
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional
from urllib.request import Request, urlopen

from backend.app.chat.response import Action, ChatResponse

logger = logging.getLogger(__name__)

# Default API endpoint
DEFAULT_API_URL = "http://localhost:8000"


def chat_response_to_blocks(response: ChatResponse) -> List[Dict[str, Any]]:
    """Convert a ChatResponse to Slack Block Kit blocks.

    This is the core rendering function — it translates the platform-agnostic
    ChatResponse into Slack's Block Kit JSON format.
    """
    blocks: List[Dict[str, Any]] = []

    # Severity header
    severity_emoji = {
        "info": ":large_blue_circle:",
        "warning": ":warning:",
        "critical": ":red_circle:",
    }
    if response.severity != "info":
        blocks.append({
            "type": "context",
            "elements": [{
                "type": "mrkdwn",
                "text": f"{severity_emoji.get(response.severity, '')} *{response.severity.upper()}*",
            }],
        })

    # Main text
    blocks.append({
        "type": "section",
        "text": {
            "type": "mrkdwn",
            "text": response.text[:3000],  # Slack limit
        },
    })

    # Structured data as fields
    if response.structured_data:
        fields = []
        for key, value in response.structured_data.items():
            if isinstance(value, (str, int, float, bool)):
                fields.append({
                    "type": "mrkdwn",
                    "text": f"*{key}*\n{value}",
                })
        if fields:
            # Slack allows max 10 fields per section
            for i in range(0, len(fields), 10):
                blocks.append({
                    "type": "section",
                    "fields": fields[i:i + 10],
                })

    # Action buttons
    if response.actions:
        button_elements = []
        for action in response.actions:
            style_map = {"primary": "primary", "danger": "danger"}
            button = {
                "type": "button",
                "text": {"type": "plain_text", "text": action.label},
                "action_id": action.action_id,
                "value": action.value or action.action_id,
            }
            if action.style in style_map:
                button["style"] = style_map[action.style]
            button_elements.append(button)

        blocks.append({
            "type": "actions",
            "elements": button_elements[:5],  # Slack max 5 buttons per block
        })

    return blocks


def format_slack_message(response: ChatResponse) -> Dict[str, Any]:
    """Format a full Slack message payload from a ChatResponse."""
    return {
        "text": response.text[:200],  # Fallback text
        "blocks": chat_response_to_blocks(response),
    }


class SlackAdapter:
    """Slack bot adapter that bridges Slack events to the Reflex chat engine.

    In production, this would use slack_bolt for event handling.
    This stub provides the interface and message formatting.
    """

    def __init__(self, api_url: str = DEFAULT_API_URL) -> None:
        self._api_url = api_url

    def handle_message(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a Slack message event.

        Args:
            event: Slack event payload with keys: text, user, thread_ts, channel.

        Returns:
            Slack message payload ready to post via chat.postMessage.
        """
        text = event.get("text", "")
        user_id = event.get("user", "unknown")
        # Use thread_ts as session_id (falls back to event ts for new threads)
        thread_ts = event.get("thread_ts") or event.get("ts", "")
        channel = event.get("channel", "")

        # Strip bot mention prefix (e.g., "<@U12345> what happened?")
        if text.startswith("<@"):
            text = text.split(">", 1)[-1].strip()

        # Call the chat API
        response_data = self._call_chat_api(thread_ts, text, user_id)

        # Build the ChatResponse
        response = ChatResponse(
            text=response_data.get("text", ""),
            structured_data=response_data.get("structured_data"),
            actions=[
                Action(
                    label=a["label"],
                    action_id=a["action_id"],
                    value=a.get("value", ""),
                    style=a.get("style", "default"),
                )
                for a in response_data.get("actions", [])
            ],
            severity=response_data.get("severity", "info"),
            conversation_id=thread_ts,
        )

        # Format as Slack message
        slack_msg = format_slack_message(response)
        slack_msg["channel"] = channel
        slack_msg["thread_ts"] = thread_ts

        return slack_msg

    def handle_interaction(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        """Handle a Slack interactive component callback (button click).

        Args:
            payload: Slack interaction payload.

        Returns:
            Slack message payload for the response.
        """
        actions = payload.get("actions", [])
        if not actions:
            return {"text": "No action found in payload."}

        action = actions[0]
        action_id = action.get("action_id", "")
        value = action.get("value", "")
        user_id = payload.get("user", {}).get("id", "unknown")
        thread_ts = payload.get("message", {}).get("thread_ts", "")
        channel = payload.get("channel", {}).get("id", "")

        # Forward the action as a chat message
        message = f"{action_id}: {value}"
        response_data = self._call_chat_api(thread_ts, message, user_id)

        response = ChatResponse(
            text=response_data.get("text", ""),
            severity=response_data.get("severity", "info"),
            conversation_id=thread_ts,
        )

        slack_msg = format_slack_message(response)
        slack_msg["channel"] = channel
        slack_msg["thread_ts"] = thread_ts

        return slack_msg

    def _call_chat_api(self, session_id: str, message: str, user_id: str) -> Dict[str, Any]:
        """Call the POST /chat endpoint."""
        payload = json.dumps({
            "session_id": session_id,
            "message": message,
            "user_id": user_id,
        }).encode()
        req = Request(
            f"{self._api_url}/chat",
            data=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            resp = urlopen(req, timeout=60)
            return json.loads(resp.read())
        except Exception as e:
            logger.error("Chat API call failed: %s", e)
            return {"text": f"Error communicating with Reflex: {e}", "severity": "critical"}


# --- Socket Mode runner (for local development) ---

def run_socket_mode():
    """Run the Slack bot in Socket Mode for local development.

    Requires:
        pip install slack-bolt
        SLACK_BOT_TOKEN and SLACK_APP_TOKEN environment variables
    """
    import os

    try:
        from slack_bolt import App
        from slack_bolt.adapter.socket_mode import SocketModeHandler
    except ImportError:
        print("slack-bolt not installed. Run: pip install slack-bolt")
        print("Then set SLACK_BOT_TOKEN and SLACK_APP_TOKEN environment variables.")
        return

    bot_token = os.environ.get("SLACK_BOT_TOKEN")
    app_token = os.environ.get("SLACK_APP_TOKEN")

    if not bot_token or not app_token:
        print("Set SLACK_BOT_TOKEN and SLACK_APP_TOKEN environment variables.")
        return

    app = App(token=bot_token)
    adapter = SlackAdapter()

    @app.event("app_mention")
    def handle_mention(event, say):
        result = adapter.handle_message(event)
        say(**result)

    @app.event("message")
    def handle_dm(event, say):
        # Only respond to DMs (not channel messages without mention)
        if event.get("channel_type") == "im":
            result = adapter.handle_message(event)
            say(**result)

    @app.action("")  # Catch-all for button clicks
    def handle_button(ack, body, say):
        ack()
        result = adapter.handle_interaction(body)
        say(**result)

    print("Starting Reflex Slack bot in Socket Mode...")
    handler = SocketModeHandler(app, app_token)
    handler.start()


if __name__ == "__main__":
    run_socket_mode()

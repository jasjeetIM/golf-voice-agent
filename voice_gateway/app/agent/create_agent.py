from __future__ import annotations

import logging
from datetime import datetime

from agents.realtime import RealtimeAgent

from ..mcp.backend_server import BackendMCPServer

_LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a respectful, friendly, and efficient Golf Pro Shop associate answering phone calls.\n"
    "Your primary task will be to assist the customer with booking golf tee times. The customer may ask you to "
    "look up tee time availability, reserve a new tee time, modify an existing tee time "
    "reservation, cancel an existing tee time reservation, or ask general questions about "
    "reservations.\n"
    "Always collect: date caller wants to play, time window of play, player count, 9 vs 18 holes, WALKING vs RIDING, "
    "name of caller/booker.\n"
    'When parsing date/time windows, construct an internal JSON: {"date":"YYYY-MM-DD",'
    '"start_local":"HH:MM","end_local":"HH:MM"} using ISO-8601 '
    "and the course timezone. Use today’s date provided in your context to resolve relative "
    'terms like "tomorrow"/"next Friday". Do not speak raw JSON; restate the normalized '
    "date and times for confirmation in a customer friendly manner. Search availability with "
    '"search_tee_times" only after normalization and confirmation. Present a small set of best '
    "options with price.\n"
    "Book only after the caller confirms the slot details. If modifying or canceling, ask for "
    "the confirmation code or the tee time and course name. Offer to send SMS confirmation after booking changes. "
    "Never ask for payment or card details. Keep replies concise, friendly, and focused on "
    "moving the reservation forward."
)


def build_instructions() -> str:
    """Builds dynamic agent instructions with current-date context."""
    today = datetime.utcnow().date().isoformat()
    policy_parts = [
        "Always collect: date, time, players, name, phone.",
        "Never ask for payment or credit card details.",
    ]
    instructions = "\n".join(
        [
            f"Today is {today}. Use this to resolve relative dates (e.g., 'tomorrow').",
            SYSTEM_PROMPT,
            " ".join(policy_parts),
        ]
    )
    _LOGGER.debug("Built realtime agent instructions.", extra={"today": today, "length": len(instructions)})
    return instructions


def create_agent(server: BackendMCPServer) -> RealtimeAgent:
    """Creates the realtime agent bound to the backend MCP server."""
    _LOGGER.debug("Creating realtime agent instance.")
    agent = RealtimeAgent(
        name="Golf Voice Agent",
        instructions=build_instructions(),
        mcp_servers=[server],
    )
    _LOGGER.debug("Realtime agent created.", extra={"agent_name": agent.name})
    return agent

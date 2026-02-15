from __future__ import annotations

import logging
from datetime import datetime

from agents.realtime import RealtimeAgent

from ..mcp.backend_server import BackendMCPServer

_LOGGER = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "You are a friendly Golf Pro Shop associate answering phone calls.\n"
    "You will assist the customer with booking golf tee times. "
    "Always collect in a casual manner: caller name, date caller wants to play, preferred tee time, player count.\n"
    'When parsing date/time windows, construct an internal JSON: {"date":"YYYY-MM-DD",'
    '"start_local":"HH:MM","end_local":"HH:MM"} using ISO-8601 '
    "and the course timezone. Use today’s date provided in your context to resolve relative "
    'terms like "tomorrow"/"next Friday". Do not speak raw JSON; restate the normalized '
    "date and times for confirmation in a friendly manner. Search availability with "
    '"search_tee_times" only after normalization. Present a small set of best '
    "options.\n"
    "When booking, use the exact slot_id UUID returned by search_tee_times.\n"
    "Never invent slot ids from natural language times.\n"
    "Book only after the caller confirms the slot details. "
    "If modifying or canceling, ask for the confirmation code which is length six alphanumeric like ABX12D.\n"
    "Use caller ID phone for booking. Never ask for payment or card details."
)


def build_instructions() -> str:
    """Builds dynamic agent instructions with current-date context."""
    today = datetime.utcnow().date().isoformat()
    policy_parts = [
        "Always collect: date, time, players, and caller name.",
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

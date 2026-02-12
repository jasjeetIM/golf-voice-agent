from __future__ import annotations

import json
from typing import Any

from mcp import Tool as MCPTool
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, PromptMessage, TextContent

from agents.mcp import MCPServer

from ..backend_client import BackendClient
from ..observability.logger import DbLogger
from shared import schemas


class BackendMCPServer(MCPServer):
    def __init__(self, client: BackendClient, logger: DbLogger | None = None):
        super().__init__(use_structured_content=True)
        self._client = client
        self._logger = logger

    def set_logger(self, logger: DbLogger | None) -> None:
        self._logger = logger

    async def connect(self):
        return None

    @property
    def name(self) -> str:
        return "backend_tools"

    async def cleanup(self):
        await self._client.close()

    async def list_tools(self, run_context=None, agent=None):
        return [
            MCPTool(
                name="search_tee_times",
                description="Search available tee times for a course on a specific date and time window with player count and WALKING/RIDING preference.",
                inputSchema=schemas.SearchTeeTimesRequest.model_json_schema(),
            ),
            MCPTool(
                name="book_tee_time",
                description="Book a tee time once the caller has confirmed date, time, players, 9 vs 18 holes, WALKING vs RIDING, and contact info.",
                inputSchema=schemas.BookTeeTimeRequest.model_json_schema(),
            ),
            MCPTool(
                name="modify_reservation",
                description="Modify a reservation's time, players, or walking/riding preference.",
                inputSchema=schemas.ModifyReservationRequest.model_json_schema(),
            ),
            MCPTool(
                name="cancel_reservation",
                description="Cancel a reservation by confirmation code.",
                inputSchema=schemas.CancelReservationRequest.model_json_schema(),
            ),
            MCPTool(
                name="send_sms_confirmation",
                description="Send a confirmation SMS to the caller.",
                inputSchema=schemas.SendSmsConfirmationRequest.model_json_schema(),
            ),
            MCPTool(
                name="get_reservation_details",
                description="Fetch reservation details by confirmation code.",
                inputSchema=schemas.GetReservationDetailsRequest.model_json_schema(),
            ),
            MCPTool(
                name="quote_reservation_change",
                description="Quote whether a reservation change is possible given slot capacity.",
                inputSchema=schemas.QuoteReservationChangeRequest.model_json_schema(),
            ),
            MCPTool(
                name="check_slot_capacity",
                description="Check if a slot has capacity for a number of players.",
                inputSchema=schemas.CheckSlotCapacityRequest.model_json_schema(),
            ),
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any] | None) -> CallToolResult:
        args = arguments or {}
        result: dict[str, Any]
        error_message = None

        try:
            if tool_name == "search_tee_times":
                result = await self._client.search_tee_times(args)
            elif tool_name == "book_tee_time":
                result = await self._client.book_tee_time(args)
            elif tool_name == "modify_reservation":
                result = await self._client.modify_reservation(args)
            elif tool_name == "cancel_reservation":
                result = await self._client.cancel_reservation(args)
            elif tool_name == "send_sms_confirmation":
                result = await self._client.send_sms_confirmation(args)
            elif tool_name == "get_reservation_details":
                result = await self._client.get_reservation_details(args)
            elif tool_name == "quote_reservation_change":
                result = await self._client.quote_reservation_change(args)
            elif tool_name == "check_slot_capacity":
                result = await self._client.check_slot_capacity(args)
            else:
                raise ValueError(f"Unknown tool: {tool_name}")
        except Exception as exc:
            error_message = str(exc)
            result = {"error": error_message}

        if self._logger:
            await self._logger.log_mcp_call(
                tool_call_id=None,
                server_name=self.name,
                method="call_tool",
                request_json={"tool_name": tool_name, "arguments": args},
                response_json=result,
                error_message=error_message,
            )

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structuredContent=result,
        )

    async def list_prompts(self) -> ListPromptsResult:
        return ListPromptsResult(prompts=[])

    async def get_prompt(self, name: str, arguments: dict[str, Any] | None = None) -> GetPromptResult:
        message = PromptMessage(role="user", content=TextContent(type="text", text=""))
        return GetPromptResult(description="", messages=[message])

"""MCP adapter that proxies tool invocations to backend HTTP endpoints."""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

from mcp import McpError
from mcp import Tool as MCPTool
from mcp.types import CallToolResult, ErrorData, GetPromptResult, ListPromptsResult, TextContent

from agents.mcp import MCPServer

from ..backend_client import BackendClient
from ..observability.logger import DbLogger
from shared import schemas

ToolHandler = Callable[[dict[str, Any]], Awaitable[dict[str, Any]]]
_LOGGER = logging.getLogger(__name__)

class BackendMCPServer(MCPServer):
    """Exposes backend business operations as MCP tools for the realtime agent."""

    def __init__(self, client: BackendClient, logger: DbLogger | None = None):
        """Initializes the MCP bridge server.

        Args:
            client: Backend HTTP client used to execute tool requests.
            logger: Optional observability logger for MCP request/response traces.
        """
        super().__init__(use_structured_content=True)
        self._client = client
        self._logger = logger
        self._call_id: str | None = logger.call_id if logger else None
        _LOGGER.debug(
            "BackendMCPServer initialized.",
            extra={"has_logger": logger is not None, "call_id": self._call_id},
        )

        # Centralized dispatch table keeps routing logic simple and testable.
        self._tool_dispatch: dict[str, ToolHandler] = {
            "search_tee_times": self._client.search_tee_times,
            "book_tee_time": self._client.book_tee_time,
            "modify_reservation": self._client.modify_reservation,
            "cancel_reservation": self._client.cancel_reservation,
            "send_sms_confirmation": self._client.send_sms_confirmation,
            "get_reservation_details": self._client.get_reservation_details,
            "quote_reservation_change": self._client.quote_reservation_change,
            "check_slot_capacity": self._client.check_slot_capacity,
        }

    def set_logger(self, logger: DbLogger | None) -> None:
        """Updates the logger used for MCP telemetry.

        Args:
            logger: New logger instance to associate with tool calls.
        """
        self._logger = logger
        self._call_id = logger.call_id if logger else self._call_id
        _LOGGER.debug(
            "BackendMCPServer logger updated.",
            extra={"has_logger": logger is not None, "call_id": self._call_id},
        )

    def set_call_id(self, call_id: str | None) -> None:
        """Binds a call id used to auto-populate tool request payloads.

        Args:
            call_id: Current Twilio call id.
        """
        self._call_id = call_id
        _LOGGER.debug("BackendMCPServer call_id updated.", extra={"call_id": call_id})

    async def connect(self) -> None:
        """No-op MCP connect hook for compatibility with MCPServer interface."""
        _LOGGER.debug("BackendMCPServer.connect() called.")
        return None

    @property
    def name(self) -> str:
        """Returns stable server name used in MCP metadata and logs."""
        return "backend_tools"

    async def cleanup(self) -> None:
        """Closes the underlying backend client."""
        _LOGGER.debug("BackendMCPServer.cleanup() closing backend client.")
        await self._client.close()

    async def list_tools(self, run_context=None, agent=None) -> list[MCPTool]:
        """Returns public tool definitions and request schemas.

        Args:
            run_context: MCP runtime context (unused).
            agent: Realtime agent instance (unused).

        Returns:
            MCP tool definitions exposed to the agent.
        """
        del run_context, agent
        _LOGGER.debug("BackendMCPServer.list_tools() called.")
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
        """Executes a backend tool call and returns MCP-formatted output.

        Args:
            tool_name: Tool name chosen by the agent.
            arguments: Parsed tool arguments.

        Returns:
            MCP call result with both text and structured payloads.
        """
        _LOGGER.debug(
            "BackendMCPServer.call_tool() invoked.",
            extra={"tool_name": tool_name, "has_arguments": arguments is not None, "call_id": self._call_id},
        )
        args = self._inject_call_id(arguments or {})
        result: dict[str, Any]
        error_message: str | None = None
        tool_call_id: str | None = None
        tool_call_external_id: str | None = None
        started = time.monotonic()

        if self._logger:
            tool_call_id, tool_call_external_id = await self._logger.resolve_tool_call_reference(
                tool_name=tool_name,
                args_json=args,
            )

        try:
            result = await self._dispatch_tool(tool_name, args)
            _LOGGER.debug(
                "BackendMCPServer.call_tool() succeeded.",
                extra={"tool_name": tool_name, "result_keys": sorted(result.keys()) if isinstance(result, dict) else None},
            )
        except Exception as exc:
            error_message = str(exc)
            result = {"error": error_message}
            _LOGGER.debug(
                "BackendMCPServer.call_tool() failed.",
                extra={"tool_name": tool_name, "error_message": error_message},
            )

        latency_ms = int((time.monotonic() - started) * 1000)

        if self._logger:
            await self._logger.log_mcp_call(
                tool_call_id=tool_call_id,
                tool_call_external_id=tool_call_external_id,
                server_name=self.name,
                method="call_tool",
                request_json={"tool_name": tool_name, "arguments": args},
                response_json=result,
                error_message=error_message,
                latency_ms=latency_ms,
            )

        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result))],
            structuredContent=result,
        )

    async def list_prompts(self) -> ListPromptsResult:
        """Returns an empty prompt catalog because this server is tool-only."""
        return ListPromptsResult(prompts=[])

    async def get_prompt(
        self, name: str, arguments: dict[str, Any] | None = None
    ) -> GetPromptResult:
        """Raises an MCP error because this server does not serve prompts.

        Args:
            name: Prompt name requested by caller.
            arguments: Prompt arguments (unused).

        Raises:
            McpError: Always raised with unknown-prompt metadata.
        """
        del arguments
        raise McpError(
            ErrorData(
                code=-32602,
                message=f"Unknown prompt: {name}",
                data={"available_prompts": []},
            )
        )

    def _inject_call_id(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Backfills call context into MCP tool invocations when absent.

        Args:
            arguments: Raw arguments from the tool invocation.

        Returns:
            Arguments with call-scoped values injected.
        """
        args = dict(arguments)
        if self._call_id and not args.get("call_id"):
            args["call_id"] = self._call_id
            _LOGGER.debug(
                "Injected call_id into MCP tool arguments.",
                extra={"call_id": self._call_id},
            )
        return args

    async def _dispatch_tool(self, tool_name: str, args: dict[str, Any]) -> dict[str, Any]:
        """Routes a tool invocation to the corresponding backend client method.

        Args:
            tool_name: Tool identifier selected by the agent.
            args: Validated tool argument payload.

        Raises:
            ValueError: If the tool name is not registered.

        Returns:
            Backend JSON result payload.
        """
        handler = self._tool_dispatch.get(tool_name)
        if handler is None:
            _LOGGER.debug("Unknown MCP tool requested.", extra={"tool_name": tool_name})
            raise ValueError(f"Unknown tool: {tool_name}")
        _LOGGER.debug("Dispatching MCP tool call to backend client.", extra={"tool_name": tool_name})
        return await handler(args)

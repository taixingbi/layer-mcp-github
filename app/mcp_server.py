"""FastMCP server instance."""

from mcp.server import FastMCP

from app.config import HTTP_HOST, HTTP_PORT

# Shared FastMCP app: tools registered in app.tools
mcp = FastMCP(
    "layer-mcp-github",
    host=HTTP_HOST,
    port=HTTP_PORT,
    stateless_http=True,
    json_response=True,
)

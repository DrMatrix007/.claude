# phone-mcp

MCP server exposing safe adb + flutter tools for debugging an Android/Flutter app on a connected device.

## Setup

```
pip install "mcp<2"
```

mcp 2.x renamed `FastMCP` to `MCPServer`; this server is written against the 1.x `FastMCP` API.

## Registration

Registered globally with:

```
claude mcp add -s user phone-debugger -- python C:\Users\ofrih\.claude\mcp-servers\phone-mcp\server.py
```

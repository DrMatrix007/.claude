# watch-mcp

MCP server with tools for building and running Garmin Connect IQ (Monkey C) watch apps in the simulator, for any Connect IQ project.

## Setup

```
pip install mcp
```

Registered globally with:

```
claude mcp add -s user watch-debugger -- python C:\Users\ofrih\.claude\mcp-servers\watch-mcp\server.py
```

## Notes

The `adb_connection` tool posts `WM_COMMAND` messages to the simulator's "adb Connection" menu using command IDs `6033` (start) and `6034` (release). These were found empirically for Connect IQ SDK 9.1.0's simulator build and may need to be rediscovered (by walking the simulator's window menu) for other SDK versions.

#!/usr/bin/env python3
"""IT Agents Orchestrator — MCP stdio server entry point.

VSCode / Claude Desktop setup
------------------------------
Add the following to your MCP config (see .vscode/mcp.json for VSCode):

    {
      "mcpServers": {
        "it-agents-orchestrator": {
          "command": "python",
          "args": ["PATH_TO_THIS_FILE/mcp_server.py"]
        }
      }
    }

Available tools once connected
--------------------------------
    ask_agent           Route any IT question to the best matching expert
    find_agents         Search the 10,000-agent catalog
    check_guardrails    Scan code / config for secrets and policy violations
    run_workflow        Execute a built-in workflow template
    agent_detail        Load full YAML definition for a specific agent ID

See future_agents/mcp/server.py for full documentation.
"""

from future_agents.mcp.server import main

if __name__ == "__main__":
    main()

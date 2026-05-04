# Embedded Altium Live Backend

This backend is absorbed from `altium-mcp` and bundled inside the `altium-pcb` skill so the skill owns both the planning layer and the live Altium bridge.

Included runtime pieces:

- `start_server.py`: bootstraps a local Windows Python virtual environment and starts the MCP-compatible live server.
- `server/main.py`: Python bridge server for Altium commands.
- `server/AltiumScript/`: DelphiScript project executed by Altium Designer.
- `server/symbol_placement_rules.txt`: symbol helper rules consumed by the backend.

Runtime files such as `.venv`, `config.json`, request/response JSON, logs, screenshots, and bytecode are intentionally ignored.

The copied code is MIT licensed; keep `LICENSE` with this backend.

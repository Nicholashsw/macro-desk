"""AgentCore Runtime entrypoint. The runtime runs this file; the server binds 0.0.0.0:8000/mcp."""

from macro_desk.server import main

if __name__ == "__main__":
    main()

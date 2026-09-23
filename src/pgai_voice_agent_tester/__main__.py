from pgai_voice_agent_tester import main, server

# LiveKit CLI (`lk agent ...`) discovers AgentServer via a module-level `server`.
__all__ = ["main", "server"]

if __name__ == "__main__":
    main()

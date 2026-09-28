"""Typed agent errors. The backend maps `status` to the HTTP response; the agent never raises raw exceptions."""


class AgentError(Exception):
    code = "agent_error"
    status = 500

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class InvalidInput(AgentError):
    code, status = "invalid_input", 422


class DuplicateContent(AgentError):
    code, status = "duplicate_content", 409


class LLMRateLimited(AgentError):
    code, status = "llm_rate_limited", 429


class LLMFailed(AgentError):
    code, status = "llm_failed", 502


class TranscriptionFailed(AgentError):
    code, status = "transcription_failed", 502


class MemoryUnavailable(AgentError):
    code, status = "memory_unavailable", 502


class ConfigMissing(AgentError):
    code, status = "config_missing", 503

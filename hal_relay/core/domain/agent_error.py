"""AgentError — domain exception for expected agent operational failures.

Raised by AgentClient implementations (PIRpcClient) for failures that are
operational rather than programming bugs: PI rejected a prompt, the stream
died mid-turn, a turn timed out and was aborted. The Relay catches this to
send the user a friendly error reply; unexpected exceptions still propagate
(so real bugs surface as tracebacks, not swallowed as 'something went wrong').

Kept in core/domain/ because it is part of the AgentClient contract: callers
depend on this type, not on RuntimeError.
"""


class AgentError(RuntimeError):
    """An expected operational failure of an agent client."""

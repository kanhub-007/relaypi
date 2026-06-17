"""AllowAllList — a test allowlist that admits everyone."""


class AllowAllList:
    def allows(self, msg) -> bool:  # noqa: ANN001 - duck-typed against InboundMessage
        return True

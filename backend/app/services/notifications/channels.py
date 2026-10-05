"""The seam between the outbox and a delivery provider."""

from typing import Protocol


class ChannelError(Exception):
    """A send failed. `permanent` means retrying cannot help (a number WhatsApp
    rejects, a mailbox that does not exist); `suppress` additionally means the
    address itself is bad and should stop receiving anything."""

    def __init__(self, message: str, *, permanent: bool, suppress: bool = False) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.suppress = suppress


class Channel(Protocol):
    name: str

    def available(self) -> bool:
        """Whether this channel is configured. Never raises."""
        ...

    async def send(
        self, address: str, template: str, params: dict, link_url: str, *, language: str = "en"
    ) -> str:
        """Deliver one notification and return the provider's message id."""
        ...

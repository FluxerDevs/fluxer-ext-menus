from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from fluxer.ext import menus
from fluxer.models.reaction import PartialEmoji


class FakeMessage:
    def __init__(self) -> None:
        self.id = 100
        self.edits: list[dict[str, Any]] = []
        self.reactions: list[Any] = []
        self.removed: list[Any] = []
        self.cleared = False
        self.deleted = False

    async def edit(self, **kwargs: Any) -> None:
        self.edits.append(kwargs)

    async def add_reaction(self, emoji: Any) -> None:
        self.reactions.append(emoji)

    async def remove_reaction(self, emoji: Any, user: Any) -> None:
        self.removed.append((emoji, user))

    async def clear_reactions(self) -> None:
        self.cleared = True

    async def delete(self) -> None:
        self.deleted = True


class FakeChannel:
    def __init__(self) -> None:
        self.guild = None
        self.message = FakeMessage()
        self.sent: list[dict[str, Any]] = []

    async def send(self, **kwargs: Any) -> FakeMessage:
        self.sent.append(kwargs)
        return self.message


class FakeBot:
    def __init__(self, payload: Any | None = None) -> None:
        self.user = SimpleNamespace(id=999)
        self.owner_id = None
        self.owner_ids = set()
        self._payload = payload
        self._closed = False

    async def wait_for(self, event: str, *, check=None, timeout=None) -> Any:
        assert event in {"raw_reaction_add", "raw_reaction_remove"}
        if self._payload is None:
            raise TimeoutError
        if check is None or check(self._payload):
            return self._payload
        raise TimeoutError

    def is_closed(self) -> bool:
        return self._closed


def make_ctx(bot: Any, channel: FakeChannel) -> Any:
    return SimpleNamespace(
        bot=bot,
        channel=channel,
        author=SimpleNamespace(id=42),
    )


def test_import_surface() -> None:
    assert menus.Menu
    assert menus.MenuPages
    assert menus.ListPageSource
    assert menus.GroupByPageSource
    assert menus.AsyncIteratorPageSource
    assert menus.Button
    assert menus.button


def test_emoji_casting() -> None:
    async def noop(self, payload) -> None:
        return None

    custom = menus.Button("<:wave:1234567890123>", noop)
    assert custom.emoji.name == "wave"
    assert custom.emoji.id == 1234567890123
    unicode_button = menus.Button("\N{WHITE HEAVY CHECK MARK}", noop)
    assert unicode_button.emoji.name == "\N{WHITE HEAVY CHECK MARK}"
    class Confirm(menus.Menu):
        @menus.button("\N{WHITE HEAVY CHECK MARK}")
        async def approve(self, payload):
            return None

    payload = SimpleNamespace(
        emoji=PartialEmoji.from_data({"name": "\N{WHITE HEAVY CHECK MARK}"})
    )
    assert Confirm()._button_for_payload(payload) is not None


@pytest.mark.asyncio
async def test_page_sources() -> None:
    class Source(menus.ListPageSource):
        async def format_page(self, menu, entries):
            return ",".join(map(str, entries))

    source = Source([1, 2, 3], per_page=2)
    assert source.is_paginating()
    assert source.get_max_pages() == 2
    assert await source.get_page(0) == [1, 2]

    grouped = menus.GroupByPageSource(["aa", "ab", "b"], key=lambda item: item[0], per_page=2)
    first = await grouped.get_page(0)
    assert first.key == "a"
    assert first.items == ["aa", "ab"]

    async def values():
        for value in range(3):
            yield value

    async_source = menus.AsyncIteratorPageSource(values(), per_page=2)
    await async_source.prepare()
    assert async_source.is_paginating()
    assert await async_source.get_page(0) == [0, 1]


@pytest.mark.asyncio
async def test_menu_pages_static_render() -> None:
    class Source(menus.ListPageSource):
        async def format_page(self, menu, entries):
            return {"content": ",".join(map(str, entries))}

    channel = FakeChannel()
    ctx = make_ctx(FakeBot(), channel)
    pages = menus.MenuPages(source=Source([1], per_page=2))
    await pages.start(ctx)
    assert channel.sent == [{"content": "1"}]


@pytest.mark.asyncio
async def test_reaction_menu_lifecycle() -> None:
    events: list[str] = []

    class Confirm(menus.Menu):
        async def send_initial_message(self, ctx, channel):
            return await channel.send(content="confirm")

        @menus.button("\N{WHITE HEAVY CHECK MARK}")
        async def approve(self, payload):
            events.append("approve")
            self.stop()

    menu = Confirm()
    button_emoji = next(iter(menu.buttons))
    payload = SimpleNamespace(message_id=100, user_id=42, emoji=button_emoji)
    channel = FakeChannel()
    ctx = make_ctx(FakeBot(payload), channel)

    await menu.start(ctx, wait=True)
    await menu.update(payload)

    assert events == ["approve"]
    assert channel.message.reactions == [button_emoji]


@pytest.mark.asyncio
async def test_missing_wait_for_for_interactive_menu() -> None:
    class NeedsReaction(menus.Menu):
        async def send_initial_message(self, ctx, channel):
            return await channel.send(content="menu")

        @menus.button("\N{WHITE HEAVY CHECK MARK}")
        async def approve(self, payload):
            self.stop()

    ctx = make_ctx(SimpleNamespace(user=SimpleNamespace(id=1)), FakeChannel())
    with pytest.raises(menus.MissingMenuCapability):
        await NeedsReaction().start(ctx)

from __future__ import annotations

import asyncio
import inspect
import itertools
import logging
import re
from collections import OrderedDict, namedtuple
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable, Mapping
from typing import Any

import fluxer

try:
    PartialEmoji = fluxer.PartialEmoji
except AttributeError:
    from fluxer.models.reaction import PartialEmoji


__version__ = "1.0.0a0"

log = logging.getLogger(__name__)

_custom_emoji = re.compile(r"<?(?P<animated>a)?:?(?P<name>[A-Za-z0-9_]+):(?P<id>[0-9]{13,20})>?")


class MenuError(Exception):
    pass


class CannotEmbedLinks(MenuError):
    def __init__(self) -> None:
        super().__init__("Bot does not have embed-link permission in this channel.")


class CannotSendMessages(MenuError):
    def __init__(self) -> None:
        super().__init__("Bot cannot send messages in this channel.")


class CannotAddReactions(MenuError):
    def __init__(self) -> None:
        super().__init__("Bot cannot add reactions in this channel.")


class CannotReadMessageHistory(MenuError):
    def __init__(self) -> None:
        super().__init__("Bot cannot read message history in this channel.")


class MissingMenuCapability(MenuError):
    def __init__(self, capability: str) -> None:
        super().__init__(f"Interactive menus require {capability}.")


class Position:
    __slots__ = ("number", "bucket")

    def __init__(self, number: int, *, bucket: int = 1) -> None:
        self.number = number
        self.bucket = bucket

    def __lt__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return (self.bucket, self.number) < (other.bucket, other.number)

    def __eq__(self, other: object) -> bool:
        return isinstance(other, Position) and (self.bucket, self.number) == (
            other.bucket,
            other.number,
        )

    def __le__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return not other < self

    def __gt__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return other < self

    def __ge__(self, other: object) -> bool:
        if not isinstance(other, Position):
            return NotImplemented
        return not self < other

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}: {self.number}>"


class First(Position):
    __slots__ = ()

    def __init__(self, number: int = 0) -> None:
        super().__init__(number, bucket=0)


class Last(Position):
    __slots__ = ()

    def __init__(self, number: int = 0) -> None:
        super().__init__(number, bucket=2)


class cached_property:
    def __init__(self, func: Callable[[Any], Any]) -> None:
        self.func = func
        self.name = func.__name__

    def __get__(self, instance: Any, owner: type[Any] | None = None) -> Any:
        if instance is None:
            return self
        value = self.func(instance)
        instance.__dict__[self.name] = value
        return value


async def maybe_coroutine(func: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    value = func(*args, **kwargs)
    if inspect.isawaitable(value):
        return await value
    return value


def _cast_emoji(obj: Any) -> PartialEmoji:
    if isinstance(obj, PartialEmoji):
        return obj

    value = str(obj)
    match = _custom_emoji.match(value)
    if match is not None:
        groups = match.groupdict()
        return PartialEmoji(
            name=groups["name"],
            id=int(groups["id"]),
            animated=bool(groups["animated"]),
        )
    return PartialEmoji(name=value, id=None, animated=False, unicode=value)


def _emoji_matches(left: PartialEmoji, right: Any) -> bool:
    if not isinstance(right, PartialEmoji):
        right = _cast_emoji(right)
    if left.id is not None or right.id is not None:
        return left == right
    left_value = left.unicode or left.name
    right_value = right.unicode or right.name
    return left_value == right_value


def _permission_enabled(permissions: Any, *names: str) -> bool:
    for name in names:
        value = getattr(permissions, name, None)
        if isinstance(value, bool):
            return value
        upper_name = name.upper()
        value = getattr(permissions, upper_name, None)
        if value is not None:
            try:
                return bool(permissions & value)
            except TypeError:
                return bool(value)
    return True


def _bot_is_closed(bot: Any) -> bool:
    is_closed = getattr(bot, "is_closed", None)
    if callable(is_closed):
        return bool(is_closed())
    return bool(getattr(bot, "_closed", False))


def _create_task(bot: Any, coro: Awaitable[Any]) -> asyncio.Task[Any]:
    loop = getattr(bot, "loop", None)
    if loop is not None and hasattr(loop, "create_task"):
        return loop.create_task(coro)
    return asyncio.create_task(coro)


class Button:
    __slots__ = ("emoji", "_action", "_skip_if", "position", "lock")

    def __init__(
        self,
        emoji: Any,
        action: Callable[..., Awaitable[Any]],
        *,
        skip_if: Callable[["Menu"], bool] | None = None,
        position: Position | None = None,
        lock: bool = True,
    ) -> None:
        self.emoji = _cast_emoji(emoji)
        self.action = action
        self.skip_if = skip_if
        self.position = position or Position(0)
        self.lock = lock

    @property
    def action(self) -> Callable[..., Awaitable[Any]]:
        return self._action

    @action.setter
    def action(self, value: Callable[..., Awaitable[Any]]) -> None:
        bound_self = getattr(value, "__self__", None)
        if bound_self is not None:
            if not isinstance(bound_self, Menu):
                raise TypeError(f"action bound method must be from Menu not {bound_self!r}")
            value = value.__func__
        if not inspect.iscoroutinefunction(value):
            raise TypeError(f"action must be a coroutine not {value!r}")
        self._action = value

    @property
    def skip_if(self) -> Callable[["Menu"], bool]:
        return self._skip_if

    @skip_if.setter
    def skip_if(self, value: Callable[["Menu"], bool] | None) -> None:
        if value is None:
            self._skip_if = lambda menu: False
            return
        bound_self = getattr(value, "__self__", None)
        if bound_self is not None:
            if not isinstance(bound_self, Menu):
                raise TypeError(f"skip_if bound method must be from Menu not {bound_self!r}")
            value = value.__func__
        self._skip_if = value

    def __call__(self, menu: "Menu", payload: Any) -> Awaitable[Any] | None:
        if self.skip_if(menu):
            return None
        return self._action(menu, payload)

    def __str__(self) -> str:
        return str(self.emoji)

    def is_valid(self, menu: "Menu") -> bool:
        return not self.skip_if(menu)


def button(emoji: Any, **kwargs: Any) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    def decorator(func: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        func.__menu_button__ = _cast_emoji(emoji)
        func.__menu_button_kwargs__ = kwargs
        return func

    return decorator


class _MenuMeta(type):
    @classmethod
    def __prepare__(cls, name: str, bases: tuple[type, ...], **kwargs: Any) -> OrderedDict[str, Any]:
        return OrderedDict()

    def __new__(
        cls,
        name: str,
        bases: tuple[type, ...],
        attrs: Mapping[str, Any],
        **kwargs: Any,
    ) -> type:
        inherit_buttons = kwargs.pop("inherit_buttons", True)
        new_cls = super().__new__(cls, name, bases, dict(attrs), **kwargs)
        buttons: list[Callable[..., Awaitable[Any]]] = []

        if inherit_buttons:
            for base in reversed(new_cls.__mro__):
                buttons.extend(
                    value
                    for value in base.__dict__.values()
                    if hasattr(value, "__menu_button__")
                )
        else:
            buttons.extend(
                value for value in attrs.values() if hasattr(value, "__menu_button__")
            )

        new_cls.__menu_buttons__ = buttons
        return new_cls

    def get_buttons(cls) -> OrderedDict[PartialEmoji, Button]:
        buttons: OrderedDict[PartialEmoji, Button] = OrderedDict()
        for func in cls.__menu_buttons__:
            emoji = func.__menu_button__
            buttons[emoji] = Button(emoji, func, **func.__menu_button_kwargs__)
        return buttons


class Menu(metaclass=_MenuMeta):
    def __init__(
        self,
        *,
        timeout: float = 180.0,
        delete_message_after: bool = False,
        clear_reactions_after: bool = False,
        check_embeds: bool = False,
        message: Any | None = None,
    ) -> None:
        self.timeout = timeout
        self.delete_message_after = delete_message_after
        self.clear_reactions_after = clear_reactions_after
        self.check_embeds = check_embeds
        self._can_remove_reactions = False
        self.__tasks: list[asyncio.Task[Any]] = []
        self.__timed_out = False
        self.__me: fluxer.Object | None = None
        self._running = True
        self.message = message
        self.ctx = None
        self.bot = None
        self._author_id: int | None = None
        self._buttons = self.__class__.get_buttons()
        self._lock = asyncio.Lock()
        self._event = asyncio.Event()

    @cached_property
    def buttons(self) -> dict[PartialEmoji, Button]:
        buttons = sorted(self._buttons.values(), key=lambda item: item.position)
        return {button.emoji: button for button in buttons if button.is_valid(self)}

    def add_button(self, button: Button, *, react: bool = False) -> Awaitable[None] | None:
        self._buttons[button.emoji] = button
        if not react:
            return None
        if not self.__tasks or self.message is None:
            async def dummy() -> None:
                raise MenuError("Menu has not been started yet")

            return dummy()

        async def wrapped() -> None:
            await self.message.add_reaction(button.emoji)
            self.buttons[button.emoji] = button

        return wrapped()

    def remove_button(self, emoji: Button | str | PartialEmoji, *, react: bool = False) -> Awaitable[None] | None:
        button_emoji = emoji.emoji if isinstance(emoji, Button) else _cast_emoji(emoji)
        self._buttons.pop(button_emoji, None)
        if not react:
            return None
        if not self.__tasks or self.message is None:
            async def dummy() -> None:
                raise MenuError("Menu has not been started yet")

            return dummy()

        async def wrapped() -> None:
            self.buttons.pop(button_emoji, None)
            await self.message.remove_reaction(button_emoji, self.__me)

        return wrapped()

    def clear_buttons(self, *, react: bool = False) -> Awaitable[None] | None:
        self._buttons.clear()
        if not react:
            return None
        if not self.__tasks or self.message is None:
            async def dummy() -> None:
                raise MenuError("Menu has not been started yet")

            return dummy()

        async def wrapped() -> None:
            if self._can_remove_reactions:
                try:
                    del self.buttons
                except AttributeError:
                    pass
                await self.message.clear_reactions()
                return
            reactions = list(self.buttons.keys())
            try:
                del self.buttons
            except AttributeError:
                pass
            for reaction in reactions:
                await self.message.remove_reaction(reaction, self.__me)

        return wrapped()

    def should_add_reactions(self) -> bool:
        return bool(self.buttons)

    def _verify_permissions(self, ctx: Any, channel: Any, permissions: Any | None) -> None:
        if permissions is None:
            self._can_remove_reactions = False
            return
        if not _permission_enabled(permissions, "send_messages"):
            raise CannotSendMessages()
        if self.check_embeds and not _permission_enabled(permissions, "embed_links"):
            raise CannotEmbedLinks()
        self._can_remove_reactions = _permission_enabled(permissions, "manage_messages")
        if self.should_add_reactions():
            if not _permission_enabled(permissions, "add_reactions"):
                raise CannotAddReactions()
            if not _permission_enabled(permissions, "read_message_history"):
                raise CannotReadMessageHistory()

    def reaction_check(self, payload: Any) -> bool:
        if self.message is None:
            return False
        if getattr(payload, "message_id", None) != self.message.id:
            return False
        allowed_ids = {self._author_id}
        allowed_ids.update(getattr(self.bot, "owner_ids", set()) or set())
        owner_id = getattr(self.bot, "owner_id", None)
        if owner_id is not None:
            allowed_ids.add(owner_id)
        if getattr(payload, "user_id", None) not in allowed_ids:
            return False
        return self._button_for_payload(payload) is not None

    def _button_for_payload(self, payload: Any) -> Button | None:
        emoji = getattr(payload, "emoji", None)
        for button_emoji, button in self.buttons.items():
            if _emoji_matches(button_emoji, emoji):
                return button
        return None

    async def _internal_loop(self) -> None:
        tasks: list[asyncio.Task[Any]] = []
        try:
            self.__timed_out = False
            while self._running:
                tasks = [
                    asyncio.create_task(
                        self.bot.wait_for("raw_reaction_add", check=self.reaction_check)
                    ),
                    asyncio.create_task(
                        self.bot.wait_for("raw_reaction_remove", check=self.reaction_check)
                    ),
                ]
                done, pending = await asyncio.wait(
                    tasks,
                    timeout=self.timeout,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if not done:
                    raise asyncio.TimeoutError
                payload = done.pop().result()
                _create_task(self.bot, self.update(payload))
        except asyncio.TimeoutError:
            self.__timed_out = True
        finally:
            self._event.set()
            for task in tasks:
                task.cancel()
            try:
                await self.finalize(self.__timed_out)
            except Exception:
                log.exception("Menu finalizer failed.")
            finally:
                self.__timed_out = False

            if _bot_is_closed(self.bot):
                return

            try:
                if self.delete_message_after and self.message is not None:
                    await self.message.delete()
                    return
                if self.clear_reactions_after and self.message is not None:
                    if self._can_remove_reactions:
                        await self.message.clear_reactions()
                    else:
                        for button_emoji in self.buttons:
                            try:
                                await self.message.remove_reaction(button_emoji, self.__me)
                            except fluxer.HTTPException:
                                continue
            except Exception:
                log.exception("Menu cleanup failed.")

    async def update(self, payload: Any) -> None:
        button = self._button_for_payload(payload)
        if button is None:
            return
        if not self._running:
            return
        try:
            if button.lock:
                async with self._lock:
                    if self._running:
                        await button(self, payload)
            else:
                await button(self, payload)
        except Exception as exc:
            await self.on_menu_button_error(exc)

    async def on_menu_button_error(self, exc: Exception) -> None:
        log.exception("Unhandled exception during menu update.", exc_info=exc)

    async def start(self, ctx: Any, *, channel: Any | None = None, wait: bool = False) -> None:
        try:
            del self.buttons
        except AttributeError:
            pass

        self.bot = bot = ctx.bot
        self.ctx = ctx
        self._author_id = ctx.author.id
        channel = channel or ctx.channel

        me = getattr(bot, "user", None)
        guild = getattr(channel, "guild", None)
        if guild is not None:
            me = getattr(guild, "me", me)

        permissions = None
        permissions_for = getattr(channel, "permissions_for", None)
        if callable(permissions_for) and me is not None:
            permissions = permissions_for(me)
        self.__me = fluxer.Object(id=getattr(me, "id", 0))
        self._verify_permissions(ctx, channel, permissions)

        if self.should_add_reactions() and not callable(getattr(bot, "wait_for", None)):
            raise MissingMenuCapability("Bot.wait_for")

        self._event.clear()
        msg = self.message
        if msg is None:
            self.message = msg = await self.send_initial_message(ctx, channel)

        if self.should_add_reactions():
            for task in self.__tasks:
                task.cancel()
            self.__tasks.clear()
            self._running = True
            self.__tasks.append(_create_task(bot, self._internal_loop()))

            async def add_reactions_task() -> None:
                for emoji in self.buttons:
                    await msg.add_reaction(emoji)

            self.__tasks.append(_create_task(bot, add_reactions_task()))

            if wait:
                await self._event.wait()

    async def finalize(self, timed_out: bool) -> None:
        return None

    async def send_initial_message(self, ctx: Any, channel: Any) -> Any:
        raise NotImplementedError

    def stop(self) -> None:
        self._running = False
        for task in self.__tasks:
            task.cancel()
        self.__tasks.clear()


class PageSource:
    async def _prepare_once(self) -> None:
        if not getattr(self, "_PageSource__prepared", False):
            await self.prepare()
            self.__prepared = True

    async def prepare(self) -> None:
        return None

    def is_paginating(self) -> bool:
        raise NotImplementedError

    def get_max_pages(self) -> int | None:
        return None

    async def get_page(self, page_number: int) -> Any:
        raise NotImplementedError

    async def format_page(self, menu: Menu, page: Any) -> str | fluxer.Embed | dict[str, Any]:
        raise NotImplementedError


class MenuPages(Menu):
    def __init__(self, source: PageSource, **kwargs: Any) -> None:
        self._source = source
        self.current_page = 0
        super().__init__(**kwargs)

    @property
    def source(self) -> PageSource:
        return self._source

    async def change_source(self, source: PageSource) -> None:
        if not isinstance(source, PageSource):
            raise TypeError(f"Expected {PageSource!r} not {source.__class__!r}.")
        self._source = source
        self.current_page = 0
        if self.message is not None:
            await source._prepare_once()
            await self.show_page(0)

    def should_add_reactions(self) -> bool:
        return self._source.is_paginating()

    async def _get_kwargs_from_page(self, page: Any) -> dict[str, Any]:
        value = await maybe_coroutine(self._source.format_page, self, page)
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            return {"content": value, "embed": None}
        if isinstance(value, fluxer.Embed):
            return {"embed": value, "content": None}
        raise TypeError("Page formatter must return str, Embed, or dict.")

    async def show_page(self, page_number: int) -> None:
        page = await self._source.get_page(page_number)
        self.current_page = page_number
        kwargs = await self._get_kwargs_from_page(page)
        await self.message.edit(**kwargs)

    async def send_initial_message(self, ctx: Any, channel: Any) -> Any:
        page = await self._source.get_page(0)
        kwargs = await self._get_kwargs_from_page(page)
        return await channel.send(**kwargs)

    async def start(self, ctx: Any, *, channel: Any | None = None, wait: bool = False) -> None:
        await self._source._prepare_once()
        await super().start(ctx, channel=channel, wait=wait)

    async def show_checked_page(self, page_number: int) -> None:
        max_pages = self._source.get_max_pages()
        try:
            if max_pages is None or max_pages > page_number >= 0:
                await self.show_page(page_number)
        except IndexError:
            pass

    async def show_current_page(self) -> None:
        if self._source.is_paginating():
            await self.show_page(self.current_page)

    def _skip_double_triangle_buttons(self) -> bool:
        max_pages = self._source.get_max_pages()
        return max_pages is None or max_pages <= 2

    @button(
        "\N{BLACK LEFT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}",
        position=First(0),
        skip_if=_skip_double_triangle_buttons,
    )
    async def go_to_first_page(self, payload: Any) -> None:
        await self.show_page(0)

    @button("\N{BLACK LEFT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}", position=First(1))
    async def go_to_previous_page(self, payload: Any) -> None:
        await self.show_checked_page(self.current_page - 1)

    @button("\N{BLACK RIGHT-POINTING TRIANGLE}\N{VARIATION SELECTOR-16}", position=Last(0))
    async def go_to_next_page(self, payload: Any) -> None:
        await self.show_checked_page(self.current_page + 1)

    @button(
        "\N{BLACK RIGHT-POINTING DOUBLE TRIANGLE WITH VERTICAL BAR}\N{VARIATION SELECTOR-16}",
        position=Last(1),
        skip_if=_skip_double_triangle_buttons,
    )
    async def go_to_last_page(self, payload: Any) -> None:
        max_pages = self._source.get_max_pages()
        if max_pages is not None:
            await self.show_page(max_pages - 1)

    @button("\N{BLACK SQUARE FOR STOP}\N{VARIATION SELECTOR-16}", position=Last(2))
    async def stop_pages(self, payload: Any) -> None:
        self.stop()


class ListPageSource(PageSource):
    def __init__(self, entries: list[Any] | tuple[Any, ...], *, per_page: int) -> None:
        self.entries = entries
        self.per_page = per_page
        pages, left_over = divmod(len(entries), per_page)
        self._max_pages = pages + bool(left_over)

    def is_paginating(self) -> bool:
        return len(self.entries) > self.per_page

    def get_max_pages(self) -> int:
        return self._max_pages

    async def get_page(self, page_number: int) -> Any:
        if self.per_page == 1:
            return self.entries[page_number]
        base = page_number * self.per_page
        return self.entries[base : base + self.per_page]


_GroupByEntry = namedtuple("_GroupByEntry", "key items")


class GroupByPageSource(ListPageSource):
    def __init__(
        self,
        entries: Iterable[Any],
        *,
        key: Callable[[Any], Any],
        per_page: int,
        sort: bool = True,
    ) -> None:
        source = entries if not sort else sorted(entries, key=key)
        nested = []
        self.nested_per_page = per_page
        for group_key, group in itertools.groupby(source, key=key):
            items = list(group)
            nested.extend(
                _GroupByEntry(key=group_key, items=items[index : index + per_page])
                for index in range(0, len(items), per_page)
            )
        super().__init__(nested, per_page=1)

    async def format_page(self, menu: Menu, entry: Any) -> dict[str, Any]:
        raise NotImplementedError


def _aiter(obj: Any) -> AsyncIterator[Any]:
    try:
        iterator = obj.__aiter__()
    except AttributeError:
        raise TypeError(f"{obj.__class__.__name__!r} object is not an async iterable") from None
    if inspect.isawaitable(iterator):
        raise TypeError(f"{obj.__class__.__name__!r} object is not an async iterable")
    return iterator


class AsyncIteratorPageSource(PageSource):
    def __init__(self, iterator: AsyncIterator[Any], *, per_page: int) -> None:
        self.iterator = _aiter(iterator)
        self.per_page = per_page
        self._exhausted = False
        self._cache: list[Any] = []

    async def _iterate(self, count: int) -> None:
        for _ in range(count):
            try:
                self._cache.append(await self.iterator.__anext__())
            except StopAsyncIteration:
                self._exhausted = True
                break

    async def prepare(self) -> None:
        await self._iterate(self.per_page + 1)

    def is_paginating(self) -> bool:
        return len(self._cache) > self.per_page

    async def _get_single_page(self, page_number: int) -> Any:
        if page_number < 0:
            raise IndexError("Negative page number.")
        if not self._exhausted and len(self._cache) <= page_number:
            await self._iterate((page_number + 1) - len(self._cache))
        return self._cache[page_number]

    async def _get_page_range(self, page_number: int) -> list[Any]:
        if page_number < 0:
            raise IndexError("Negative page number.")
        base = page_number * self.per_page
        max_base = base + self.per_page
        if not self._exhausted and len(self._cache) <= max_base:
            await self._iterate((max_base + 1) - len(self._cache))
        entries = self._cache[base:max_base]
        if not entries and max_base > len(self._cache):
            raise IndexError("Went too far")
        return entries

    async def get_page(self, page_number: int) -> Any:
        if self.per_page == 1:
            return await self._get_single_page(page_number)
        return await self._get_page_range(page_number)


__all__ = (
    "AsyncIteratorPageSource",
    "Button",
    "CannotAddReactions",
    "CannotEmbedLinks",
    "CannotReadMessageHistory",
    "CannotSendMessages",
    "First",
    "GroupByPageSource",
    "Last",
    "ListPageSource",
    "Menu",
    "MenuError",
    "MenuPages",
    "MissingMenuCapability",
    "PageSource",
    "Position",
    "button",
)

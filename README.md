# fluxer-ext-menus

Reaction-based menu helpers for `fluxer.py`.

Includes reaction buttons, paginated menus, and synchronous and asynchronous
page sources. Requires Python 3.14 or newer and `fluxer.py>=0.5.0a4`.

## Install

```sh
python -m pip install --pre fluxer-ext-menus
```

The PyPI command applies once the first release is published. To install this
checkout now, run `python -m pip install .` from the repository directory.
Until the required `fluxer.py` release is on PyPI, install that library from its
compatible checkout first: `python -m pip install ../fluxer.py` in this workspace.

## Example

```py
from fluxer.ext import commands, menus


class Confirm(menus.Menu):
    def __init__(self, prompt: str):
        super().__init__(timeout=30.0, delete_message_after=True)
        self.prompt = prompt
        self.result = None

    async def send_initial_message(self, ctx, channel):
        return await channel.send(self.prompt)

    @menus.button("\N{WHITE HEAVY CHECK MARK}")
    async def confirm(self, payload):
        self.result = True
        self.stop()

    @menus.button("\N{CROSS MARK}")
    async def deny(self, payload):
        self.result = False
        self.stop()


bot = commands.Bot(command_prefix="!")


@bot.command()
async def ask(ctx):
    menu = Confirm("Continue?")
    await menu.start(ctx, wait=True)
    await ctx.send(f"result={menu.result}")
```

Interactive menus require a bot object with `wait_for(event, *, check=None, timeout=None)` support for `raw_reaction_add` and `raw_reaction_remove`.

## Development

Create and activate a Python 3.14+ virtual environment, then run:

```sh
python -m pip install ".[dev]"
python -m pytest
python -m ruff check .
python -m build
python -m twine check --strict dist/*
```

Use a regular installation and reinstall after changing the library. This
extension shares the `fluxer.ext` package supplied by `fluxer.py`; a regular
installation places both distributions in the same environment. Tests use the
installed package and do not depend on adjacent repositories or import-path
patches.

See [PUBLISHING.md](PUBLISHING.md) for TestPyPI, PyPI, and release setup.

## License

Licensed under the [MIT License](LICENSE).

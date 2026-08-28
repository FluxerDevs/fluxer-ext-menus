# fluxer-ext-menus

Reaction-based menu helpers for `fluxer.py`.

## Install

```sh
python -m pip install -e .
```

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

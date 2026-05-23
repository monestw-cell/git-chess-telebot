"""Handler modules for the Telegram bot."""

from bot.handlers import (
    menu,
    setup,
    github_repos,
    github_files,
    github_workflows,
    chess_handler,
)

ALL_MODULES = [menu, setup, github_repos, github_files, github_workflows, chess_handler]


def register_all(bot):
    """Register all handler modules with the bot instance."""
    for module in ALL_MODULES:
        module.register(bot)

"""Handler modules for the Telegram bot."""

from bot.handlers import (
    menu,
    setup,
    github_repos,
    github_files,
    github_workflows,
    chess_handler,
    github_branches,
    github_issues,
    github_prs,
    github_collabs,
    github_releases,
    github_advanced,
    github_actions,
    github_secrets,
    github_editor,
    github_search,
    github_gists,
    github_notifications,
)

ALL_MODULES = [
    menu, setup, github_repos, github_files, github_workflows, chess_handler,
    github_branches, github_issues, github_prs, github_collabs,
    github_releases, github_advanced, github_actions, github_secrets,
    github_editor, github_search, github_gists, github_notifications,
]


def register_all(bot):
    """Register all handler modules with the bot instance."""
    for module in ALL_MODULES:
        module.register(bot)

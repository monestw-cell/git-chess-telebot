"""Centralized user state management replacing scattered global dicts."""


class UserStateManager:
    """Manages per-user session state."""

    def __init__(self):
        self._states = {}

    def get(self, chat_id):
        """Get user state dict, creating if not exists."""
        if chat_id not in self._states:
            self._states[chat_id] = {}
        return self._states[chat_id]

    def clear(self, chat_id):
        """Clear user state but preserve repo_map, wf_map, and current_repo."""
        old = self._states.get(chat_id, {})
        preserved = {}
        for key in ('repo_map', 'wf_map', 'current_repo'):
            if key in old:
                preserved[key] = old[key]
        self._states[chat_id] = preserved

    def set_field(self, chat_id, key, value):
        """Set a specific field in user state."""
        state = self.get(chat_id)
        state[key] = value

    def get_field(self, chat_id, key, default=None):
        """Get a specific field from user state."""
        return self.get(chat_id).get(key, default)

    def active_count(self):
        """Return number of active user sessions."""
        return len(self._states)


# Global state manager instance
user_state = UserStateManager()

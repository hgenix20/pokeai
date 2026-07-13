"""skills/ — callable game skills (F3): the components the task queue dispatches.

Each skill is a verb the planner can call ("navigate here", "buy this", "find a
Pokemon"). They compose the verified perception/navigation stack. See
docs/FIRERED_REDESIGN.md §7.
"""
from pokeai.skills.navigate_to import NavigateTo

__all__ = ["NavigateTo"]

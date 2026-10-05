"""Language of the person a message is being sent to (not the author of the current update)."""
from bot.database.methods.read import get_user_languages


async def language_of(user_id: int) -> str | None:
    """The user's chosen language, or None (-> the bot default) when they have not chosen or are unknown."""
    return (await get_user_languages([user_id])).get(user_id)

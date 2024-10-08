import logging
import time
from typing import Optional

from steamship import Steamship, SteamshipError,Tag
from steamship.agents.service.agent_service import AgentService
from steamship.invocable import post
from steamship.invocable.package_mixin import PackageMixin

from agents.onboarding_agent import OnboardingAgent, _is_allowed_by_moderation
from generators.generator_context_utils import get_profile_image_generator
from schema.game_state import ActiveMode, GameState

# An instnace is a game instance.
from utils.context_utils import RunNextAgentException, append_chat_intro_messages, append_onboarding_message, get_game_state, save_game_state
from utils.error_utils import record_and_throw_unrecoverable_error
from utils.generation_utils import generate_story_intro
from utils.tags import QuestIdTag, SceneTag, TagKindExtensions,StoryContextTag,CharacterTag,InstructionsTag,QuestTag


class OnboardingMixin(PackageMixin):
    """Provides endpoints for Onboarding."""

    agent_service: AgentService
    client: Steamship
    openai_api_key: str

    def __init__(
        self, client: Steamship, agent_service: AgentService, openai_api_key: str
    ):
        self.client = client
        self.agent_service = agent_service
        self.openai_api_key = openai_api_key

    @post("/set_character_name")
    def set_character_name(self, name: str, **kwargs):
        """Set the character name (moderation is enabled)"""
        context = self.agent_service.build_default_context(**kwargs)

        if not _is_allowed_by_moderation(name, self.openai_api_key):
            raise SteamshipError(
                "Supplied 'name' was rejected by game's moderation filter. Please try again."
            )

        game_state = get_game_state(context)
        game_state.player.name = name
        save_game_state(game_state, context)

    @post("/set_character_background")
    def set_character_background(self, background: str, **kwargs):
        """Set the character background (moderation is enabled)."""
        context = self.agent_service.build_default_context(**kwargs)

        if not _is_allowed_by_moderation(background, self.openai_api_key):
            raise SteamshipError(
                "Supplied 'background' was rejected by game's moderation filter. Please try again."
            )

        game_state = get_game_state(context)
        game_state.player.background = background
        save_game_state(game_state, context)

    @post("/set_character_description")
    def set_character_description(
        self,
        description: str,
        update: Optional[bool] = True,
        **kwargs,
    ):
        """Set the character description (moderation is enabled)."""
        context = self.agent_service.build_default_context(**kwargs)

        if not _is_allowed_by_moderation(description, self.openai_api_key):
            raise SteamshipError(
                "Supplied 'description' was rejected by game's moderation filter. Please try again."
            )

        game_state = get_game_state(context)
        game_state.player.description = description

        if game_state.player.description and game_state.player.name:
            if (not game_state.image_generation_requested()) or update:
                if image_gen := get_profile_image_generator(context):
                    start = time.perf_counter()
                    task = image_gen.request_profile_image_generation(context=context)
                    character_image_block = task.wait().blocks[0]
                    game_state.player.image = character_image_block.raw_data_url
                    game_state.profile_image_url = character_image_block.raw_data_url
                    logging.debug(
                        f"Onboarding endpoint image gen: {time.perf_counter()-start}"
                    )

        save_game_state(game_state, context)

    @post("/complete_onboarding")
    def complete_onboarding(self, **kwargs) -> bool:  # noqa: C901
        """Attempts to complete onboarding."""
        start = time.perf_counter()
        try:
            context = self.agent_service.build_default_context()
            game_state = get_game_state(context)

            # These fields are required for the game to continue. If we're calling complete_onboarding and they're not
            # set, we should fail early.
            if not game_state.player.name:
                raise SteamshipError(
                    "Unable to complete onboarding: player name was None"
                )
            if not game_state.player.description:
                raise SteamshipError(
                    "Unable to complete onboarding: player description was None"
                )
            if not game_state.player.background:
                raise SteamshipError(
                    "Unable to complete onboarding: player background was None"
                )
            
            # These fields must pass validation for the game to continue without later problems.
            # If they don't pass validation, then we should fail early.
            # TODO: streamline for mass validation ?
            if game_state.moderate_mode:
                moderation_start = time.perf_counter()
                if not _is_allowed_by_moderation(
                    game_state.player.name, self.openai_api_key
                ):
                    raise SteamshipError(
                        "Supplied 'name' was rejected by game's moderation filter. Please try again."
                    )
                if not _is_allowed_by_moderation(
                    game_state.player.background, self.openai_api_key
                ):
                    raise SteamshipError(
                        "Supplied 'background' was rejected by game's moderation filter. Please try again."
                    )
                if not _is_allowed_by_moderation(
                    game_state.player.description, self.openai_api_key
                ):
                    raise SteamshipError(
                        "Supplied 'description' was rejected by game's moderation filter. Please try again."
                    )
                logging.debug(f"Moderation time: {time.perf_counter() - moderation_start}")

            if game_state.active_mode != ActiveMode.ONBOARDING:
                raise SteamshipError(
                    message=f"Unable to complete onboarding -- it appears to be complete! Currently in state {game_state.active_mode.value}"
                )

            self.onboarding_agent = OnboardingAgent(
                client=self.client, tools=[], openai_api_key=self.openai_api_key
            )
            logging.debug(f"Before agent: {time.perf_counter() - start}")
            self.onboarding_agent.run(context)
            logging.debug(f"After agent: {time.perf_counter() - start}")
            return True
        except RunNextAgentException:
            return game_state.chat_history_for_onboarding_complete
        except BaseException as e:
            logging.error(e)
            context = self.agent_service.build_default_context()
            record_and_throw_unrecoverable_error(e, context)

    @post("/generate_story_intro")
    def generate_story_intro(self) -> str:
        try:
            context = self.agent_service.build_default_context()
            game_state = get_game_state(context)
            story_intro = generate_story_intro(
                player=game_state.player, context=context
            )
            return story_intro
        except BaseException as e:
            context = self.agent_service.build_default_context()
            record_and_throw_unrecoverable_error(e, context)

    @post("init_companion_chat")
    def init_companion_chat(self,name:str,description:str = "",personality:str = "",appearance:str = "",background:str = "",seed:str ="",tags:str = "", **kwargs) -> bool:
        try:
            if personality == "":
                personality = "N/A"
            if background == "" or background =="\n":
                background = "N/A"
            if appearance == "":
                appearance = "N/A"
            if description == "":
                description = "N/A"
            if tags == "":
                tags = "Fictional drama"
    
            context = self.agent_service.build_default_context()
            #onboarding_message = GameState.onboarding_message if hasattr(GameState, 'onboarding_message') else "Default onboarding message"
            
            game_state = get_game_state(context)
            if not game_state:
                logging.error("Game state is None, cannot proceed with clearing history.")
                return False
                
            game_state.player.name = name
            game_state.player.description = description
            game_state.player.personality = personality
            game_state.player.appearance = appearance
            game_state.player.background = background
            game_state.tags = tags
            if seed != "":
                game_state.player.seed_message = seed
            
            save_game_state(game_state, context)
            
            if not game_state.onboarding_agent_has_completed:
                self.onboarding_agent = OnboardingAgent(
                    client=self.client, tools=[], openai_api_key=self.openai_api_key
                )
                self.onboarding_agent.run(context)
                return True
            else:
                return False
        except RunNextAgentException:
            return game_state.chat_history_for_onboarding_complete
        except BaseException as e:
            logging.error(e)
            context = self.agent_service.build_default_context()
            record_and_throw_unrecoverable_error(e, context)

    @post("update_companion_chat")
    def update_companion_chat(self,name:str,description:str = "",personality:str = "",appearance:str = "",background:str = "",seed:str ="",tags:str ="", **kwargs) -> bool:
        """Update companion details in game state and re-add system onboarding message."""
        try:
            if personality == "":
                personality = "N/A"
            if background == "":
                background = "N/A"
            if appearance == "":
                appearance = "N/A"
            if description == "":
                description = "N/A"
            if tags == "":
                tags = "N/A"    

            context = self.agent_service.build_default_context()
            game_state = get_game_state(context)
            if not game_state:
                logging.error("Game state is None, cannot proceed.")
                return False
            temp_game_state = GameState()    
            game_state.onboarding_message = temp_game_state.onboarding_message
            game_state.player.name = name
            game_state.player.description = description
            game_state.player.personality = personality
            game_state.player.appearance = appearance
            game_state.player.background = background  
            game_state.player.seed_message = seed
            game_state.tags = tags
            save_game_state(game_state, context)

            append_onboarding_message(context)
            
            return True

        except BaseException as e:
            logging.error(e)
            context = self.agent_service.build_default_context()
            record_and_throw_unrecoverable_error(e, context)

    
    @post("append_onboarding_message")
    def append_onboarding_message(self, message: str, **kwargs) -> bool:
        try:            
            context = self.agent_service.build_default_context()
            game_state = get_game_state(context)

            append_onboarding_message(context)
            append_chat_intro_messages(context)
            
            return True
        except BaseException as e:
            context = self.agent_service.build_default_context()
            record_and_throw_unrecoverable_error(e, context)
            return False
import json
import logging
from datetime import datetime, timezone
from enum import Enum
from random import randint, random
import textwrap
from typing import Dict, List

from pydantic.utils import Representation
from steamship import SteamshipError, Tag
from steamship.agents.logging import AgentLogging
from steamship.agents.schema import Action, AgentContext
from steamship.agents.schema.action import FinishAction

from generators.generator_context_utils import (
    get_music_generator,
    get_quest_background_image_generator,
    get_chat_image_generator
)
from schema.game_state import GameState
from schema.quest import Quest, QuestChallenge, QuestDescription
from schema.server_settings import Difficulty
from tools.end_quest_tool import EndQuestTool
from utils.context_utils import (
    FinishActionException,
    await_ask,
    get_current_quest,
    get_game_state,
    get_server_settings,
    save_game_state,
)
from utils.generation_utils import (
    await_streamed_block,
    generate_image_description,
    generate_is_solution_attempt,
    generate_likelihood_estimation,
    generate_quest_arc,
    send_story_generation,
)
from utils.interruptible_python_agent import InterruptiblePythonAgent
from utils.moderation_utils import mark_block_as_excluded
from utils.tags import InstructionsTag, QuestIdTag, QuestTag, TagKindExtensions



class ChatAgent(InterruptiblePythonAgent):
    """
    The Chat agent goes on a chat!

    HOW THIS AGENT IS ACTIVATED
    ===========================

    The game log defers to this agent when `game_state.current_quest` is not None.

    The `game_state.current_quest` argument matches `game_state.quests[].name` and is used to provide the
    Quest object to this agent at construction time so that it has a handle on where to load/store state.

    WHAT CAUSES THAT ACTIVATION TO HAPPEN
    =====================================

    The `use_settings.current_quest` string is set to not-None when the following things happen:

    - POST /start_quest (See the quest_mixin)
    - maybe later: The Camp Agent runs the Start Quest Tool

    It can be slotted into as a state machine sub-agent by the overall agent.
    """
    
    def run(self, context: AgentContext) -> Action:  # noqa: C901
        """
        It could go in a tool, but that doesn't feel necessary... there are some other spots where tools feel very
        well fit, but this might be better left open-ended, so we can stop/start things as we like.
        """
        
        # Load the main things we're working with. These can modified and the save_game_state called at any time
        game_state = get_game_state(context)
        player = game_state.player
        quest = get_current_quest(context)
        server_settings = get_server_settings(context)


        logging.debug(
            "Running Chat Agent",
            extra={
                AgentLogging.IS_MESSAGE: True,
                AgentLogging.MESSAGE_TYPE: AgentLogging.AGENT,
                AgentLogging.MESSAGE_AUTHOR: AgentLogging.TOOL,
                AgentLogging.AGENT_NAME: self.__class__.__name__,
            },
        )
        
        if not game_state.chat_intro_complete:
            #user_prompt = await_ask(
                #f"What do you say next?",
                #context,
                #key_suffix=
                #f"user input {quest.name}"

            #)
            game_state.chat_intro_complete = True
            user_prompt =""
            if context.chat_history and context.chat_history.last_user_message:
                if context.chat_history.last_user_message.text:
                    user_prompt = context.chat_history.last_user_message.text
                
            save_game_state(game_state, context)
            
            
            block = send_story_generation(
            prompt=user_prompt,
            quest_name=quest.name,
            context=context,
            )
            response_block = await_streamed_block(block, context)
            if server_settings.enable_images_in_chat: 
                task = self.handle_image_generation(game_state, context, quest, response_block.text)

        

        if game_state.chat_mode and game_state.chat_intro_complete:      
           
            user_prompt = await_ask(
                f"What do you say next?",
                context,
                key_suffix=
                f"user input {quest.name}"

            )
            save_game_state(game_state, context)
            additional_info = ""

                
            
            response_block = self.respond_to_user(game_state,context,quest,user_prompt=user_prompt,additional_context=additional_info)
            if server_settings.enable_images_in_chat:
                task = self.handle_image_generation(game_state, context, quest, response_block.text)
                    
            
            user_prompt = await_ask(
                f"What do you say next?",
                context,
                key_suffix=
                f"user input {quest.name}"

            )
        
        blocks = []        
        return FinishAction(output=blocks)


#       *** END RUN FUNCTION ***    

    
    def tags(self, part: QuestTag, quest: "Quest") -> List[Tag]:  # noqa: F821
        return [
            Tag(kind=TagKindExtensions.QUEST, name=part),
            QuestIdTag(quest.name)
        ]

    def respond_to_user(
        self,
        game_state: GameState,
        context: AgentContext,
        quest: Quest,
        user_prompt: str = None,
        additional_context: str = "",
    ):
        prompt = f"{user_prompt}"
        solution_block = send_story_generation(
            prompt=prompt,            
            quest_name=quest.name,
            context=context,
            additional_context=additional_context, 
        )
        return await_streamed_block(solution_block, context)

    def generate_image_description(self, game_state: GameState, context: AgentContext,
    quest: Quest,user_prompt:str):
        user_prompt_processed = user_prompt.replace("\n", " ")
        prompt = textwrap.dedent(
        f"""\
        <Instruction>
        Switch to function mode.
        Given the context of conversion and last message: {user_prompt_processed}
        
        Imagine fitting image description keywords for an imaginary image of {game_state.player.name}, 
        Give your response in the following json format:
        {{
        "ImageDescriptionKeywords": [
            insert image description keywords here as plist
        ]
        }}
        Return just the json, no other text is necessary.\
        """)

        is_solution_attempt_response = generate_image_description(
    prompt=prompt,
    quest_name=quest.name,
    context=context,
    )
        #logging.warning(f"Image description response:\n{is_solution_attempt_response.text}")
        return is_solution_attempt_response.text.strip()

    def generate_plan(self, game_state: GameState, context: AgentContext,
    quest: Quest,user_prompt:str):
        user_prompt_processed = user_prompt.replace("\n", " ")
        prompt = textwrap.dedent(
        f"""\
        <Instruction>
        Pause embodying character and revert to assistant mode.
        Review the message from {game_state.player.name}: "{user_prompt_processed}".
        
        Determine if the message contains any suggestion, gesture,action, intent,indication, or implication—directly or indirectly—that an image/selfie/picture is:
        - being described,
        - being sent,
        - about to be sent,
        - going to be taken,
        - or intended to be shown.
        
        Provide your response in the following format:
        <result>True/False</result>
        <confidence>0.00-1.00</confidence>
        <reasoning>reasoning here</reasoning>\
        """)

        is_solution_attempt_response = generate_is_solution_attempt(
    prompt=prompt,
    quest_name=quest.name,
    context=context,
    )
        #logging.warning(f"Plan response:\n{is_solution_attempt_response.text}")
        return is_solution_attempt_response.text.strip()

    def handle_image_generation(self, game_state: GameState, context: AgentContext, quest: Quest, response_text: str):
        server_settings = get_server_settings(context)

        if not server_settings.enable_images_in_chat:
            return None
        response_plan = self.generate_plan(game_state, context, quest, user_prompt=response_text)

        if "true" not in response_plan.lower():
            return None
        image_description = self.generate_image_description(game_state, context, quest, user_prompt=response_text)

        try:
            image_description_data = json.loads(image_description)
            if "ImageDescriptionKeywords" in image_description_data:
                image_description = " ,".join(image_description_data["ImageDescriptionKeywords"])
        except json.JSONDecodeError:
            logging.error("Failed to parse image description JSON.")
            return None
        image_gen = get_chat_image_generator(context)
        if image_gen:
            task = image_gen.request_chat_image_generation(description=image_description, context=context)
            return task
        return None 
    

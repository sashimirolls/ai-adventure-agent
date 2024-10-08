import json
import logging
import time
from typing import Final, List, Optional

from steamship import PluginInstance, SteamshipError, Tag, Task
from steamship.agents.schema import AgentContext
from steamship.data import TagValueKey

from generators.image_generator import ImageGenerator
from schema.image_theme import CustomStableDiffusionTheme, StableDiffusionTheme
from schema.objects import Item
from utils.context_utils import get_game_state, get_server_settings, get_theme
from utils.tags import (
    CampTag,
    CharacterTag,
    ItemTag,
    QuestIdTag,
    SceneTag,
    StoryContextTag,
    TagKindExtensions,
)
from utils.context_utils import _FALAI_API_KEY
from utils.generation_utils import print_log

class CustomStableDiffusionWithLorasImageGenerator(ImageGenerator):
    PLUGIN_HANDLE: Final[str] = "fal-ai-image-generator"
    generator_plugin_config: dict = {
        "api_key":
        "added_from_context"
    } 
    version: str = "1.0.5"
    plugin_instance: Optional[PluginInstance] = None

    def get_theme(self, theme_name: str, context) -> CustomStableDiffusionTheme:
        #server_settings = get_server_settings(context)
        theme = get_theme(theme_name, context)
        if theme.is_dalle:
            raise SteamshipError(
                f"Theme {theme_name} is DALL-E but this is the SD Generator"
            )
        d = theme.dict()
        return CustomStableDiffusionTheme.parse_obj(d)

    def _get_plugin_instance(self, context: AgentContext):
        self.generator_plugin_config["api_key"] = context.metadata[_FALAI_API_KEY]
        
        if self.plugin_instance is None:
            self.plugin_instance = context.client.use_plugin(
                plugin_handle=CustomStableDiffusionWithLorasImageGenerator.PLUGIN_HANDLE,
                config=self.generator_plugin_config,
                version=self.version,
            )
        return self.plugin_instance

    def generate(
        self,
        context,
        theme_name: str,
        prompt: str,
        negative_prompt: str,
        template_vars: dict,
        image_size: str,
        tags: List[Tag],
    ) -> Task:
        sd = self._get_plugin_instance(context)

        theme = self.get_theme(theme_name, context)
        prompt = theme.make_prompt(prompt, template_vars)
        negative_prompt = theme.make_negative_prompt(negative_prompt, template_vars)

        lora_list = list(map(lambda lora: {"path": lora}, theme.loras))
        lora_json_str = json.dumps(lora_list)
        try:
            image_size = json.loads(image_size)
        except json.JSONDecodeError:
            pass
        options = {
            #"seed": theme.seed,
            "model_name": theme.model,
            "loras": json.loads(lora_json_str),
            "image_size": image_size,
            "num_inference_steps": theme.num_inference_steps,
            "guidance_scale": theme.guidance_scale,
            "clip_skip": theme.clip_skip,
            "scheduler": theme.scheduler,
            "model_architecture": theme.model_architecture,
            "negative_prompt": negative_prompt,
            "enable_safety_checker": False
        }

        start = time.perf_counter()
        #logging.warning("Image theme: " + str(theme))
        #print_log(f"Generating image for Custom Fal Theme {theme.name}: "+str(prompt)+"\nNegative prompt: "+str(negative_prompt))
        task = sd.generate(
            text=prompt.strip(),
            tags=tags,
            streaming=True,
            append_output_to_file=True,
            output_file_id=context.chat_history.file.id,
            make_output_public=True,
            options=options,
        )
        logging.debug(f"Innermost generate start task: {time.perf_counter()-start}")
        task.wait(retry_delay_s=0.1)
        logging.debug(f"Innermost generate after wait: {time.perf_counter() - start}")
        return task

    def request_item_image_generation(self, item: Item, context: AgentContext) -> Task:
        game_state = get_game_state(context)
        server_settings = get_server_settings(context)
        tags = [
            Tag(kind=TagKindExtensions.ITEM, name=ItemTag.IMAGE),
            Tag(
                kind=TagKindExtensions.ITEM,
                name=ItemTag.NAME,
                value={TagValueKey.STRING_VALUE: item.name},
            ),
        ]
        if quest_id := game_state.current_quest:
            tags.append(QuestIdTag(quest_id))

        task = self.generate(
            context=context,
            theme_name=server_settings.item_image_theme,
            prompt=server_settings.item_image_prompt,
            negative_prompt=server_settings.item_image_negative_prompt,
            template_vars={
                "tone": server_settings.narrative_tone,
                "name": item.name,
                "genre": server_settings.narrative_voice,
                "description": item.description,
                "visual_description": item.visual_description,
            },
            image_size="square_hd",
            tags=tags,
        )
        return task

    def request_profile_image_generation(self, context: AgentContext) -> Task:
        game_state = get_game_state(context)
        server_settings = get_server_settings(context)

        name = game_state.player.name
        description = game_state.player.description

        tags = [
            Tag(kind=TagKindExtensions.CHARACTER, name=CharacterTag.IMAGE),
            Tag(
                kind=TagKindExtensions.CHARACTER,
                name=CharacterTag.NAME,
                value={TagValueKey.STRING_VALUE: name},
            ),
        ]
        if quest_id := game_state.current_quest:
            tags.append(QuestIdTag(quest_id))

        task = self.generate(
            context=context,
            theme_name=server_settings.profile_image_theme,
            prompt=server_settings.profile_image_prompt,
            negative_prompt=server_settings.profile_image_negative_prompt,
            template_vars={
                "name": name,
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
                "description": description,
            },
            image_size="portrait_4_3",
            tags=tags,
        )
        return task

    def request_character_image_generation(
        self, name: str, description: str, context: AgentContext
    ) -> Task:
        server_settings = get_server_settings(context)
        task = self.generate(
            context=context,
            theme_name=server_settings.profile_image_theme,
            prompt=server_settings.profile_image_prompt,
            negative_prompt=server_settings.profile_image_negative_prompt,
            template_vars={
                "name": name,
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
                "description": description,
            },
            image_size="portrait_4_3",
            tags=[],  # no tags, as this shouldn't be used in chathistory for anything else (at the moment)
        )
        return task

    def request_scene_image_generation(
        self, description: str, context: AgentContext
    ) -> Task:
        game_state = get_game_state(context)
        server_settings = get_server_settings(context)

        tags = [
            Tag(kind=TagKindExtensions.SCENE, name=SceneTag.BACKGROUND),
        ]
        if quest_id := game_state.current_quest:
            tags.append(QuestIdTag(quest_id))

        task = self.generate(
            context=context,
            theme_name=server_settings.quest_background_theme,
            prompt=server_settings.quest_background_image_prompt,
            negative_prompt=server_settings.quest_background_image_negative_prompt,
            template_vars={
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
                "description": description,
            },
            image_size="landscape_16_9",
            tags=tags,
        )
        return task

    def request_camp_image_generation(self, context: AgentContext) -> Task:
        server_settings = get_server_settings(context)

        tags = [
            Tag(kind=TagKindExtensions.STORY_CONTEXT, name=StoryContextTag.CAMP),
            Tag(kind=TagKindExtensions.CAMP, name=CampTag.IMAGE),
        ]
        task = self.generate(
            context=context,
            theme_name=server_settings.camp_image_theme,
            prompt=server_settings.camp_image_prompt,
            negative_prompt=server_settings.camp_image_negative_prompt,
            template_vars={
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
            },
            image_size="landscape_16_9",
            tags=tags,
        )
        return task

    def request_adventure_image_generation(self, context: AgentContext) -> Task:
        server_settings = get_server_settings(context)

        tags = []

        task = self.generate(
            context=context,
            theme_name=server_settings.adventure_image_theme,
            prompt="Cinematic, 8k, movie advertising image, {narrative_voice}, Movie Title: {name}",
            negative_prompt="",
            template_vars={
                "narrative_voice": server_settings.narrative_voice,
                "name": server_settings.name,
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
            },
            image_size="landscape_16_9",
            tags=tags,
        )
        return task

    def request_chat_image_generation(self, description: str,context: AgentContext) -> Task:
        game_state = get_game_state(context)
        server_settings = get_server_settings(context)

        tags = [
            Tag(kind=TagKindExtensions.SCENE, name=SceneTag.BACKGROUND),
        ]
        if quest_id := game_state.current_quest:
            tags.append(QuestIdTag(quest_id))
        
        appearance = ""
        if game_state.player.appearance and game_state.player.appearance != "":
            appearance = f"{game_state.player.appearance}"
            
        task = self.generate(
            context=context,
            theme_name=server_settings.adventure_image_theme,
            prompt=server_settings.chat_image_prompt,
            negative_prompt="",
            template_vars={
                "tone": server_settings.narrative_tone,
                "genre": server_settings.narrative_voice,
                "description": description,
                "appearance" : appearance,

            },
            image_size="portrait_4_3", #'{\"height\": 1152,\"width\":896 }'
            tags=tags,
        )
        return task
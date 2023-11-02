import json
from typing import Dict, Final, Optional, List

from pydantic.fields import PrivateAttr
from steamship import Tag, Task
from steamship.agents.schema import AgentContext
from steamship.data import TagValueKey

from generators.image_generator import ImageGenerator
from schema.objects import Item
from utils.context_utils import get_game_state, get_server_settings
from utils.tags import (
    CampTag,
    CharacterTag,
    ItemTag,
    QuestIdTag,
    SceneTag,
    StoryContextTag,
    TagKindExtensions,
)


class StableDiffusionWithLorasImageGenerator(ImageGenerator):

    PLUGIN_HANDLE: Final[str] = "fal-sd-lora-image-generator"

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
        # TODO(doug): cache plugin instance by client workspace
        sd = context.client.use_plugin(
            StableDiffusionWithLorasImageGenerator.PLUGIN_HANDLE
        )

        theme = self.get_theme(theme_name, context)
        prompt = theme.make_prompt(prompt, template_vars)
        negative_prompt = theme.make_negative_prompt(negative_prompt, template_vars)

        lora_list = list(map(lambda lora: {"path": lora}, theme.loras))
        lora_json_str = json.dumps(lora_list)

        options = {
            "seed": theme.seed,
            "model_name": theme.model,
            "loras": lora_json_str,
            "image_size": image_size,
            "num_inference_steps": theme.num_inference_steps,
            "guidance_scale": theme.guidance_scale,
            "clip_skip": theme.clip_skip,
            "scheduler": theme.scheduler,
            "model_architecture": theme.model_architecture,
            "negative_prompt": negative_prompt,
        }

        return sd.generate(
            text=prompt,
            tags=tags,
            streaming=True,
            append_output_to_file=True,
            output_file_id=context.chat_history.file.id,
            make_output_public=True,
            options=options,
        )

    DEFAULT_LORA: Final[str] = "https://civitai.com/api/download/models/123593"
    KNOWN_LORAS_AND_TRIGGERS: Final[Dict[str, str]] = {
        # Pixel Art XL (https://civitai.com/models/120096/pixel-art-xl) by https://civitai.com/user/NeriJS
        "https://civitai.com/api/download/models/135931": "(pixel art)",
        # Pixel Art SDXL RW (https://civitai.com/models/114334/pixel-art-sdxl-rw) by https://civitai.com/user/leonnn1
        "https://civitai.com/api/download/models/123593": "((pixelart))",
    }

    _lora: str = PrivateAttr(default=DEFAULT_LORA)

    def __init__(self, lora: Optional[str] = DEFAULT_LORA):
        super().__init__()
        self._lora = lora



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
                "genre": game_state.genre or "Adventure",
                "tone": game_state.tone or "Triumphant",
                "name": item.name or "A random object",
                "description": item.description or "Of usual character",
            },
            image_size="square_hd",
            tags=tags,
        )

        task.wait()
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
                "name": name or "Hero",
                "description": description or "A superhero that will save the day.",
            },
            image_size="portrait_4_3",
            tags=tags,
        )

        task.wait()
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
                "genre": game_state.genre or "Adventure",
                "tone": game_state.tone or "Triumphant",
                "description": description or "An interesting place far away.",
            },
            image_size="landscape_16_9",
            tags=tags,
        )

        task.wait()
        return task

    def request_camp_image_generation(self, context: AgentContext) -> Task:
        game_state = get_game_state(context)
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
                "genre": game_state.genre or "Adventure",
                "tone": game_state.tone or "Triumphant",
            },
            image_size="landscape_16_9",
            tags=tags,
        )
        task.wait()
        return task

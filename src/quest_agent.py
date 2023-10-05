from steamship import Block, MimeTypes
from steamship.agents.schema import Action, Agent, AgentContext
from steamship.agents.schema.action import FinishAction

from schema import UserSettings
from script import Script


class QuestAgent(Agent):
    """
    DESIGN GOALS:
    This implements the "going on a quest" and only that.
    It can be slotted into as a state machine sub-agent by the overall agent.
    """

    PROMPT = ""

    user_settings: UserSettings

    def record_action_run(self, action: Action, context: AgentContext):
        pass

    def next_action(self, context: AgentContext) -> Action:
        try:
            script = Script(context.chat_history)

            script.generate_story(
                f"Explain to {self.user_settings.name} that we're going on a quest to {self.user_settings.motivation} and will generate some music and pictures.",
                context,
            )

            # TODO: How can these be emitted in a way that is both streaming friendly and sync-agent friendly?
            script.generate_background_music("Soft guitar music playing", context)

            script.generate_background_image("A picture of a forest", context)

            story_part_1 = script.generate_story(
                f"{self.user_settings.name} it about to go on a mission. Describe the first few things they do in a few sentences",
                context,
            )

            script.generate_narration(story_part_1, context)

            story_part_2 = script.generate_story(
                f"How does this mission end? {self.user_settings.name} should not yet achieve their overall goal of {self.user_settings.motivation}",
                context,
            )

            script.generate_narration(story_part_2, context)

            # CONCLUDE STORY
            """
            TODO
            Block is of type END SCENE and contains JSON with the summary.

            - how much gold
            - what items
            - summary of the journey

            Every Quest is a different chat history.
            - There would be a quest log button somewhere.
            - In that quest log.
            """

            final_block = Block(text="The quest is over.", mime_type=MimeTypes.MKD)
            return FinishAction(output=[final_block])
        except BaseException as e:
            print(e)

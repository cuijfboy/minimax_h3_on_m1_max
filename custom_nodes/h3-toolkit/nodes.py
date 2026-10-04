"""H3 Toolkit: MiniMax H3 多镜头分镜的辅助节点。

  · H3StructuredPrompt —— 场景/动作/镜头/风格/音效 五字段拼成一段提示词
  · H3LastFrame        —— 从视频取最后一帧，用于镜头之间的末帧接力

后者把 GetVideoComponents + ImageFromBatch 两个节点压成一个。
"""

from comfy_api.latest import ComfyExtension, io


class H3StructuredPrompt(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3StructuredPrompt",
            display_name="H3 Structured Prompt",
            category="H3 Toolkit",
            description=(
                "把场景 / 动作 / 镜头 / 风格 / 音效 五个字段拼成一段完整提示词。\n"
                "留空的字段会被跳过；音效单独成段，便于模型区分画面与声音。"
            ),
            inputs=[
                io.String.Input("scene", display_name="场景", multiline=True, default="",
                                tooltip="画面里有什么：主体、环境、时间、天气"),
                io.String.Input("action", display_name="动作", multiline=True, default="",
                                tooltip="发生什么：主体的动作与变化"),
                io.String.Input("camera", display_name="镜头", multiline=True, default="",
                                tooltip="怎么拍：景别、机位、运动"),
                io.String.Input("style", display_name="风格", multiline=True, default="",
                                tooltip="什么质感：光线、色调、影像风格"),
                io.String.Input("sound", display_name="音效", multiline=True, default="",
                                tooltip="听到什么：对白、音效、环境音。H3 会连同画面一起生成音频"),
                io.String.Input("extra", display_name="补充", multiline=True, default="",
                                optional=True, tooltip="额外要求，追加在最后"),
            ],
            outputs=[io.String.Output(display_name="prompt")],
        )

    @classmethod
    def execute(cls, scene="", action="", camera="", style="", sound="", extra="") -> io.NodeOutput:
        parts = []
        for label, value in (("Scene", scene), ("Action", action),
                             ("Camera", camera), ("Style", style)):
            value = value.strip()
            if value:
                parts.append(f"{label}: {value}")
        prompt = ". ".join(parts)
        if prompt and not prompt.endswith("."):
            prompt += "."

        sound = sound.strip()
        if sound:
            prompt += f"\n\nOverall soundscape: {sound}"
        extra = extra.strip()
        if extra:
            prompt += f"\n\n{extra}"

        return io.NodeOutput(prompt)


class H3LastFrame(io.ComfyNode):
    @classmethod
    def define_schema(cls):
        return io.Schema(
            node_id="H3LastFrame",
            display_name="H3 Get Last Frame",
            category="H3 Toolkit",
            description=(
                "取视频的最后一帧，作为多镜头接力的首帧。\n"
                "接到下一个镜头的 first_frame 上，两个镜头就会严丝合缝地接起来。"
            ),
            inputs=[io.Video.Input("video", tooltip="要取帧的视频")],
            outputs=[io.Image.Output(display_name="image")],
        )

    @classmethod
    def execute(cls, video) -> io.NodeOutput:
        images = video.get_components().images
        return io.NodeOutput(images[-1:])


class H3ToolkitExtension(ComfyExtension):
    async def get_node_list(self):
        return [H3StructuredPrompt, H3LastFrame]


async def comfy_entrypoint() -> H3ToolkitExtension:
    return H3ToolkitExtension()

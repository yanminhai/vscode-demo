from typing import Union
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionContentPartParam

from custom_types import InputMode
from image_generation.core import create_alt_url_mapping
from prompts.imported_code_prompts import IMPORTED_CODE_SYSTEM_PROMPTS
from prompts.screenshot_system_prompts import SYSTEM_PROMPTS
from prompts.types import Stack
from video.utils import assemble_claude_prompt_video


USER_PROMPT = """
Generate code for a web page that looks exactly like this.
"""

SVG_USER_PROMPT = """
Generate code for a SVG that looks exactly like this.
"""

TEXT_USER_PROMPT = """
Generate code for a web page based on the following description.
"""


async def create_prompt(
    params: dict[str, str], stack: Stack, input_mode: InputMode
) -> tuple[list[ChatCompletionMessageParam], dict[str, str]]:

    image_cache: dict[str, str] = {}

    # If this generation started off with imported code, we need to assemble the prompt differently
    if params.get("isImportedFromCode"):
        original_imported_code = params["history"][0]
        prompt_messages = assemble_imported_code_prompt(original_imported_code, stack)
        for index, text in enumerate(params["history"][1:]):
            if index % 2 == 0:
                message: ChatCompletionMessageParam = {
                    "role": "user",
                    "content": text,
                }
            else:
                message: ChatCompletionMessageParam = {
                    "role": "assistant",
                    "content": text,
                }
            prompt_messages.append(message)
    else:
        # 检查是否有图像输入
        if "image" in params and params["image"]:
            # print("prompt使用",stack)
            # 如果有结果图像，使用它
            if params.get("resultImage"):
                prompt_messages = assemble_prompt(
                    params["image"], stack, params["resultImage"]
                )
            else:
                prompt_messages = assemble_prompt(params["image"], stack)
        # 检查是否有文本输入
        elif "text" in params and params["text"]:
            prompt_messages = assemble_text_prompt(params["text"], stack)
        else:
            # 如果没有图像或文本输入，返回错误
            raise ValueError("No image or text input provided")

    if input_mode == "video":
        video_data_url = params["image"]
        prompt_messages = await assemble_claude_prompt_video(video_data_url)

    return prompt_messages, image_cache


def assemble_imported_code_prompt(
    code: str, stack: Stack
) -> list[ChatCompletionMessageParam]:
    system_content = IMPORTED_CODE_SYSTEM_PROMPTS[stack]
    return [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": code,
        },
    ]


def assemble_prompt(
    image_data_url: str,
    stack: Stack,
    result_image_data_url: Union[str, None] = None,
) -> list[ChatCompletionMessageParam]:
    system_content = SYSTEM_PROMPTS[stack]
    user_prompt = USER_PROMPT if stack != "svg" else SVG_USER_PROMPT

    user_content: list[ChatCompletionContentPartParam] = [
        {
            "type": "image_url",
            "image_url": {"url": image_data_url, "detail": "high"},
        },
        {
            "type": "text",
            "text": user_prompt,
        },
    ]

    # Include the result image if it exists
    if result_image_data_url:
        user_content.insert(
            1,
            {
                "type": "image_url",
                "image_url": {"url": result_image_data_url, "detail": "high"},
            },
        )
    return [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": user_content,
        },
    ]


def assemble_text_prompt(
    text: str,
    stack: Stack,
) -> list[ChatCompletionMessageParam]:
    system_content = SYSTEM_PROMPTS[stack]
    user_prompt = TEXT_USER_PROMPT

    return [
        {
            "role": "system",
            "content": system_content,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"{user_prompt}\n\n{text}",
                },
            ],
        },
    ]

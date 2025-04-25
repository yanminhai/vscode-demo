import asyncio
import json
from dataclasses import dataclass
import traceback
from fastapi import APIRouter, WebSocket, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import List, Dict, Any, Optional, AsyncGenerator
import openai
import re
from codegen.utils import extract_html_content
from config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    GEMINI_API_KEY,
    IS_PROD,
    NUM_VARIANTS,
    OPENAI_API_KEY,
    OPENAI_BASE_URL,
    REPLICATE_API_KEY,
    SHOULD_MOCK_AI_RESPONSE,
    # 新增
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    QWEN_API_KEY,
    QWEN_BASE_URL,
    # 新增：InternVL
    INTERN_VL_API_KEY,
    INTERN_VL_BASE_URL,
)
from custom_types import InputMode
from llm import (
    Completion,
    Llm,
    stream_claude_response,
    stream_claude_response_native,
    stream_gemini_response,
    stream_openai_response,
)
from fs_logging.core import write_logs
from mock_llm import mock_completion
from typing import Any, Callable, Coroutine, Dict, List, Literal, cast, get_args
from image_generation.core import generate_images
from prompts import create_prompt
from prompts.claude_prompts import VIDEO_PROMPT
from prompts.types import Stack
from openai.types.chat import ChatCompletionMessageParam, ChatCompletionContentPartParam

# from utils import pprint_prompt
from ws.constants import APP_ERROR_WEB_SOCKET_CODE  # type: ignore
import datetime
from uuid import uuid4
from pathlib import Path
import html
import asyncio
import re
from fastapi import Request

router = APIRouter()


# 新增：定义Vercel AI SDK请求模型
class Attachment(BaseModel):
    id: str
    name: str
    type: str
    localUrl: str
    contentType: str
    url: str  # This seems to hold the base64 data URL from the frontend


class Message(BaseModel):
    role: str
    content: str
    experimental_attachments: Optional[List[Attachment]] = None
    # 'parts' is not explicitly used in the frontend's append call structure shown,
    # but keeping it optional for potential future use or variations.
    parts: Optional[List[Dict[str, Any]]] = None  # Allow more flexible parts if needed


class OtherConfig(BaseModel):
    # Making fields optional as their presence might vary
    isBackEnd: Optional[bool] = None
    backendLanguage: Optional[str] = None
    extra: Optional[Dict[str, Any]] = None


class GenerateCodeRequest(BaseModel):
    # id is not explicitly sent by useChat hook body, but might be added by the hook itself or wrapper. Keep optional.
    id: Optional[str] = None
    messages: List[Message]
    model: str
    mode: str
    otherConfig: Optional[OtherConfig] = None  # Make optional as it might not always be sent
    # Add tools if needed based on frontend logic
    tools: Optional[List[Dict[str, Any]]] = None


class GenerateCodeResponse(BaseModel):
    # The frontend's onFinish expects a Message object structure,
    # but let's return a simple content string for now, matching the original intent.
    # A full streaming implementation would be different.
    # id: str # Let's remove id, as useChat likely manages message IDs on the client
    content: str
    role: str = "assistant"  # Keep role for consistency if frontend uses it


# 添加记录请求日志的函数
def log_request_to_file(message_type: str, data: Dict[str, Any], log_dir: Path = None, url: str = None, error: str = None):
    """
    将请求参数记录到日志文件中

    Args:
        message_type: 消息类型，例如 'first_message' 或 'edit_message'
        data: 要记录的数据
        log_dir: 日志目录，如果为None则使用默认目录
        url: 请求的URL地址
        error: 错误信息（如果有）
    """
    if log_dir is None:
        log_dir = Path(__file__).resolve().parent.parent / "request_logs"

    log_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    log_file = log_dir / f"{message_type}_{timestamp}.json"

    # 添加时间戳到数据中
    log_data = {
        "timestamp": datetime.datetime.now().isoformat(),
        "message_type": message_type,
        "data": data
    }
    
    # 添加URL地址（如果提供）
    if url:
        log_data["url"] = url
    
    # 添加错误信息（如果有）
    if error:
        log_data["error"] = error
    
    # 写入JSON文件
    with open(log_file, "w", encoding="utf-8") as f:
        json.dump(log_data, f, ensure_ascii=False, indent=2)

    print(f"请求日志已保存到: {log_file}")


# Generate images, if needed
async def perform_image_generation(
        completion: str,
        should_generate_images: bool,
        openai_api_key: str | None,
        openai_base_url: str | None,
        image_cache: dict[str, str],
        # 新增deepseek

):
    replicate_api_key = REPLICATE_API_KEY
    if not should_generate_images:
        return completion

    if replicate_api_key:
        image_generation_model = "flux"
        api_key = replicate_api_key
    else:
        if not openai_api_key:
            print(
                "No OpenAI API key and Replicate key found. Skipping image generation."
            )
            return completion
        image_generation_model = "dalle3"
        api_key = openai_api_key

    print("Generating images with model: ", image_generation_model)

    return await generate_images(
        completion,
        api_key=api_key,
        base_url=openai_base_url,
        image_cache=image_cache,
        model=image_generation_model,
    )


@dataclass
class ExtractedParams:
    stack: Stack
    input_mode: InputMode
    should_generate_images: bool
    openai_api_key: str | None
    anthropic_api_key: str | None
    openai_base_url: str | None
    anthropic_base_url: str | None
    generation_type: Literal["create", "update"]
    # 新增deepseek和千问
    deepseek_api_key: str | None
    deepseek_api_url: str | None
    qwen_api_key: str | None
    qwen_api_url: str | None
    # 新增：InternVL
    intern_vl_api_key: str | None
    intern_vl_api_url: str | None


async def extract_params(
        # This function seems designed for WebSocket params. We need a different approach
        # for the POST request or adapt this function significantly.
        # For now, let's extract directly in the POST handler.
        # params: Dict[str, str], throw_error: Callable[[str], Coroutine[Any, Any, None]]
        request_data: GenerateCodeRequest,  # Pass the whole request object
        throw_error: Callable[[str], Coroutine[Any, Any, None]]  # Keep error handling
) -> ExtractedParams:
    # TODO: Refactor this function to take GenerateCodeRequest and extract relevant info
    # For now, we will extract directly in the POST handler and might remove this later.
    # Placeholder implementation:
    print("Warning: extract_params needs refactoring for POST requests.")

    # --- Start Temporary Extraction Logic (Needs proper implementation) ---
    # Determine input mode based on the *last* message's attachments
    last_message = request_data.messages[-1] if request_data.messages else None
    has_image_attachment = False
    if last_message and last_message.experimental_attachments:
        has_image_attachment = any(att.type.startswith("image/") for att in last_message.experimental_attachments)

    validated_input_mode: InputMode = "image" if has_image_attachment else "text"

    # Determine stack - How to get this? Maybe from otherConfig? Defaulting for now.
    validated_stack: Stack = "vue_tailwind"  # Default, needs better source
    if request_data.otherConfig and request_data.otherConfig.extra:
        # Example: Infer stack from frontend framework if available
        frontend_lang = request_data.otherConfig.extra.get("frontendLanguage")
        if frontend_lang == "vue":
            validated_stack = "vue_tailwind"  # Or other Vue stacks
        elif frontend_lang == "react":
            validated_stack = "react_tailwind"  # Or other React stacks
        # Add more logic as needed

    # Image generation flag - Where does this come from in the new request? Defaulting.
    should_generate_images = False  # Default, needs source (maybe otherConfig?)

    # Generation type - Where does this come from? Defaulting.
    generation_type: Literal["create", "update"] = "create"  # Default, needs source

    # API Keys - Should ideally be read from server environment or a secure config,
    # not passed directly in request unless absolutely necessary and secured.
    # Using environment variables as the primary source.
    openai_api_key = OPENAI_API_KEY
    anthropic_api_key = ANTHROPIC_API_KEY
    openai_base_url = OPENAI_BASE_URL  # Assuming OPENAI_BASE_URL is set appropriately
    anthropic_base_url = ANTHROPIC_BASE_URL
    deepseek_api_key = DEEPSEEK_API_KEY
    deepseek_api_url = DEEPSEEK_BASE_URL
    qwen_api_key = QWEN_API_KEY
    qwen_api_url = QWEN_BASE_URL
    # 新增：InternVL
    intern_vl_api_key = INTERN_VL_API_KEY
    intern_vl_api_url = INTERN_VL_BASE_URL
    # --- End Temporary Extraction Logic ---

    return ExtractedParams(
        stack=validated_stack,
        input_mode=validated_input_mode,
        should_generate_images=should_generate_images,
        openai_api_key=openai_api_key,
        anthropic_api_key=anthropic_api_key,
        openai_base_url=openai_base_url,
        anthropic_base_url=anthropic_base_url,
        generation_type=generation_type,
        deepseek_api_key=deepseek_api_key,
        deepseek_api_url=deepseek_api_url,
        qwen_api_key=qwen_api_key,
        qwen_api_url=qwen_api_url,
        # 新增：InternVL
        intern_vl_api_key=intern_vl_api_key,
        intern_vl_api_url=intern_vl_api_url,
    )


# This function is likely unnecessary if keys come only from env vars
# def get_from_settings_dialog_or_env(
#         params: dict[str, str], key: str, env_var: str | None
# ) -> str | None:
#     # ... (implementation)


# Helper function to format stream data according to Vercel AI SDK
def format_vercel_stream_chunk(type_index: int, data: Any) -> str:
    # Ensure data is JSON serializable (especially strings for type 0)
    if type_index == 0 and isinstance(data, str):
        payload = json.dumps(data)
    else:
        payload = json.dumps(data)
    return f"{type_index}:{payload}\n"


async def stream_generator(
        prompt_messages_for_llm: List[Dict[str, Any]],
        selected_llm_enum: Llm,
        api_key_to_use: str | None,
        base_url_to_use: str | None,
        stream_function: Callable[..., Coroutine[Any, Any, Completion]],
        should_generate_images: bool,
        openai_api_key_for_images: str | None,  # Explicitly pass key for images
        openai_base_url_for_images: str | None,  # Explicitly pass base url for images
        image_cache: Dict[str, str],
        input_mode: InputMode,  # Needed for mock completion
        request_url: str | None = None  # 添加请求URL参数
) -> AsyncGenerator[str, None]:
    """
    Asynchronous generator to stream LLM responses and handle post-processing.
    Yields formatted chunks for Vercel AI SDK.
    """
    full_completion_code = ""
    completion_result = None
    queue = asyncio.Queue[str]()
    finished = asyncio.Event()

    async def stream_callback(content: str):
        nonlocal full_completion_code
        full_completion_code += content
        await queue.put(format_vercel_stream_chunk(0, content))  # Yield text chunk

    async def llm_task():
        nonlocal completion_result
        try:
            if SHOULD_MOCK_AI_RESPONSE:
                # Mock completion needs adaptation for streaming yield
                print("Warning: Mock completion streaming not fully implemented, returning full mock.")
                mock_result = await mock_completion(lambda x: None, input_mode=input_mode)
                await queue.put(format_vercel_stream_chunk(0, mock_result["code"]))
                completion_result = mock_result  # Store mock result
            else:
                completion_result = await stream_function(
                    prompt_messages_for_llm,
                    api_key=api_key_to_use,
                    base_url=base_url_to_use,
                    callback=stream_callback,  # Use the callback to yield chunks
                    model=selected_llm_enum
                )
        except Exception as e:
            error_message = f"Error during LLM stream: {e}"
            print(error_message)
            traceback.print_exception(e)
            
            # 记录错误信息
            log_data = {
                "function": "stream_generator.llm_task",
                "model": selected_llm_enum.name if selected_llm_enum else "unknown",
                "exception_type": type(e).__name__,
                "api_key": api_key_to_use,
                "base_url": base_url_to_use
            }
            log_request_to_file("error", log_data, url=request_url, error=str(e))
            
            error_payload = {"error": "LLM generation failed", "details": str(e)}
            await queue.put(format_vercel_stream_chunk(3, error_payload))  # Yield error message
        finally:
            await queue.put(None)  # Signal completion
            finished.set()

    task = asyncio.create_task(llm_task())

    while True:
        chunk = await queue.get()
        if chunk is None:
            break
        yield chunk
        queue.task_done()

    await finished.wait()  # Ensure LLM task is fully finished

    # --- Post-processing after stream completion ---
    if completion_result and not isinstance(completion_result, BaseException):
        try:
            final_code = completion_result.get("code", full_completion_code)  # Use result if available

            # 7. Post-process the completion (HTML extraction)
            html_content = extract_html_content(final_code)

            # 8. Perform image generation if needed
            if should_generate_images:
                html_content = await perform_image_generation(
                    html_content,
                    should_generate_images,
                    openai_api_key_for_images,  # Use the passed key
                    openai_base_url_for_images,  # Use the passed base url
                    image_cache,
                )

            # 9. Log the interaction
            write_logs(prompt_messages_for_llm, html_content)

            # 10. Yield final processed data message
            # final_data = {"type": "final_content", "content": html_content}
            # yield format_vercel_stream_chunk(2, final_data)  # Use index 2 for data messages

        except Exception as e:
            error_message = f"Error during post-processing: {e}"
            print(error_message)
            traceback.print_exception(e)
            
            # 记录错误信息
            log_data = {
                "function": "stream_generator.post_processing",
                "model": selected_llm_enum.name if selected_llm_enum else "unknown",
                "exception_type": type(e).__name__
            }
            log_request_to_file("error", log_data, url=request_url, error=str(e))
            
            error_payload = {"error": "Post-processing failed", "details": str(e)}
            yield format_vercel_stream_chunk(3, error_payload)
    elif isinstance(completion_result, BaseException):
        error_message = f"LLM generation resulted in an exception: {completion_result}"
        print(error_message)
        
        # 记录错误信息
        log_data = {
            "function": "stream_generator",
            "model": selected_llm_enum.name if selected_llm_enum else "unknown",
            "exception_type": type(completion_result).__name__
        }
        log_request_to_file("error", log_data, url=request_url, error=str(completion_result))
        # Error already yielded in llm_task

    task.cancel()  # Clean up task


async def assemble_edit_prompt(previous_code: str, edit_instruction: str, request_url: str = None) -> list[ChatCompletionMessageParam]:
    """
    为修改指令创建提示信息。
    只包含上一次生成的HTML代码和本次输入的指令内容。
    
    Args:
        previous_code: 上一次生成的HTML代码
        edit_instruction: 修改指令
        request_url: 请求的URL地址
    """
    EDIT_PROMPT = """
    你是一位专业的Web开发人员。根据用户的指令，修改下面的HTML代码。
    只返回完整的修改后的HTML代码，不要包含任何其他解释。
    不要使用markdown格式，只返回原始HTML。
    """

    # 记录修改指令的参数
    log_data = {
        "previous_code_length": len(previous_code),
        "previous_code_excerpt": previous_code[:200] + "..." if len(previous_code) > 200 else previous_code,
        "edit_instruction": edit_instruction
    }
    log_request_to_file("edit_message", log_data, url=request_url)
    
    return [
        {
            "role": "system",
            "content": EDIT_PROMPT,
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": f"这是当前的HTML代码:\n\n{previous_code}\n\n请按照以下指令修改代码:\n{edit_instruction}"
                }
            ]
        }
    ]


@router.post("/api/chat")
async def generate_code_post(request: Request, body: GenerateCodeRequest):
    """
    处理Vercel AI SDK (ai/react) 发送的POST请求，生成代码 (Streaming).
    """
    try:
        # 1. Extract data from the request object (same as before)
        messages = body.messages
        model_name = body.model
        # mode = request.mode
        # other_config = request.otherConfig
        
        # 获取请求URL
        request_url = str(request.url)

        if not messages:
            raise ValueError("Received empty messages list.")

        # Extract text and image from the *last* user message (same as before)
        last_message = messages[-1]
        text_content = last_message.content
        image_base64_url = None
        input_mode: InputMode = "text"

        if last_message.experimental_attachments:
            for attachment in last_message.experimental_attachments:
                if attachment.type.startswith("image/"):
                    image_base64_url = attachment.url  # Expecting base64 data URL
                    input_mode = "image"
                    break

        # 判断是否是首次对话
        is_first_conversation = len(messages) <= 1  # 只有当前用户消息，没有之前的AI回复

        # 2. Prepare parameters (same as before, determine stack, etc.)
        stack: Stack = "vue_tailwind"  # Default
        generation_type: Literal["create", "update"] = "create"  # Default
        should_generate_images = False  # Default - TODO: Determine this reliably

        if body.otherConfig and body.otherConfig.extra:
            frontend_lang = body.otherConfig.extra.get("frontendLanguage")
            # print("获取到的参数", frontend_lang)
            if frontend_lang == "vue":
                stack = "vue_tailwind"
            elif frontend_lang == "react":
                stack = "react_tailwind"
            elif frontend_lang == "mobile":
                stack = "vue_vant_tailwind"
            elif frontend_lang == "pc":
                stack = "vue_element_tailwind"

        prompt_params = {"image": image_base64_url, "text": text_content}

        # Get API keys (same as before)
        openai_api_key = OPENAI_API_KEY
        openai_base_url = OPENAI_BASE_URL
        deepseek_api_key = DEEPSEEK_API_KEY
        deepseek_api_url = DEEPSEEK_BASE_URL
        qwen_api_key = QWEN_API_KEY
        qwen_api_url = QWEN_BASE_URL
        anthropic_api_key = ANTHROPIC_API_KEY
        anthropic_base_url = ANTHROPIC_BASE_URL
        # 新增：InternVL
        intern_vl_api_key = INTERN_VL_API_KEY
        intern_vl_api_url = INTERN_VL_BASE_URL

        # 3. Create prompt messages
        image_cache = {}

        if is_first_conversation:
            # 首次对话，记录请求参数
            log_data = {
                "is_first_conversation": True,
                "input_mode": input_mode,
                "text_content": text_content,
                "has_image": image_base64_url is not None,
                "image_url_length": len(image_base64_url) if image_base64_url else 0,
                "stack": stack,
                "model": model_name,
            }
            log_request_to_file("first_message", log_data, url=request_url)
            
            # 首次对话，使用正常的提示创建方式
            prompt_messages_for_llm, image_cache = await create_prompt(prompt_params, stack, input_mode)
        else:
            # 非首次对话，这是一个修改指令
            # 获取上一次AI回复（最后一条助手消息）的内容作为上一次生成的HTML代码
            previous_html = ""
            for msg in reversed(messages[:-1]):  # 跳过最后一条用户消息
                if msg.role == "assistant":
                    previous_html = msg.content
                    break

            # 记录修改请求的参数
            log_data = {
                "is_first_conversation": False,
                "input_mode": input_mode,
                "text_content": text_content,
                "has_previous_html": bool(previous_html),
                "previous_html_length": len(previous_html) if previous_html else 0,
                "stack": stack,
                "model": model_name,
                "messages_count": len(messages)
            }
            log_request_to_file("edit_request", log_data, url=request_url)
            
            if not previous_html:
                # 如果找不到上一次的HTML代码，使用正常的提示创建方式
                prompt_messages_for_llm, image_cache = await create_prompt(prompt_params, stack, input_mode)
            else:
                # 使用修改提示
                prompt_messages_for_llm = await assemble_edit_prompt(previous_html, text_content, request_url)

        # 4. Select LLM (same as before)
        model_map = {
            "claude-3-5-sonnet-20240620": Llm.CLAUDE_3_5_SONNET_2024_10_22,
            "claude-3-7-sonnet-20250219": Llm.CLAUDE_3_7_SONNET_2025_02_19,
            "claude-3-opus-20240229": Llm.CLAUDE_3_OPUS,
            "gpt-4o-2024-11-20": Llm.GPT_4O_2024_11_20,
            "gpt-4o-mini": Llm.GPT_4O_MINI,
            "deepseek-chat": Llm.DEEPSEEK_V3,
            "DeepSeek-R1": Llm.DEEPSEEK_R1,
            "qwen2.5-vl-72b-instruct": Llm.Qwen2_5_72B_Instruct,
            "gemini-2.0-pro-exp-02-05": Llm.GEMINI_2_0_PRO_EXP,
            # 新增：InternVL
            "InternVL2-8B-MPO": Llm.INTERN_VL2_8B_MPO,
            # 新增：hzb-qwen-72b
            "qwen-72b": Llm.HZB_QWEN_72B,
            # 新增：deepseek-qwen
            "deepseek-qwen": Llm.DEEPSEEK_QWEN,
        }
        selected_llm_enum = model_map.get(model_name)
        if not selected_llm_enum:
            print(f"Warning: Model '{model_name}' not found. Falling back to GPT-4o Mini.")
            selected_llm_enum = Llm.GPT_4O_MINI

        # 5. Determine API key, base URL, and stream function (same as before)
        api_key_to_use = None
        base_url_to_use = None
        stream_function = stream_openai_response  # Default

        model_name = selected_llm_enum.name
        print('model_name', model_name)
        if "Qwen" in model_name:
            model_family = "QWEN"
        elif "DEEPSEEK" in model_name:
            model_family = "DEEPSEEK"
        elif "CLAUDE" in model_name:
            model_family = "CLAUDE"
            api_key_to_use = anthropic_api_key
            # base_url_to_use = anthropic_base_url
            # stream_function = stream_claude_response
            if not api_key_to_use: raise ValueError("Anthropic API key missing.")
        elif "GEMINI" in model_name:
            model_family = "GEMINI"
        elif "O1" in model_name:
            model_family = "O1"
        else:
            # 尝试从模型名中提取，例如 INTERN_VL2_8B_MPO -> INTERN_VL
            parts = model_name.split("_")
            if len(parts) > 1:
                model_family = parts[0].upper()
            else:
                model_family = model_name.split("-")[0].upper() # 备用分割符

        print('model_family', model_family)
        if model_family == "DEEPSEEK":
            # 特例处理：如果是 DEEPSEEK_QWEN 模型，使用 InternVL 的 API 端点
            if selected_llm_enum == Llm.DEEPSEEK_QWEN:
                api_key_to_use = intern_vl_api_key
                base_url_to_use = intern_vl_api_url
                if not api_key_to_use: raise ValueError("InternVL API key for HZB models missing.")
            else:
                # 其他 DeepSeek 模型使用常规 DeepSeek API
                api_key_to_use = deepseek_api_key
                base_url_to_use = deepseek_api_url
                if not api_key_to_use: raise ValueError("Deepseek API key missing.")
        elif model_family == "QWEN" and "HZB_QWEN" in model_name:
            # 使用 InternVL 的 API 端点
            api_key_to_use = intern_vl_api_key
            base_url_to_use = intern_vl_api_url
            if not api_key_to_use: raise ValueError("InternVL API key for HZB models missing.")
        elif model_family == "QWEN":
            api_key_to_use = qwen_api_key
            base_url_to_use = qwen_api_url
            if not api_key_to_use: raise ValueError("Qwen API key missing.")
        elif model_family == "CLAUDE":
            api_key_to_use = anthropic_api_key
            # base_url_to_use = anthropic_base_url
            # stream_function = stream_claude_response
            if not api_key_to_use: raise ValueError("Anthropic API key missing.")
        elif model_family == "GEMINI":
            # TODO: Implement Gemini streaming
            print("Warning: Gemini model selected, streaming not implemented.")
            raise NotImplementedError("Gemini streaming not implemented.")
        # 新增：InternVL
        elif model_family == "INTERN" or model_family == "HZB":
            api_key_to_use = intern_vl_api_key
            base_url_to_use = intern_vl_api_url
            if not api_key_to_use: raise ValueError("InternVL API key missing.")
        else:  # Default OpenAI
            api_key_to_use = openai_api_key
            base_url_to_use = openai_base_url
            if not api_key_to_use: raise ValueError("OpenAI API key missing.")

        # 6. Return StreamingResponse using the generator
        # return StreamingResponse(
        #     stream_generator(
        #         prompt_messages_for_llm=prompt_messages_for_llm,
        #         selected_llm_enum=selected_llm_enum,
        #         api_key_to_use=api_key_to_use,
        #         base_url_to_use=base_url_to_use,
        #         stream_function=stream_function,
        #         should_generate_images=should_generate_images,
        #         openai_api_key_for_images=openai_api_key, # Pass key for potential image gen
        #         openai_base_url_for_images=openai_base_url, # Pass base url for potential image gen
        #         image_cache=image_cache,
        #         input_mode=input_mode # Pass for mock completion
        #     ),
        #     media_type="text/event-stream",
        # )

        async def stream_and_save(generator, output_file_path: Path):
            generated_text = ""

            try:
                async for chunk in generator:
                    # 1. 发送给前端不变
                    yield chunk

                    # 2. 从 chunk 中提取文本内容并写入本地
                    try:
                        if isinstance(chunk, bytes):
                            chunk = chunk.decode("utf-8")

                        # 去除前缀 "data: "
                        if chunk.startswith("data: "):
                            chunk = chunk[len("data: "):]

                        # 去除 SSE 结束标记
                        if chunk.strip() == "[DONE]":
                            continue

                        # 正则提取冒号后的字符串内容（去除前面的 0:，和首尾双引号）
                        match = re.match(r'0:"(.*)"', chunk.strip())
                        if match:
                            content = match.group(1)
                            # 还原转义字符（如 \" -> "）
                            content = bytes(content, "utf-8").decode("unicode_escape")
                            generated_text += content
                    except Exception as e:
                        error_message = f"Chunk 解析失败: {chunk}"
                        print(error_message)
                        
                        # 记录解析错误
                        log_data = {
                            "function": "stream_and_save.chunk_parsing",
                            "chunk_sample": str(chunk)[:200] if chunk else "",
                            "exception_type": type(e).__name__
                        }
                        log_request_to_file("error", log_data, url=request_url, error=str(e))
                        continue

                html_text = extract_html_content(generated_text)
                # 插入脚本
                html_text = re.sub(r'</head>', r'<script src="http://localhost:8010/static/drop.js"></script></head>', html_text)
                # 写入 HTML 页面
                output_file_path.write_text(html_text, encoding="utf-8")
                
            except Exception as e:
                error_message = f"流式传输或保存过程出错: {e}"
                print(error_message)
                traceback.print_exception(e)
                
                # 记录流处理错误
                log_data = {
                    "function": "stream_and_save",
                    "model": model_name,
                    "output_path": str(output_file_path),
                    "exception_type": type(e).__name__
                }
                log_request_to_file("error", log_data, url=request_url, error=str(e))
                
                # 重新抛出异常
                raise

        # 构建保存文件路径
        # timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        # filename = f"generate_code_{timestamp}_{uuid4().hex[:8]}.html"
        filename = f"{model_name}.html"

        output_dir = Path(__file__).resolve().parent.parent / "generated_outputs"
        output_dir.mkdir(parents=True, exist_ok=True)
        output_file_path = output_dir / filename

        # 构建原始 generator
        original_generator = stream_generator(
            prompt_messages_for_llm=prompt_messages_for_llm,
            selected_llm_enum=selected_llm_enum,
            api_key_to_use=api_key_to_use,
            base_url_to_use=base_url_to_use,
            stream_function=stream_function,
            should_generate_images=should_generate_images,
            openai_api_key_for_images=openai_api_key,
            openai_base_url_for_images=openai_base_url,
            image_cache=image_cache,
            input_mode=input_mode,
            request_url=request_url
        )

        # 创建流式响应，包装 generator（边发边保存）
        response = StreamingResponse(
            stream_and_save(original_generator, output_file_path),
            media_type="text/event-stream"
        )

        host = str(request.base_url)
        response.headers["X-File-Path"] = str(host) + f"static/{filename}"
        # response.headers["X-File-Path"] = relative_static_path

        # 获取 output_file_path 的绝对路径
        absolute_path = output_file_path.resolve()
        # 设置响应头为完整路径
        response.headers["X-Physical-Path"] = str(absolute_path)

        return response

    except Exception as e:
        error_message = f"Error setting up stream for /api/chat: {str(e)}"
        print(error_message)
        traceback.print_exception(e)
        
        # 记录错误信息
        log_data = {
            "function": "generate_code_post",
            "model": body.model if hasattr(body, "model") else "unknown",
            "exception_type": type(e).__name__
        }
        log_request_to_file("error", log_data, url=str(request.url) if request else None, error=str(e))
        
        raise


@router.websocket("/generate-code")
async def stream_code(websocket: WebSocket):
    await websocket.accept()
    print("Incoming websocket connection...")

    ## Communication protocol setup
    async def throw_error(
            message: str,
    ):
        print(message)
        await websocket.send_json({"type": "error", "value": message})
        await websocket.close(APP_ERROR_WEB_SOCKET_CODE)

    async def send_message(
            type: Literal["chunk", "status", "setCode", "error"],
            value: str,
            variantIndex: int,
    ):
        # Print for debugging on the backend
        if type == "error":
            print(f"Error (variant {variantIndex}): {value}")
        elif type == "status":
            print(f"Status (variant {variantIndex}): {value}")

        await websocket.send_json(
            {"type": type, "value": value, "variantIndex": variantIndex}
        )

    ## Parameter extract and validation

    # TODO: Are the values always strings?
    # 收到的输入参数，主要是图片的base64，模型信息、apikey以及生成代码的配置如vue+tailwind
    params: dict[str, str] = await websocket.receive_json()
    # print("模型配置参数打印：",params)
    print("Received params")

    # 拿到模型相关配置： anthropic_api_key,base_url,stak=vue_tailwind
    extracted_params = await extract_params(params, throw_error)
    # stak = vue_tailwind
    stack = extracted_params.stack
    # input_mode = 'image'
    input_mode = extracted_params.input_mode
    # openai_api_key = xxx
    # 新增deepseek和通义千问
    deepseek_api_key = extracted_params.deepseek_api_key
    deepseek_api_url = extracted_params.deepseek_api_url
    qwen_api_key = extracted_params.qwen_api_key
    qwen_api_url = extracted_params.qwen_api_url

    openai_api_key = extracted_params.openai_api_key
    openai_base_url = extracted_params.openai_base_url
    anthropic_api_key = extracted_params.anthropic_api_key
    # should_generate_images = true
    should_generate_images = extracted_params.should_generate_images
    # generation_type="create"
    generation_type = extracted_params.generation_type

    print(f"Generating {stack} code in {input_mode} mode")

    for i in range(NUM_VARIANTS):
        await send_message("status", "Generating code...", i)

    ### Prompt creation

    # Image cache for updates so that we don't have to regenerate images
    image_cache: Dict[str, str] = {}

    try:
        prompt_messages, image_cache = await create_prompt(params, stack, input_mode)
    except:
        await throw_error(
            "Error assembling prompt. Contact support at support@picoapps.xyz"
        )
        raise

    # pprint_prompt(prompt_messages)  # type: ignore

    ### Code generation

    async def process_chunk(content: str, variantIndex: int):
        await send_message("chunk", content, variantIndex)

    if SHOULD_MOCK_AI_RESPONSE:
        completion_results = [
            await mock_completion(process_chunk, input_mode=input_mode)
        ]
        completions = [result["code"] for result in completion_results]
    else:
        try:
            if input_mode == "video":
                if not anthropic_api_key:
                    await throw_error(
                        "Video only works with Anthropic models. No Anthropic API key found. Please add the environment variable ANTHROPIC_API_KEY to backend/.env or in the settings dialog"
                    )
                    raise Exception("No Anthropic key")

                completion_results = [
                    await stream_claude_response_native(
                        system_prompt=VIDEO_PROMPT,
                        messages=prompt_messages,  # type: ignore
                        api_key=anthropic_api_key,
                        callback=lambda x: process_chunk(x, 0),
                        model=Llm.CLAUDE_3_OPUS,
                        include_thinking=True,
                    )
                ]
                completions = [result["code"] for result in completion_results]
            else:

                # Depending on the presence and absence of various keys,
                # we decide which models to run
                variant_models = []

                # For creation, use Claude Sonnet 3.7
                # For updates, we use Claude Sonnet 3.5 until we have tested Claude Sonnet 3.7
                if generation_type == "create":
                    claude_model = Llm.CLAUDE_3_7_SONNET_2025_02_19
                else:
                    claude_model = Llm.CLAUDE_3_7_SONNET_2025_02_19

                # 如果存在deepseek Key,调用deepseek
                if deepseek_api_key and deepseek_api_url:
                    variant_models = [
                        Llm.DEEPSEEK_V3,
                        Llm.DEEPSEEK_R1,
                    ]

                # 如果存在千问 Key,调用千问
                elif qwen_api_key and qwen_api_url:
                    variant_models = [
                        Llm.QWEN_VL_MAX,
                        Llm.QWEN_VL_MAX,
                    ]

                elif openai_api_key and anthropic_api_key:
                    variant_models = [
                        Llm.Qwen2_5_72B_Instruct,
                        Llm.CLAUDE_3_7_SONNET_2025_02_19,
                        Llm.CLAUDE_3_5_SONNET_2024_10_22,
                        Llm.GEMINI_2_5_PRO_EXP_2025_03_25
                    ]
                elif openai_api_key:
                    variant_models = [
                        Llm.GPT_4O_2024_11_20,
                        Llm.GPT_4O_2024_11_20,
                    ]
                elif anthropic_api_key:
                    variant_models = [
                        claude_model,
                        Llm.CLAUDE_3_7_SONNET_2025_02_19,
                    ]
                else:
                    await throw_error(
                        "No OpenAI or Anthropic API key found. Please add the environment variable OPENAI_API_KEY or ANTHROPIC_API_KEY to backend/.env or in the settings dialog. If you add it to .env, make sure to restart the backend server."
                    )
                    raise Exception("No OpenAI or Anthropic key")

                # variant_models  模型列表，3.5,3.7
                tasks: List[Coroutine[Any, Any, Completion]] = []
                for index, model in enumerate(variant_models):
                    print("使用模型", model)
                    if model.name.startswith("DEEPSEEK"):
                        if deepseek_api_key is None:
                            await throw_error("DEEPSEEK API key is missing.")
                            raise Exception("DEEPSEEK API key is missing.")
                        tasks.append(
                            stream_openai_response(
                                prompt_messages,
                                api_key=deepseek_api_key,
                                base_url=deepseek_api_url,
                                callback=lambda x, i=index: process_chunk(x, i),
                                model=model,
                            )
                        )
                    elif model.name.startswith("QWEN"):
                        if qwen_api_key is None:
                            await throw_error("QWEN API key is missing.")
                            raise Exception("QWEN API key is missing.")
                        tasks.append(
                            stream_openai_response(
                                prompt_messages,
                                api_key=qwen_api_key,
                                base_url=qwen_api_url,
                                callback=lambda x, i=index: process_chunk(x, i),
                                model=model,
                            )
                        )
                    else:
                        if openai_api_key is None:
                            await throw_error("OpenAI API key is missing.")
                            raise Exception("OpenAI API key is missing.")
                        tasks.append(
                            stream_openai_response(
                                prompt_messages,
                                api_key=openai_api_key,
                                base_url=openai_base_url,
                                callback=lambda x, i=index: process_chunk(x, i),
                                model=model,
                            )
                        )

                # Run the models in parallel and capture exceptions if any
                completions = await asyncio.gather(*tasks, return_exceptions=True)

                # If all generations failed, throw an error
                all_generations_failed = all(
                    isinstance(completion, BaseException) for completion in completions
                )
                if all_generations_failed:
                    await throw_error("Error generating code. Please contact support.")

                    # Print the all the underlying exceptions for debugging
                    for completion in completions:
                        if isinstance(completion, BaseException):
                            traceback.print_exception(completion)
                    raise Exception("All generations failed")

                # If some completions failed, replace them with empty strings
                for index, completion in enumerate(completions):
                    if isinstance(completion, BaseException):
                        completions[index] = Completion(duration=0, code="")
                        print("Generation failed for variant", index)
                        print(completion)
                    else:
                        print(
                            f"{variant_models[index].value} completion took {completion['duration']:.2f} seconds"
                        )

                completions = [
                    result["code"]
                    for result in completions
                    if not isinstance(result, BaseException)
                ]

        except openai.AuthenticationError as e:
            print("[GENERATE_CODE] Authentication failed", e)
            error_message = (
                    "Incorrect OpenAI key. Please make sure your OpenAI API key is correct, or create a new OpenAI API key on your OpenAI dashboard."
                    + (
                        " Alternatively, you can purchase code generation credits directly on this website."
                        if IS_PROD
                        else ""
                    )
            )
            return await throw_error(error_message)
        except openai.NotFoundError as e:
            print("[GENERATE_CODE] Model not found", e)
            error_message = (
                    e.message
                    + ". Please make sure you have followed the instructions correctly to obtain an OpenAI key with GPT vision access: https://github.com/abi/screenshot-to-code/blob/main/Troubleshooting.md"
                    + (
                        " Alternatively, you can purchase code generation credits directly on this website."
                        if IS_PROD
                        else ""
                    )
            )
            return await throw_error(error_message)
        except openai.RateLimitError as e:
            print("[GENERATE_CODE] Rate limit exceeded", e)
            error_message = (
                    "OpenAI error - 'You exceeded your current quota, please check your plan and billing details.'"
                    + (
                        " Alternatively, you can purchase code generation credits directly on this website."
                        if IS_PROD
                        else ""
                    )
            )
            return await throw_error(error_message)

    ## Post-processing

    # Strip the completion of everything except the HTML content
    completions = [extract_html_content(completion) for completion in completions]

    # Write the messages dict into a log so that we can debug later
    write_logs(prompt_messages, completions[0])

    ## Image Generation

    for index, _ in enumerate(completions):
        await send_message("status", "Generating images...", index)

    image_generation_tasks = [
        perform_image_generation(
            completion,
            should_generate_images,
            openai_api_key,
            openai_base_url,
            image_cache,
        )
        for completion in completions
    ]

    updated_completions = await asyncio.gather(*image_generation_tasks)

    for index, updated_html in enumerate(updated_completions):
        await send_message("setCode", updated_html, index)
        await send_message("status", "Code generation complete.", index)

    await websocket.close()

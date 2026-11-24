import abc
import math
import time
import base64
import numpy as np
from PIL import Image
from io import BytesIO
from typing import Any, Optional
from pathlib import Path
from types import SimpleNamespace
import sys

# Reuse the OSWorld-tested transport-only hard deadline. This changes neither
# model messages/actions nor task scoring, and never retries device actions.
_transport_root = str(Path(__file__).resolve().parents[3] / 'osworld_uipath')
if _transport_root not in sys.path:
    sys.path.insert(0, _transport_root)
from bounded_api_transport import BoundedApiTransport
try:
    from qwen_vl_utils import smart_resize
except ModuleNotFoundError:
    def smart_resize(
        height: int,
        width: int,
        factor: int,
        min_pixels: int,
        max_pixels: int,
    ) -> tuple[int, int]:
        """Resize dimensions to factor multiples while respecting pixel limits."""
        resized_height = max(factor, round(height / factor) * factor)
        resized_width = max(factor, round(width / factor) * factor)
        pixels = resized_height * resized_width
        if pixels > max_pixels:
            scale = math.sqrt((height * width) / max_pixels)
            resized_height = max(factor, math.floor(height / scale / factor) * factor)
            resized_width = max(factor, math.floor(width / scale / factor) * factor)
        elif pixels < min_pixels:
            scale = math.sqrt(min_pixels / (height * width))
            resized_height = max(factor, math.ceil(height * scale / factor) * factor)
            resized_width = max(factor, math.ceil(width * scale / factor) * factor)
        return resized_height, resized_width

ERROR_CALLING_LLM = 'Error calling LLM'

def pil_to_base64(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG") 
    return base64.b64encode(buffer.getvalue()).decode("utf-8")

def image_to_base64(image_path):
    dummy_image = Image.open(image_path)
    MIN_PIXELS=3136
    MAX_PIXELS=10035200
    resized_height, resized_width  = smart_resize(dummy_image.height,
        dummy_image.width,
        factor=28,
        min_pixels=MIN_PIXELS,
        max_pixels=MAX_PIXELS,)
    dummy_image = dummy_image.resize((resized_width, resized_height))
    return f"data:image/png;base64,{pil_to_base64(dummy_image)}"

class LlmWrapper(abc.ABC):
    """Abstract interface for (text only) LLM."""
    @abc.abstractmethod
    def predict(
        self,
        text_prompt: str,
    ) -> tuple[str, Optional[bool], Any]:
        """Calling multimodal LLM with a prompt and a list of images.

        Args:
        text_prompt: Text prompt.

        Returns:
        Text output, is_safe, and raw output.
        """

class MultimodalLlmWrapper(abc.ABC):
    """Abstract interface for Multimodal LLM."""
    @abc.abstractmethod
    def predict_mm(
        self, text_prompt: str, images: list[np.ndarray]
    ) -> tuple[str, Optional[bool], Any]:
        """Calling multimodal LLM with a prompt and a list of images.

        Args:
        text_prompt: Text prompt.
        images: List of images as numpy ndarray.

        Returns:
        Text output and raw output.
        """

class GUIOwlWrapper(LlmWrapper, MultimodalLlmWrapper):

    RETRY_WAITING_SECONDS = 20

    def __init__(
            self,
            api_key: str,
            base_url: str,
            model_name: str,
            max_retry: int = 3,
            temperature: float = 0.0,
    ):
        if max_retry <= 0:
            max_retry = 3
            print('Max_retry must be positive. Reset it to 3')
        self.max_retry = min(max_retry, 3)
        self.temperature = temperature
        self.model = model_name
        self.transport = BoundedApiTransport(base_url, api_key, timeout=120)
        self.bot = SimpleNamespace(chat=SimpleNamespace(completions=self.transport))

    def __del__(self):
        transport = getattr(self, 'transport', None)
        if transport is not None:
            try:
                transport.close()
            except (OSError, ValueError):
                pass

    def convert_messages_format_to_openaiurl(self, messages):
      converted_messages = []
      for message in messages:
          new_content = []
          for item in message['content']:
              if list(item.keys())[0] == 'text':
                  new_content.append({'type': 'text', 'text': item['text']})
              elif list(item.keys())[0] == 'image':
                new_content.append({'type': 'image_url', 'image_url': {'url': image_to_base64(item['image'])}})
          converted_messages.append({'role': message['role'], 'content': new_content})

      return converted_messages
    
    def predict(
            self,
            text_prompt: str,
    ) -> tuple[str, Optional[bool], Any]:
        return self.predict_mm(text_prompt, [])

    def predict_mm(
            self, text_prompt: str, images: list[np.ndarray], messages = None
    ) -> tuple[str, Optional[bool], Any]:
        
        if messages is None:
          payload = [
              {
                  "role": "user",
                  "content": [
                      {"text": text_prompt},
                  ]
              }
          ]
          
          for image in images:
            payload[0]['content'].append({
                'image': image
            })
        else:
          payload = messages
            
        payload = self.convert_messages_format_to_openaiurl(payload)

        counter = self.max_retry
        wait_seconds = self.RETRY_WAITING_SECONDS
        while counter > 0:
            try:
              chat_completion_from_url = self.bot.chat.completions.create(model=self.model, messages=payload, **{})
              return (chat_completion_from_url.choices[0].message.content, payload, chat_completion_from_url)
            except Exception as e:
                time.sleep(wait_seconds)
                wait_seconds *= 1
                counter -= 1
                print('Error calling LLM, will retry soon...')
                print(e)
        return ERROR_CALLING_LLM, None, None

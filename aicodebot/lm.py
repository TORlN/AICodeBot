from aicodebot.config import read_config
from aicodebot.helpers import logger
from langchain.chains import LLMChain
from langchain.chat_models import ChatOpenAI
from langchain.memory import ConversationTokenBufferMemory
from openai.api_resources import engine
import functools, openai, os, tiktoken

DEFAULT_RESPONSE_TOKENS = 512
DEFAULT_MEMORY_TOKENS = DEFAULT_RESPONSE_TOKENS * 2
DEFAULT_CONTEXT_TOKENS = DEFAULT_RESPONSE_TOKENS * 4
PRECISE_TEMPERATURE = 0.05
CREATIVE_TEMPERATURE = 0.6
DEFAULT_MODEL = "gpt-4"


class LanguageModelManager:
    """A class for interacting with language models."""

    model = memory = None

    @functools.lru_cache  # cache so we only make the API call once
    @staticmethod
    def openai_supported_engines():
        """Get a list of the models supported by the OpenAI API key."""
        config = read_config()
        openai.api_key = config["openai_api_key"]
        engines = engine.Engine.list()
        out = [engine.id for engine in engines.data]
        logger.trace(f"OpenAI supported engines: {out}")
        return out

    def get_memory(self, llm, token_limit=DEFAULT_MEMORY_TOKENS, memory_key="chat_history", input_key="task"):
        """Initializes a memory object with the specified parameters."""
        if not self.memory:  # Re-use the same memory object
            self.memory = ConversationTokenBufferMemory(
                memory_key=memory_key, input_key=input_key, llm=llm, max_token_limit=token_limit
            )
        return self.memory

    def get_langchain_chain(self, llm, prompt, memory=None):
        """Initializes a langchain chain with the specified parameters."""
        return LLMChain(llm=llm, prompt=prompt, memory=memory)

    def get_langchain_model(
        self,
        model_name,
        response_token_size=None,
        temperature=PRECISE_TEMPERATURE,
        streaming=False,
        callbacks=None,
    ):
        """Initializes a language model for chat with the specified parameters."""
        config = read_config()
        if "openrouter_api_key" in config:
            # If the openrouter_api_key is set, use the Open Router API
            # OpenRouter allows for access to many models that have larger token limits
            api_key = config["openrouter_api_key"]
            api_base = "https://openrouter.ai/api/v1"
            headers = {"HTTP-Referer": "https://aicodebot.dev", "X-Title": "AICodeBot"}

            # In order to get conversation buffer memory to work, we need to set the tiktoken model name
            # For OpenAI models, this is as simple as stripping the prefix "openai/" from the model name
            # For non-OpenAI models, we need to set the model name to "gpt-4" for now
            if model_name.startswith("openai/"):
                tiktoken_model_name = model_name.replace("openai/", "")
            else:
                # HACK: For any other model, default to gpt-4. Seems to work?
                # Tested with anthropic/claude2
                tiktoken_model_name = DEFAULT_MODEL

        else:
            api_key = config["openai_api_key"]
            api_base = None
            headers = None
            tiktoken_model_name = model_name

        self.langchain_model = ChatOpenAI(
            openai_api_key=api_key,
            openai_api_base=api_base,
            model=model_name,
            max_tokens=response_token_size,
            temperature=temperature,
            streaming=streaming,
            callbacks=callbacks,
            tiktoken_model_name=tiktoken_model_name,
            model_kwargs={"headers": headers},
        )
        return self.langchain_model

    @staticmethod
    def get_model_headers():
        """Certain providers require extra headers to be set in order to access their models."""
        config = read_config()
        if "openrouter_api_key" in config:
            return {"HTTP-Referer": "https://aicodebot.dev", "X-Title": "AICodeBot"}
        else:
            return None

    @staticmethod
    def get_model_token_limit(model_name):
        model_token_limits = {
            "openai/gpt-4": 8192,
            "openai/gpt-4-32k": 32768,
            "anthropic/claude-2": 100_000,
            "gpt-4": 8192,
            "gpt-4-32k": 32768,
            "gpt-3.5-turbo": 4096,
            "gpt-3.5-turbo-16k": 16384,
        }
        if model_name in model_token_limits:
            return model_token_limits[model_name]
        else:
            raise ValueError(f"Model {model_name} not found")

    @classmethod
    def choose_model(cls, token_size=0):
        """Gets the name of the model to use for the specified token size."""
        config = read_config()
        if os.getenv("AICODEBOT_LLM_MODEL"):
            logger.info(
                f"Using model {os.getenv('AICODEBOT_LLM_MODEL')} from AICODEBOT_LLM_MODEL environment variable"
            )
            return os.getenv("AICODEBOT_LLM_MODEL")

        if "openrouter_api_key" in config:
            model_options = supported_engines = ["openai/gpt-4", "openai/gpt-4-32k"]
        else:
            model_options = ["gpt-4", "gpt-4-32k", "gpt-3.5-turbo", "gpt-3.5-turbo-16k"]
            # Pull the list of supported engines from the OpenAI API for this key
            supported_engines = cls.openai_supported_engines()

        # For some unknown reason, tiktoken often underestimates the token size by ~5%, so let's buffer
        token_size = int(token_size * 1.05)

        for model_name in model_options:
            max_tokens = cls.get_model_token_limit(model_name)
            if model_name in supported_engines and token_size <= max_tokens:
                logger.info(f"Using {model_name} for token size {token_size}")
                return model_name

        logger.critical(
            f"The context is too large ({token_size}) for any of the models supported by your API key. 😞"
        )
        if "openrouter_api_key" not in config:
            logger.critical(
                "If you provide an Open Router API key, you can access larger models, up to 100k tokens"
            )
        return None

    def get_token_length(text, model=DEFAULT_MODEL):
        """Get the number of tokens in a string using the tiktoken library."""
        encoding = tiktoken.encoding_for_model(model)
        tokens = encoding.encode(text)
        token_length = len(tokens)
        short_text = (text[0:20] + "..." if len(text) > 10 else text).strip()
        logger.trace(f"Token length for {short_text}: {token_length}")
        return token_length


def get_token_size(text, model=DEFAULT_MODEL):
    # shortcut
    return LanguageModelManager.get_token_length(text, model)
import os
from typing import List, Optional
from dotenv import load_dotenv

load_dotenv()  # Load .env file into os.environ


class Config:
    """Centralized configuration from environment variables with singleton pattern."""
    
    _instance: Optional['Config'] = None
    
    def __new__(cls) -> 'Config':
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self) -> None:
        if self._initialized:
            return
        
        # Discord Configuration
        self.DISCORD_TOKEN: str = os.environ.get('DISCORD_TOKEN', '')
        self.DISCORD_CLIENT_ID: str = os.environ.get('DISCORD_CLIENT_ID', '')
        self.DISCORD_CLIENT_SECRET: str = os.environ.get('DISCORD_CLIENT_SECRET', '')
        self.DISCORD_REDIRECT_URI: str = os.environ.get('DISCORD_REDIRECT_URI', '')
        self.ALLOWED_GUILD_IDS: List[int] = self._parse_guild_ids(
            os.environ.get('ALLOWED_GUILD_IDS', '')
        )
        
        # Safety Configuration
        self.GUILD_LOCK_MODE: str = os.environ.get('GUILD_LOCK_MODE', 'open')  # "open" or "whitelist" (set "whitelist" + ALLOWED_GUILD_IDS in production)
        self.RATE_LIMIT_DELAY: float = float(os.environ.get('RATE_LIMIT_DELAY', '0.5'))
        
        # LLM Configuration
        self.LLM_PROVIDER: str = os.environ.get('LLM_PROVIDER', 'gemini')
        self.GEMINI_API_KEY: str = os.environ.get('GEMINI_API_KEY', '')
        self.GEMINI_MODEL: str = os.environ.get('GEMINI_MODEL', 'gemini-2.5-flash')
        
        
        # Ollama Configuration (for local/self-hosted models)
        self.OLLAMA_BASE_URL: str = os.environ.get('OLLAMA_BASE_URL', 'http://localhost:11434')
        self.OLLAMA_MODEL: str = os.environ.get('OLLAMA_MODEL', 'qwen2.5:7b-instruct')
        
        # Server Configuration
        self.PORT: int = int(os.environ.get('PORT', 8000))
        self.SECRET_KEY: str = os.environ.get('SECRET_KEY', '')
        self.DEBUG: bool = os.environ.get('DEBUG', 'False').lower() == 'true'
        self.LOG_LEVEL: str = os.environ.get('LOG_LEVEL', 'INFO')
        
        # CORS Configuration
        allowed_origins_str = os.environ.get('ALLOWED_ORIGINS', '')
        self.ALLOWED_ORIGINS: List[str] = (
            [o.strip() for o in allowed_origins_str.split(',') if o.strip()]
            if allowed_origins_str.strip()
            else []  # Must be explicitly configured via ALLOWED_ORIGINS env var
        )

        # Database Configuration
        self.DATABASE_URL: str = os.environ.get(
            'DATABASE_URL',
            'postgresql://localhost:5432/aurafactory'
        )
        self.DATABASE_BACKEND: str = os.environ.get('DATABASE_BACKEND', 'postgresql')  # "postgresql" or "dynamodb"
        self.DYNAMODB_TABLE_NAME: str = os.environ.get('DYNAMODB_TABLE_NAME', 'aurafactory')
        
        # Input limits
        self.MAX_MESSAGE_LENGTH: int = int(os.environ.get('MAX_MESSAGE_LENGTH', '2000'))
        
        # Token budget
        self.DAILY_TOKEN_BUDGET: int = int(os.environ.get('DAILY_TOKEN_BUDGET', '800000'))
        self.PER_REQUEST_TOKEN_LIMIT: int = int(os.environ.get('PER_REQUEST_TOKEN_LIMIT', '10000'))
        
        # AWS/Bedrock Configuration 
        self.AWS_REGION: str = os.environ.get('AWS_REGION', 'us-east-1')
        self.BEDROCK_MODEL_ID: str = os.environ.get('BEDROCK_MODEL_ID', 'amazon.nova-micro-v1:0')
        
        # Bedrock Guardrails Configuration
        self.BEDROCK_GUARDRAIL_ID: str = os.environ.get('BEDROCK_GUARDRAIL_ID', '')
        self.BEDROCK_GUARDRAIL_VERSION: str = os.environ.get('BEDROCK_GUARDRAIL_VERSION', 'DRAFT')
        
        # AWS Access (optional — prefers IAM role on App Runner/ECS)
        self.AWS_ACCESS_KEY_ID: str = os.environ.get('AWS_ACCESS_KEY_ID', '')
        self.AWS_SECRET_ACCESS_KEY: str = os.environ.get('AWS_SECRET_ACCESS_KEY', '')
        
        self._initialized = True
        self._validate_production()
    
    @staticmethod
    def _parse_guild_ids(guild_ids_str: str) -> List[int]:
        """Parse comma-separated guild IDs from environment variable."""
        if not guild_ids_str.strip():
            return []
        try:
            return [int(gid.strip()) for gid in guild_ids_str.split(',') if gid.strip()]
        except ValueError:
            return []
    
    def _validate_production(self) -> None:
        """Validate required configuration for production deployments."""
        if not self.DEBUG:
            missing = []
            if not self.SECRET_KEY:
                missing.append('SECRET_KEY')
            if not self.DATABASE_URL or self.DATABASE_URL == 'postgresql://localhost:5432/aurafactory':
                missing.append('DATABASE_URL')
            if missing:
                raise RuntimeError(f"Production requires these env vars: {', '.join(missing)}")
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """Get or create the singleton instance."""
        return cls()


# Singleton instance
config = Config.get_instance()
settings = config  # Alias — main.py and services use `from app.config import settings`

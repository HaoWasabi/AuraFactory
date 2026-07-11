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
        
        # LLM Configuration
        self.LLM_PROVIDER: str = os.environ.get('LLM_PROVIDER', 'gemini')
        self.GEMINI_API_KEY: str = os.environ.get('GEMINI_API_KEY', '')
        self.GEMINI_MODEL: str = os.environ.get('GEMINI_MODEL', 'gemini-2.0-flash')

        # Bedrock multi-model routing
        # Default model (used when LLM_PROVIDER=bedrock and no specific override)
        self.BEDROCK_MODEL_ID: str = os.environ.get(
            'BEDROCK_MODEL_ID', 'amazon.nova-lite-v1:0'
        )
        # Per-service model overrides (optional — falls back to BEDROCK_MODEL_ID)
        self.BEDROCK_PLANNER_MODEL: str = os.environ.get(
            'BEDROCK_PLANNER_MODEL', 'amazon.nova-pro-v1:0'
        )
        self.BEDROCK_CLASSIFIER_MODEL: str = os.environ.get(
            'BEDROCK_CLASSIFIER_MODEL', 'amazon.nova-micro-v1:0'
        )
        
        # Server Configuration
        self.PORT: int = int(os.environ.get('PORT', 8000))
        self.SECRET_KEY: str = os.environ.get('SECRET_KEY', 'dev-secret-key-change-in-production')
        self.DEBUG: bool = os.environ.get('DEBUG', 'False').lower() == 'true'
        self.LOG_LEVEL: str = os.environ.get('LOG_LEVEL', 'INFO')
        
        # CORS Configuration
        allowed_origins_str = os.environ.get('ALLOWED_ORIGINS', '')
        self.ALLOWED_ORIGINS: List[str] = (
            [o.strip() for o in allowed_origins_str.split(',') if o.strip()]
            if allowed_origins_str.strip()
            else ["*"]
        )

        # Database Configuration
        self.DATABASE_URL: str = os.environ.get(
            'DATABASE_URL',
            'postgresql://localhost:5432/aurafactory'
        )
        
        # AWS/Bedrock Configuration
        self.ENABLE_BEDROCK_LLM: bool = os.environ.get('ENABLE_BEDROCK_LLM', 'False').lower() == 'true'
        self.AWS_REGION: str = os.environ.get('AWS_REGION', 'us-east-1')
        # Note: AWS_ACCESS_KEY_ID and AWS_SECRET_ACCESS_KEY are read directly
        # by boto3 from the environment — no need to store them here.
        
        # Paths Configuration
        self.PROMPTS_DIR: str = os.environ.get('PROMPTS_DIR', './prompts')
        self.SKILLS_DIR: str = os.environ.get('SKILLS_DIR', './skills')
        
        self._initialized = True
    
    @staticmethod
    def _parse_guild_ids(guild_ids_str: str) -> List[int]:
        """Parse comma-separated guild IDs from environment variable."""
        if not guild_ids_str.strip():
            return []
        try:
            return [int(gid.strip()) for gid in guild_ids_str.split(',') if gid.strip()]
        except ValueError:
            return []
    
    @classmethod
    def get_instance(cls) -> 'Config':
        """Get or create the singleton instance."""
        return cls()

    # Lowercase property aliases (used by services)
    @property
    def discord_client_id(self) -> str:
        return self.DISCORD_CLIENT_ID

    @property
    def discord_client_secret(self) -> str:
        return self.DISCORD_CLIENT_SECRET

    @property
    def discord_redirect_uri(self) -> str:
        return self.DISCORD_REDIRECT_URI


# Singleton instance
config = Config.get_instance()
settings = config  # Alias — main.py and services use `from app.config import settings`

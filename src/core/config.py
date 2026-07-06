"""
Centralized configuration with validation and type safety.
"""

import os
import logging
from typing import List, Optional, Set
from dataclasses import dataclass, field
from functools import lru_cache
from dotenv import load_dotenv

load_dotenv()


@dataclass(frozen=True)
class Config:
    """Immutable configuration with validation."""
    
    # Bot Configuration
    BOT_TOKEN: str = field(default_factory=lambda: os.getenv('BOT_TOKEN', ''))
    ENVIRONMENT: str = field(default_factory=lambda: os.getenv('ENVIRONMENT', 'development'))
    
    # Database
    DATABASE_URL: str = field(default_factory=lambda: os.getenv('DATABASE_URL', 'sqlite:///translator_bot.db'))
    DATABASE_POOL_SIZE: int = field(default_factory=lambda: int(os.getenv('DATABASE_POOL_SIZE', 10)))
    DATABASE_MAX_OVERFLOW: int = field(default_factory=lambda: int(os.getenv('DATABASE_MAX_OVERFLOW', 20)))
    
    # Redis
    REDIS_URL: str = field(default_factory=lambda: os.getenv('REDIS_URL', ''))
    REDIS_PASSWORD: Optional[str] = field(default_factory=lambda: os.getenv('REDIS_PASSWORD'))
    
    # Admin
    ADMIN_IDS: List[int] = field(default_factory=lambda: [
        int(id.strip()) for id in os.getenv('ADMIN_IDS', '').split(',') if id.strip()
    ])
    
    # Rate Limiting
    RATE_LIMIT_PER_MINUTE: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_PER_MINUTE', 30)))
    RATE_LIMIT_PER_HOUR: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_PER_HOUR', 300)))
    RATE_LIMIT_PER_DAY: int = field(default_factory=lambda: int(os.getenv('RATE_LIMIT_PER_DAY', 1000)))
    
    # Logging
    LOG_LEVEL: str = field(default_factory=lambda: os.getenv('LOG_LEVEL', 'INFO'))
    LOG_FORMAT: str = field(default_factory=lambda: os.getenv('LOG_FORMAT', 'json'))
    
    # Features
    OCR_ENABLED: bool = field(default_factory=lambda: os.getenv('OCR_ENABLED', 'true').lower() == 'true')
    VOICE_ENABLED: bool = field(default_factory=lambda: os.getenv('VOICE_ENABLED', 'true').lower() == 'true')
    PDF_ENABLED: bool = field(default_factory=lambda: os.getenv('PDF_ENABLED', 'true').lower() == 'true')
    GROUP_MODE_ENABLED: bool = field(default_factory=lambda: os.getenv('GROUP_MODE_ENABLED', 'true').lower() == 'true')
    
    # Cache
    CACHE_TTL: int = field(default_factory=lambda: int(os.getenv('CACHE_TTL', 3600)))
    CACHE_MAX_SIZE: int = field(default_factory=lambda: int(os.getenv('CACHE_MAX_SIZE', 10000)))
    
    # Performance
    WORKER_THREADS: int = field(default_factory=lambda: int(os.getenv('WORKER_THREADS', 4)))
    MAX_CONCURRENT_TRANSLATIONS: int = field(default_factory=lambda: int(os.getenv('MAX_CONCURRENT_TRANSLATIONS', 10)))
    
    # Translation Limits
    MAX_TEXT_LENGTH: int = 4096
    MAX_HISTORY_SIZE: int = 100
    MAX_FAVORITES: int = 50
    MAX_AUDIO_DURATION: int = 60
    MAX_DOCUMENT_SIZE: int = 10485760  # 10MB
    SUPPORTED_AUDIO_FORMATS: Set[str] = field(default_factory=lambda: {'.ogg', '.mp3', '.wav', '.m4a', '.flac'})
    ALLOWED_DOCUMENT_TYPES: Set[str] = field(default_factory=lambda: {'.txt', '.pdf', '.docx', '.doc', '.rtf', '.odt'})
    
    # UI
    BOT_NAME: str = "🌍 Premium Translator Bot"
    BOT_VERSION: str = "3.0.0"
    BOT_DESCRIPTION: str = "Advanced Translation with Premium Features"
    
    # Railway Deployment
    PORT: int = field(default_factory=lambda: int(os.getenv('PORT', 8080)))
    WEBHOOK_URL: Optional[str] = field(default_factory=lambda: os.getenv('WEBHOOK_URL'))
    WEBHOOK_PATH: str = field(default_factory=lambda: os.getenv('WEBHOOK_PATH', '/webhook'))
    
    def __post_init__(self):
        """Validate configuration."""
        if not self.BOT_TOKEN:
            raise ValueError("BOT_TOKEN is required")
        
        if self.ENVIRONMENT not in ['development', 'staging', 'production']:
            raise ValueError(f"Invalid ENVIRONMENT: {self.ENVIRONMENT}")
    
    @property
    def is_development(self) -> bool:
        """Check if running in development mode."""
        return self.ENVIRONMENT == 'development'
    
    @property
    def is_production(self) -> bool:
        """Check if running in production mode."""
        return self.ENVIRONMENT == 'production'
    
    @property
    def is_staging(self) -> bool:
        """Check if running in staging mode."""
        return self.ENVIRONMENT == 'staging'
    
    @property
    def use_webhook(self) -> bool:
        """Check if webhook should be used."""
        return self.is_production and self.WEBHOOK_URL


@lru_cache()
def get_config() -> Config:
    """Get cached configuration instance."""
    return Config()


def setup_logging():
    """Setup logging with JSON or text format."""
    config = get_config()
    
    # Create logs directory
    os.makedirs('logs', exist_ok=True)
    os.makedirs('temp', exist_ok=True)
    os.makedirs('exports', exist_ok=True)
    
    # Configure logging
    handlers = [
        logging.FileHandler('logs/bot.log'),
        logging.StreamHandler()
    ]
    
    if config.LOG_FORMAT == 'json':
        # JSON logging for production
        try:
            import json_logging
            json_logging.init_non_web(enable_json=True)
            logging.setLoggerClass(json_logging.JSONLogger)
        except ImportError:
            pass
    
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL.upper()),
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S',
        handlers=handlers
    )
    
    return logging.getLogger(__name__)

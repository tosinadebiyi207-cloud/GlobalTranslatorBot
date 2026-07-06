"""
Translation service with async support and caching.
"""

import asyncio
import hashlib
import time
from typing import Optional, Tuple, Dict, Any, List
from functools import lru_cache
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from deep_translator import GoogleTranslator, single_detection
from deep_translator.exceptions import RequestError
from src.core.config import get_config
from src.core.exceptions import TranslationError
from src.core.decorators import async_retry, measure_performance
from src.services.cache import cache_service
from src.database.base import get_db
from src.database.models import Translation
import logging

logger = logging.getLogger(__name__)


class TranslationService:
    """Async translation service with caching."""
    
    _instance: Optional['TranslationService'] = None
    _supported_languages: Optional[Dict[str, str]] = None
    _language_cache = {}
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    @property
    def supported_languages(self) -> Dict[str, str]:
        """Get supported languages with caching."""
        if self._supported_languages is None:
            try:
                self._supported_languages = GoogleTranslator().get_supported_languages(as_dict=True)
            except Exception:
                self._supported_languages = {
                    'en': 'English', 'es': 'Spanish', 'fr': 'French',
                    'de': 'German', 'ar': 'Arabic', 'zh-CN': 'Chinese',
                    'hi': 'Hindi', 'yo': 'Yoruba', 'ig': 'Igbo', 'ha': 'Hausa'
                }
        return self._supported_languages
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(RequestError),
        reraise=True
    )
    async def detect_language(self, text: str) -> Optional[str]:
        """Detect language asynchronously."""
        try:
            if not text or len(text.strip()) < 2:
                return None
            
            # Run in thread pool for blocking operation
            loop = asyncio.get_event_loop()
            detection = await loop.run_in_executor(
                None,
                single_detection,
                text,
                ''
            )
            
            return detection.get('language') if detection else None
            
        except Exception as e:
            logger.error(f"Language detection error: {e}")
            return None
    
    @async_retry(max_retries=3, delay=1.0, backoff=2.0, exceptions=(RequestError,))
    @measure_performance
    async def translate(
        self,
        text: str,
        target_lang: str,
        source_lang: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> Tuple[Optional[str], Optional[str], Optional[float]]:
        """
        Translate text with caching and analytics.
        
        Returns:
            Tuple of (translated_text, detected_lang, translation_time_ms)
        """
        if not text or not text.strip():
            return None, None, None
        
        # Check cache
        cache_key = self._get_cache_key(text, target_lang)
        cached_result = await cache_service.get(cache_key)
        if cached_result:
            logger.debug(f"Cache hit for key: {cache_key}")
            return cached_result['text'], cached_result.get('detected_lang'), 0
        
        start_time = time.perf_counter()
        
        try:
            # Detect source language
            detected_lang = None
            if not source_lang:
                detected_lang = await self.detect_language(text)
                if detected_lang and detected_lang == target_lang:
                    return text, detected_lang, 0
                source_lang = detected_lang or 'auto'
            
            # Perform translation in thread pool
            loop = asyncio.get_event_loop()
            translated = await loop.run_in_executor(
                None,
                self._translate_sync,
                text,
                source_lang,
                target_lang
            )
            
            if not translated:
                return None, None, None
            
            # Cache result
            await cache_service.set(
                cache_key,
                {
                    'text': translated,
                    'detected_lang': detected_lang
                },
                ttl=get_config().CACHE_TTL
            )
            
            # Save to database if user provided
            if user_id:
                await self._save_translation(
                    user_id,
                    text,
                    translated,
                    source_lang,
                    target_lang,
                    detected_lang,
                    (time.perf_counter() - start_time) * 1000
                )
            
            translation_time = (time.perf_counter() - start_time) * 1000
            return translated, detected_lang, translation_time
            
        except Exception as e:
            logger.error(f"Translation error: {e}")
            raise TranslationError(f"Translation failed: {str(e)}") from e
    
    def _translate_sync(self, text: str, source_lang: str, target_lang: str) -> Optional[str]:
        """Synchronous translation for thread pool."""
        try:
            translator = GoogleTranslator(source=source_lang, target=target_lang)
            return translator.translate(text)
        except Exception as e:
            logger.error(f"Sync translation error: {e}")
            return None
    
    def _get_cache_key(self, text: str, target_lang: str) -> str:
        """Generate cache key for translation."""
        text_hash = hashlib.md5(text.encode()).hexdigest()
        return f"translation:{text_hash}:{target_lang}"
    
    async def _save_translation(
        self,
        user_id: int,
        source_text: str,
        translated_text: str,
        source_lang: str,
        target_lang: str,
        detected_lang: Optional[str],
        translation_time_ms: float
    ):
        """Save translation to database."""
        try:
            async with get_db() as session:
                translation = Translation(
                    user_id=user_id,
                    source_text=source_text,
                    translated_text=translated_text,
                    source_lang=source_lang,
                    target_lang=target_lang,
                    detected_lang=detected_lang,
                    text_length=len(source_text),
                    character_count=len(source_text),
                    word_count=len(source_text.split()),
                    translation_time_ms=translation_time_ms
                )
                session.add(translation)
        except Exception as e:
            logger.error(f"Failed to save translation: {e}")
    
    @lru_cache(maxsize=1000)
    def get_language_name(self, code: str) -> str:
        """Get language name with caching."""
        return self.supported_languages.get(code, code)
    
    def get_supported_languages_list(self) -> List[Tuple[str, str]]:
        """Get sorted list of supported languages."""
        return sorted(self.supported_languages.items(), key=lambda x: x[1])
    
    async def translate_batch(
        self,
        texts: List[str],
        target_lang: str,
        source_lang: Optional[str] = None,
        user_id: Optional[int] = None
    ) -> List[Tuple[Optional[str],

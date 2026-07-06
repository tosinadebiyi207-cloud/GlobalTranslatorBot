"""
Decorators for common functionality.
"""

import asyncio
import functools
import logging
import time
from typing import Callable, Any, Optional, TypeVar, cast
from telegram import Update
from telegram.ext import ContextTypes
from src.core.exceptions import RateLimitError, TranslatorBotError
from src.core.config import get_config

logger = logging.getLogger(__name__)
F = TypeVar('F', bound=Callable[..., Any])


def async_retry(
    max_retries: int = 3,
    delay: float = 1.0,
    backoff: float = 2.0,
    exceptions: tuple = (Exception,)
) -> Callable[[F], F]:
    """Retry decorator for async functions."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            retries = 0
            current_delay = delay
            
            while retries < max_retries:
                try:
                    return await func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries >= max_retries:
                        logger.error(f"Function {func.__name__} failed after {max_retries} retries: {e}")
                        raise
                    
                    logger.warning(f"Retry {retries}/{max_retries} for {func.__name__}: {e}")
                    await asyncio.sleep(current_delay)
                    current_delay *= backoff
            
            raise RuntimeError(f"Max retries exceeded for {func.__name__}")
        
        return cast(F, wrapper)
    return decorator


def async_log(
    log_args: bool = True,
    log_result: bool = False,
    log_time: bool = True
) -> Callable[[F], F]:
    """Log decorator for async functions."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            start_time = time.time()
            func_name = func.__name__
            
            logger.debug(f"Starting {func_name}")
            
            if log_args:
                logger.debug(f"{func_name} args: {args}, kwargs: {kwargs}")
            
            try:
                result = await func(*args, **kwargs)
                
                if log_time:
                    elapsed = (time.time() - start_time) * 1000
                    logger.debug(f"{func_name} completed in {elapsed:.2f}ms")
                
                if log_result:
                    logger.debug(f"{func_name} result: {result}")
                
                return result
                
            except Exception as e:
                logger.error(f"{func_name} failed: {e}")
                raise
        
        return cast(F, wrapper)
    return decorator


def handle_errors(func: F) -> F:
    """Handle errors and send user-friendly messages."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        try:
            return await func(update, context, *args, **kwargs)
        except RateLimitError as e:
            await update.message.reply_text(
                f"⚠️ <b>Rate Limit Exceeded</b>\n\n"
                f"Please wait {e.retry_after} seconds before trying again.",
                parse_mode='HTML'
            )
        except TranslatorBotError as e:
            logger.error(f"Bot error: {e}", exc_info=True)
            await update.message.reply_text(
                f"❌ <b>Error</b>\n\n{e.message}\n\n"
                f"Please try again later or contact support.",
                parse_mode='HTML'
            )
        except Exception as e:
            logger.error(f"Unexpected error: {e}", exc_info=True)
            await update.message.reply_text(
                "❌ <b>Unexpected Error</b>\n\n"
                "Something went wrong. Please try again later.\n"
                "If the problem persists, contact support.",
                parse_mode='HTML'
            )
    
    return cast(F, wrapper)


def require_admin(func: F) -> F:
    """Check if user is admin."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        user_id = update.effective_user.id
        config = get_config()
        
        if user_id not in config.ADMIN_IDS:
            await update.message.reply_text(
                "⛔ <b>Access Denied</b>\n\n"
                "This command is only available for administrators.",
                parse_mode='HTML'
            )
            return
        
        return await func(update, context, *args, **kwargs)
    
    return cast(F, wrapper)


def require_group(func: F) -> F:
    """Check if command is used in a group."""
    @functools.wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if update.effective_chat and update.effective_chat.type == 'private':
            await update.message.reply_text(
                "👥 <b>Group Only</b>\n\n"
                "This command is only available in groups.",
                parse_mode='HTML'
            )
            return
        
        return await func(update, context, *args, **kwargs)
    
    return cast(F, wrapper)


def rate_limit(per_minute: int = 30, per_hour: int = 300) -> Callable[[F], F]:
    """Rate limit decorator using Redis or memory."""
    def decorator(func: F) -> F:
        @functools.wraps(func)
        async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
            user_id = update.effective_user.id
            from src.services.rate_limiter import rate_limiter
            
            allowed, remaining, reset_time = await rate_limiter.is_allowed(user_id)
            
            if not allowed:
                raise RateLimitError(
                    f"Rate limit exceeded. Please try again in {reset_time}s.",
                    retry_after=reset_time
                )
            
            return await func(update, context, *args, **kwargs)
        
        return cast(F, wrapper)
    return decorator


def measure_performance(func: F) -> F:
    """Measure and log function performance."""
    @functools.wraps(func)
    async def wrapper(*args, **kwargs):
        start_time = time.perf_counter()
        try:
            result = await func(*args, **kwargs)
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.info(f"PERF: {func.__name__} took {elapsed:.2f}ms")
            return result
        except Exception as e:
            elapsed = (time.perf_counter() - start_time) * 1000
            logger.error(f"PERF: {func.__name__} failed after {elapsed:.2f}ms: {e}")
            raise
    
    return cast(F, wrapper)

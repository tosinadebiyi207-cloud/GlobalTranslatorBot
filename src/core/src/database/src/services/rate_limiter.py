"""
Distributed rate limiter with Redis or in-memory fallback.
"""

import time
import asyncio
from typing import Optional, Tuple, Dict, Any
from collections import defaultdict
import hashlib
from src.core.config import get_config
from src.core.exceptions import RateLimitError

class MemoryRateLimiter:
    """In-memory rate limiter fallback."""
    
    def __init__(self):
        self.minute_limits: Dict[int, list] = defaultdict(list)
        self.hour_limits: Dict[int, list] = defaultdict(list)
        self.day_limits: Dict[int, list] = defaultdict(list)
    
    async def is_allowed(self, user_id: int) -> Tuple[bool, int, int]:
        """Check if user is allowed."""
        current_time = time.time()
        
        # Clean old entries
        self._clean_entries(user_id, current_time)
        
        minute_count = len(self.minute_limits[user_id])
        hour_count = len(self.hour_limits[user_id])
        day_count = len(self.day_limits[user_id])
        
        config = get_config()
        
        if minute_count >= config.RATE_LIMIT_PER_MINUTE:
            return False, 60, 0
        if hour_count >= config.RATE_LIMIT_PER_HOUR:
            return False, 3600, 0
        if day_count >= config.RATE_LIMIT_PER_DAY:
            return False, 86400, 0
        
        # Add request
        self.minute_limits[user_id].append(current_time)
        self.hour_limits[user_id].append(current_time)
        self.day_limits[user_id].append(current_time)
        
        remaining_minute = config.RATE_LIMIT_PER_MINUTE - minute_count - 1
        remaining_hour = config.RATE_LIMIT_PER_HOUR - hour_count - 1
        
        return True, remaining_minute, remaining_hour
    
    def _clean_entries(self, user_id: int, current_time: float):
        """Clean old entries."""
        minute_threshold = current_time - 60
        hour_threshold = current_time - 3600
        day_threshold = current_time - 86400
        
        if user_id in self.minute_limits:
            self.minute_limits[user_id] = [
                t for t in self.minute_limits[user_id] if t > minute_threshold
            ]
        if user_id in self.hour_limits:
            self.hour_limits[user_id] = [
                t for t in self.hour_limits[user_id] if t > hour_threshold
            ]
        if user_id in self.day_limits:
            self.day_limits[user_id] = [
                t for t in self.day_limits[user_id] if t > day_threshold
            ]


class RateLimiter:
    """Rate limiter with Redis or memory fallback."""
    
    def __init__(self):
        self.memory = MemoryRateLimiter()
        self.redis_client = None
        self._initialized = False
    
    async def initialize(self):
        """Initialize Redis connection."""
        if self._initialized:
            return
        
        config = get_config()
        
        if config.REDIS_URL:
            try:
                import redis.asyncio as redis
                self.redis_client = redis.from_url(
                    config.REDIS_URL,
                    password=config.REDIS_PASSWORD,
                    decode_responses=True,
                    socket_timeout=5,
                    socket_connect_timeout=5,
                    retry_on_timeout=True
                )
                await self.redis_client.ping()
                self._initialized = True
                return
            except Exception:
                pass
        
        self._initialized = True
    
    async def is_allowed(self, user_id: int) -> Tuple[bool, int, int]:
        """Check if user is allowed."""
        try:
            await self.initialize()
            
            if self.redis_client:
                return await self._check_redis(user_id)
            else:
                return await self.memory.is_allowed(user_id)
                
        except Exception as e:
            # Fallback to memory
            return await self.memory.is_allowed(user_id)
    
    async def _check_redis(self, user_id: int) -> Tuple[bool, int, int]:
        """Check rate limit using Redis."""
        config = get_config()
        key = f"ratelimit:{user_id}"
        current_time = int(time.time())
        
        # Use sliding window with minute and hour
        minute_window = current_time - 60
        hour_window = current_time - 3600
        day_window = current_time - 86400
        
        # Pipeline for efficiency
        pipe = self.redis_client.pipeline()
        
        # Clean old entries
        pipe.zremrangebyscore(f"{key}:minute", 0, minute_window)
        pipe.zremrangebyscore(f"{key}:hour", 0, hour_window)
        pipe.zremrangebyscore(f"{key}:day", 0, day_window)
        
        # Get counts
        pipe.zcard(f"{key}:minute")
        pipe.zcard(f"{key}:hour")
        pipe.zcard(f"{key}:day")
        
        results = await pipe.execute()
        minute_count = results[3]
        hour_count = results[4]
        day_count = results[5]
        
        # Check limits
        if minute_count >= config.RATE_LIMIT_PER_MINUTE:
            return False, 60 - (current_time - int(await self._get_oldest(f"{key}:minute"))), 0
        if hour_count >= config.RATE_LIMIT_PER_HOUR:
            return False, 3600 - (current_time - int(await self._get_oldest(f"{key}:hour"))), 0
        if day_count >= config.RATE_LIMIT_PER_DAY:
            return False, 86400 - (current_time - int(await self._get_oldest(f"{key}:day"))), 0
        
        # Add current request
        pipe = self.redis_client.pipeline()
        pipe.zadd(f"{key}:minute", {str(current_time): current_time})
        pipe.zadd(f"{key}:hour", {str(current_time): current_time})
        pipe.zadd(f"{key}:day", {str(current_time): current_time})
        pipe.expire(f"{key}:minute", 120)  # Keep for 2 minutes
        pipe.expire(f"{key}:hour", 7200)   # Keep for 2 hours
        pipe.expire(f"{key}:day", 172800)  # Keep for 2 days
        await pipe.execute()
        
        remaining_minute = config.RATE_LIMIT_PER_MINUTE - minute_count - 1
        remaining_hour = config.RATE_LIMIT_PER_HOUR - hour_count - 1
        
        return True, remaining_minute, remaining_hour
    
    async def _get_oldest(self, key: str) -> Optional[float]:
        """Get oldest timestamp in Redis sorted set."""
        try:
            result = await self.redis_client.zrange(key, 0, 0, withscores=True)
            if result:
                return result[0][1]
        except Exception:
            pass
        return 0
    
    async def get_stats(self, user_id: int) -> Dict[str, int]:
        """Get rate limit stats for a user."""
        config = get_config()
        current_time = int(time.time())
        
        if self.redis_client:
            try:
                pipe = self.redis_client.pipeline()
                pipe.zcard(f"ratelimit:{user_id}:minute")
                pipe.zcard(f"ratelimit:{user_id}:hour")
                pipe.zcard(f"ratelimit:{user_id}:day")
                results = await pipe.execute()
                
                return {
                    'minute_count': results[0],
                    'hour_count': results[1],
                    'day_count': results[2],
                    'minute_limit': config.RATE_LIMIT_PER_MINUTE,
                    'hour_limit': config.RATE_LIMIT_PER_HOUR,
                    'day_limit': config.RATE_LIMIT_PER_DAY
                }
            except Exception:
                pass
        
        return await self.memory.get_stats(user_id)


# Global rate limiter instance
rate_limiter = RateLimiter()

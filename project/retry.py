# retry.py - Retry decorator with exponential backoff
import time
import logging
from functools import wraps
from typing import Callable, TypeVar, Tuple
import requests

T = TypeVar('T')

class RetryConfig:
    """Configuration for retry behavior"""
    def __init__(
        self,
        max_retries: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        retryable_status_codes: Tuple[int, ...] = (429, 500, 502, 503, 504)
    ):
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.retryable_status_codes = retryable_status_codes


def with_retry(config: RetryConfig = None):
    """
    Decorator for retry with exponential backoff.

    Retries on:
    - requests.HTTPError with retryable status codes (429, 5xx by default)
    - requests.RequestException (network errors, timeouts)

    Example:
        @with_retry(RetryConfig(max_retries=3))
        def upload_file(data):
            response = requests.post(url, data=data)
            response.raise_for_status()
            return response.json()
    """
    if config is None:
        config = RetryConfig()

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> T:
            last_exception = None

            for attempt in range(config.max_retries + 1):
                try:
                    return func(*args, **kwargs)

                except requests.HTTPError as e:
                    # Check if status code is retryable
                    if (e.response is not None and
                        e.response.status_code in config.retryable_status_codes):
                        last_exception = e

                        if attempt < config.max_retries:
                            delay = min(
                                config.base_delay * (config.exponential_base ** attempt),
                                config.max_delay
                            )
                            logging.warning(
                                f"{func.__name__}: Retry {attempt + 1}/{config.max_retries} "
                                f"after {delay:.1f}s (HTTP {e.response.status_code})"
                            )
                            time.sleep(delay)
                            continue
                    # Non-retryable status code, raise immediately
                    raise

                except requests.RequestException as e:
                    # Network errors, timeouts, etc.
                    last_exception = e

                    if attempt < config.max_retries:
                        delay = min(
                            config.base_delay * (config.exponential_base ** attempt),
                            config.max_delay
                        )
                        logging.warning(
                            f"{func.__name__}: Retry {attempt + 1}/{config.max_retries} "
                            f"after {delay:.1f}s ({type(e).__name__}: {e})"
                        )
                        time.sleep(delay)
                        continue
                    # Max retries exceeded
                    raise

            # This should never be reached due to raise above, but for type safety
            if last_exception:
                raise last_exception
            raise RuntimeError("Retry logic error")

        return wrapper
    return decorator

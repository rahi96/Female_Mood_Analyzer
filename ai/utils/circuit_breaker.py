"""Circuit breaker pattern for resilient LLM API calls."""

from enum import Enum
import time
from typing import Any, Callable


class CircuitState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"          # Normal operation
    OPEN = "open"              # Failing, reject requests
    HALF_OPEN = "half_open"    # Testing if recovered


class CircuitBreakerError(Exception):
    """Raised when circuit breaker is open."""
    pass


class CircuitBreaker:
    """Prevent cascading failures when external service (LLM) is down."""
    
    def __init__(self, failure_threshold: int = 5, timeout: int = 60):
        """
        Initialize circuit breaker.
        
        Args:
            failure_threshold: Number of failures before opening circuit
            timeout: Seconds to wait before attempting recovery (half-open)
        """
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None
    
    async def call(self, func: Callable, *args, **kwargs) -> Any:
        """
        Execute function with circuit breaker protection.
        
        Raises CircuitBreakerError if circuit is open.
        """
        # If circuit is open, check if we should try recovery
        if self.state == CircuitState.OPEN:
            if self.last_failure_time and time.time() - self.last_failure_time > self.timeout:
                self.state = CircuitState.HALF_OPEN
            else:
                raise CircuitBreakerError(
                    f"Circuit breaker OPEN. Service unavailable. "
                    f"Will retry after {self.timeout}s timeout."
                )
        
        try:
            result = await func(*args, **kwargs)
            
            # Success → reset circuit
            if self.state == CircuitState.HALF_OPEN:
                self.state = CircuitState.CLOSED
                self.failures = 0
            
            return result
        
        except Exception as e:
            self.failures += 1
            self.last_failure_time = time.time()
            
            # Too many failures → open circuit
            if self.failures >= self.failure_threshold:
                self.state = CircuitState.OPEN
            
            raise
    
    def reset(self) -> None:
        """Manually reset circuit breaker to closed state."""
        self.failures = 0
        self.state = CircuitState.CLOSED
        self.last_failure_time = None

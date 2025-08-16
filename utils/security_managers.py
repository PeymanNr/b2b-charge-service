import json
import threading
import time
import hashlib
import uuid
from django.core.cache import cache
from django.conf import settings
import logging
from typing import Tuple, Optional, Dict, Any
from decimal import Decimal


logger = logging.getLogger('security_managers')


class BaseCacheManager:
    """
    Base class for cache operations and deduplication management
    """
    
    def __init__(self, cache_backend=None, default_timeout: int = 300):
        self.cache = cache_backend or cache
        self.default_timeout = default_timeout
    
    def _generate_hash_key(self, data_string: str, prefix: str) -> str:
        """Generate a unique hash key"""
        hash_object = hashlib.sha256(data_string.encode())
        return f"{prefix}:{hash_object.hexdigest()}"
    
    def _safe_cache_operation(self, operation_name: str, operation_func) -> Any:
        """Safely execute cache operation with error handling"""
        try:
            return operation_func()
        except Exception as e:
            logger.error(f"Error in {operation_name}: {str(e)}")
            return None
    
    def _check_existing_record(self, key: str) -> Optional[Dict]:
        """Check for existing record in cache"""
        return self._safe_cache_operation(
            "check_existing_record",
            lambda: self.cache.get(key)
        )
    
    def _store_record(self, key: str, data: Dict, timeout: int = None) -> bool:
        """Store record in cache"""
        timeout = timeout or self.default_timeout
        result = self._safe_cache_operation(
            "store_record",
            lambda: self.cache.set(key, data, timeout=timeout)
        )
        return result is not None


class DistributedLockManager(BaseCacheManager):
    """
    Distributed lock manager to prevent race conditions
    Supports Redis/Memcached backends
    """

    def __init__(self, cache_backend=None):
        super().__init__(cache_backend, getattr(settings, 'DISTRIBUTED_LOCK_TIMEOUT', 30))
        self.lock_timeout = self.default_timeout
        self.thread_local = threading.local()

    def acquire_lock(self, key: str, timeout: Optional[int] = None, identifier: Optional[str] = None) -> Tuple[bool, Optional[str]]:
        """
        Acquire distributed lock
        Returns: (success: bool, lock_identifier: str)
        """
        timeout = timeout or self.lock_timeout
        identifier = identifier or self._generate_identifier()
        end = time.time() + timeout

        lock_key = f"lock:{key}"

        while time.time() < end:
            result = self._safe_cache_operation(
                "acquire_lock",
                lambda: self.cache.add(lock_key, identifier, timeout=self.lock_timeout)
            )
            
            if result:
                logger.info(f"Lock acquired successfully: {key} by {identifier}")
                return True, identifier

            time.sleep(0.001)  # 1ms

        logger.warning(f"Failed to acquire lock: {key}")
        return False, None

    def release_lock(self, key: str, identifier: str) -> bool:
        """
        Safely release distributed lock
        Only releases if the identifier matches
        """
        lock_key = f"lock:{key}"
        stored_identifier = self._safe_cache_operation(
            "get_lock_identifier",
            lambda: self.cache.get(lock_key)
        )

        if stored_identifier == identifier:
            result = self._safe_cache_operation(
                "delete_lock",
                lambda: self.cache.delete(lock_key)
            )
            if result is not None:
                logger.info(f"Lock released successfully: {key} by {identifier}")
                return True
        else:
            logger.warning(f"Lock release failed - identifier mismatch: {key}")
            
        return False

    def _generate_identifier(self) -> str:
        """Generate unique identifier for lock"""
        return f"{threading.current_thread().ident}_{uuid.uuid4().hex[:8]}"

    def is_locked(self, key: str) -> bool:
        """Check lock status"""
        result = self._safe_cache_operation(
            "check_lock",
            lambda: self.cache.get(f"lock:{key}")
        )
        return result is not None


class IdempotencyManager(BaseCacheManager):
    """
    Idempotency management to prevent duplicate transactions
    Fully supports Double Spending Protection
    """

    def __init__(self, cache_backend=None):
        super().__init__(cache_backend, getattr(settings, 'IDEMPOTENCY_TIMEOUT', 86400))

    def generate_key(self, **kwargs) -> str:
        """
        Generate idempotency key based on input parameters
        """
        param_string = "_".join([f"{k}:{v}" for k, v in sorted(kwargs.items())])
        return self._generate_hash_key(param_string, "idempotency")

    def check_and_store_operation(self, key: str, operation_data: Dict[str, Any]) -> Tuple[bool, Optional[Dict]]:
        """
        Check and store operation for idempotency
        Returns: (is_duplicate: bool, existing_result: Optional[Dict])
        """
        existing_data = self._check_existing_record(key)
        
        if existing_data:
            logger.warning(f"Duplicate operation detected: {key}")
            return True, existing_data.get('result')

        operation_record = {
            'operation_data': operation_data,
            'status': 'processing',
            'created_at': time.time(),
            'result': None
        }

        if self._store_record(key, operation_record):
            logger.info(f"New operation recorded: {key}")
            return False, None
        
        return False, None

    def update_operation_result(self, key: str, result_data: Dict[str, Any]) -> bool:
        """
        Update operation result
        """
        existing_data = self._check_existing_record(key)
        if not existing_data:
            return False
            
        existing_data['result'] = result_data
        existing_data['status'] = 'completed' if result_data.get('success') else 'failed'
        existing_data['completed_at'] = time.time()

        if self._store_record(key, existing_data):
            logger.info(f"Operation result updated: {key}")
            return True
        return False

    def get_operation_status(self, key: str) -> Optional[Dict]:
        """Get operation status"""
        return self._check_existing_record(key)

    def clear_operation(self, key: str) -> bool:
        """Clear operation from cache"""
        result = self._safe_cache_operation(
            "clear_operation",
            lambda: self.cache.delete(key)
        )
        return result is not None


class DoubleSpendingProtector(BaseCacheManager):
    """
    Advanced protection against double spending
    Supports multiple security layers
    """

    def __init__(self, cache_backend=None):
        super().__init__(cache_backend, getattr(settings, 'DOUBLE_SPENDING_TIMEOUT', 300))

    def create_spending_record(self, vendor_id: int, amount: Decimal, operation_type: str,
                             phone_number: str = None) -> Tuple[bool, str]:
        """
        Create spending record for double spending protection
        Returns: (success: bool, record_key: str)
        """
        unique_id = str(uuid.uuid4())[:8]
        current_time = int(time.time())

        record_data = {
            'vendor_id': vendor_id,
            'amount': str(amount),
            'operation_type': operation_type,
            'phone_number': phone_number,
            'timestamp': time.time(),
            'unique_id': unique_id,
            'created_at': current_time
        }

        record_key = self._generate_spending_key(record_data)

        existing_record = self._check_existing_record(record_key)
        if existing_record and not existing_record.get('completed', False):
            if time.time() - existing_record.get('timestamp', 0) > 300:  # 5 minutes
                logger.warning(f"Removing stale spending record: {record_key}")
                self.cache.delete(record_key)
            else:
                logger.warning(f"Double spending attempt detected: {record_key}")
                return False, record_key

        if self._store_record(record_key, record_data):
            logger.info(f"Spending record created: {record_key}")
            return True, record_key
        
        return False, record_key

    def finalize_spending_record(self, record_key: str, transaction_id: str, success: bool) -> bool:
        """
        Finalize spending record and clean up for successful cases
        """
        record_data = self._check_existing_record(record_key)
        if not record_data:
            return False
            
        record_data['transaction_id'] = transaction_id
        record_data['completed'] = True
        record_data['success'] = success
        record_data['completed_at'] = time.time()

        if success:
            # For successful operations, remove the record immediately to allow new requests
            if self._safe_cache_operation("delete_successful_spending_record",
                                        lambda: self.cache.delete(record_key)):
                logger.info(f"Successful spending record removed: {record_key}")
                return True
        else:
            timeout = 60  # 1 minute for failed operations
            if self._store_record(record_key, record_data, timeout):
                logger.info(f"Failed spending record stored for audit: {record_key}")
                return True

        return False

    def _generate_spending_key(self, record_data: Dict) -> str:
        """Generate unique key for spending record"""
        key_string = f"spend_{record_data['vendor_id']}_{record_data['amount']}_{record_data['operation_type']}"
        if record_data.get('phone_number'):
            key_string += f"_{record_data['phone_number']}"

        if 'unique_id' in record_data:
            key_string += f"_{record_data['unique_id']}"

        return self._generate_hash_key(key_string, "spending")


class RateLimiter(BaseCacheManager):
    """
    Request rate limiting management
    Supports various types of rate limits
    """

    def __init__(self, cache_backend=None):
        super().__init__(cache_backend, 120)  # 2 minutes default for rate limiting

    def check_rate_limit(self, key: str, limit: int, window: int = 60) -> Tuple[bool, int]:
        """
        Check rate limit
        Returns: (allowed: bool, current_count: int)
        """
        current_window = int(time.time() // window)
        rate_key = f"rate:{key}:{current_window}"

        current_count = self._safe_cache_operation(
            "get_rate_count",
            lambda: self.cache.get(rate_key, 0)
        ) or 0

        if current_count >= limit:
            logger.warning(f"Rate limit exceeded: {key} ({current_count}/{limit})")
            return False, current_count

        new_count = self._safe_cache_operation(
            "increment_rate_count", 
            lambda: self._increment_counter(rate_key, window)
        ) or current_count + 1

        return True, new_count

    def _increment_counter(self, rate_key: str, window: int) -> int:
        """Safely increment counter"""
        current_count = self.cache.get(rate_key, 0) + 1
        self.cache.set(rate_key, current_count, timeout=window * 2)
        return current_count

    def reset_rate_limit(self, key: str, window: int = 60) -> bool:
        """Reset rate limit"""
        current_window = int(time.time() // window)
        rate_key = f"rate:{key}:{current_window}"

        result = self._safe_cache_operation(
            "reset_rate_limit",
            lambda: self.cache.delete(rate_key)
        )
        return result is not None


class SecurityAuditLogger:
    """
    Audit logging system for security events
    """

    def __init__(self):
        self.security_logger = logging.getLogger('security_audit')

    def log_security_event(self, event_type: str, vendor_id: int = None,
                          details: Dict = None, severity: str = 'INFO') -> None:
        """
        Log security event
        """
        audit_data = {
            'event_type': event_type,
            'vendor_id': vendor_id,
            'timestamp': time.time(),
            'details': details or {},
            'severity': severity
        }

        log_message = f"SECURITY_EVENT: {event_type} | Vendor: {vendor_id} | Details: {json.dumps(details)}"

        if severity == 'ERROR':
            self.security_logger.error(log_message)
        elif severity == 'WARNING':
            self.security_logger.warning(log_message)
        else:
            self.security_logger.info(log_message)

    def log_transaction_attempt(self, vendor_id: int, operation: str,
                               amount: Decimal, success: bool, error_msg: str = None) -> None:
        """
        Log transaction attempt
        """
        details = {
            'operation': operation,
            'amount': str(amount),
            'success': success,
            'error_message': error_msg
        }

        severity = 'INFO' if success else 'WARNING'
        self.log_security_event('TRANSACTION_ATTEMPT', vendor_id, details, severity)


lock_manager = DistributedLockManager()
idempotency_manager = IdempotencyManager()
double_spending_protector = DoubleSpendingProtector()
rate_limiter = RateLimiter()
security_audit_logger = SecurityAuditLogger()

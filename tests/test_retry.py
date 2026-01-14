"""Tests for retry logic with exponential backoff."""

from unittest.mock import Mock, patch

import pytest
import requests

from dmaf.utils.retry import RetryConfig, with_retry


class TestRetryConfig:
    """Test RetryConfig initialization."""

    def test_default_values(self):
        """Test default retry configuration."""
        config = RetryConfig()

        assert config.max_retries == 3
        assert config.base_delay == 1.0
        assert config.max_delay == 60.0
        assert config.exponential_base == 2.0
        assert config.retryable_status_codes == (429, 500, 502, 503, 504)

    def test_custom_values(self):
        """Test custom retry configuration."""
        config = RetryConfig(
            max_retries=5,
            base_delay=2.0,
            max_delay=120.0,
            exponential_base=3.0,
            retryable_status_codes=(503, 504),
        )

        assert config.max_retries == 5
        assert config.base_delay == 2.0
        assert config.max_delay == 120.0
        assert config.exponential_base == 3.0
        assert config.retryable_status_codes == (503, 504)


class TestWithRetrySuccess:
    """Test successful function calls (no retries needed)."""

    def test_success_on_first_attempt(self):
        """Test that successful calls don't retry."""

        @with_retry()
        def successful_function():
            return "success"

        result = successful_function()
        assert result == "success"

    def test_success_with_custom_config(self):
        """Test successful calls with custom config."""
        config = RetryConfig(max_retries=5)

        @with_retry(config)
        def successful_function(value):
            return value * 2

        result = successful_function(21)
        assert result == 42


class TestWithRetryHTTPError:
    """Test retry behavior on HTTPError."""

    @patch("dmaf.utils.retry.time.sleep")
    def test_retry_on_500_error(self, mock_sleep):
        """Test that 500 errors trigger retry."""
        # Mock response with 500 status
        mock_response = Mock()
        mock_response.status_code = 500

        call_count = 0

        @with_retry(RetryConfig(max_retries=2, base_delay=1.0))
        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                error = requests.HTTPError()
                error.response = mock_response
                raise error
            return "success"

        result = failing_then_success()

        assert result == "success"
        assert call_count == 3
        # Should have slept twice: 1s, 2s
        assert mock_sleep.call_count == 2
        mock_sleep.assert_any_call(1.0)  # First retry: base_delay * 2^0
        mock_sleep.assert_any_call(2.0)  # Second retry: base_delay * 2^1

    @patch("dmaf.utils.retry.time.sleep")
    def test_retry_on_429_rate_limit(self, mock_sleep):
        """Test that 429 (rate limit) errors trigger retry."""
        mock_response = Mock()
        mock_response.status_code = 429

        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def rate_limited_then_success():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error = requests.HTTPError()
                error.response = mock_response
                raise error
            return "success"

        result = rate_limited_then_success()
        assert result == "success"
        assert call_count == 2

    def test_no_retry_on_404_error(self):
        """Test that 404 errors don't retry (not in retryable_status_codes)."""
        mock_response = Mock()
        mock_response.status_code = 404

        call_count = 0

        @with_retry(RetryConfig(max_retries=3))
        def not_found():
            nonlocal call_count
            call_count += 1
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            not_found()

        # Should only be called once (no retries)
        assert call_count == 1

    def test_no_retry_on_400_error(self):
        """Test that 400 errors don't retry."""
        mock_response = Mock()
        mock_response.status_code = 400

        @with_retry()
        def bad_request():
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            bad_request()

    @patch("dmaf.utils.retry.time.sleep")
    def test_max_retries_exceeded(self, mock_sleep):
        """Test that max retries are respected."""
        mock_response = Mock()
        mock_response.status_code = 500

        call_count = 0

        @with_retry(RetryConfig(max_retries=2))
        def always_fails():
            nonlocal call_count
            call_count += 1
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            always_fails()

        # Should be called 3 times: initial + 2 retries
        assert call_count == 3
        assert mock_sleep.call_count == 2


class TestWithRetryRequestException:
    """Test retry behavior on RequestException (network errors)."""

    @patch("dmaf.utils.retry.time.sleep")
    def test_retry_on_connection_error(self, mock_sleep):
        """Test retry on ConnectionError."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def connection_error_then_success():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.ConnectionError("Network error")
            return "success"

        result = connection_error_then_success()
        assert result == "success"
        assert call_count == 2
        assert mock_sleep.call_count == 1

    @patch("dmaf.utils.retry.time.sleep")
    def test_retry_on_timeout(self, mock_sleep):
        """Test retry on Timeout."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def timeout_then_success():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.Timeout("Request timeout")
            return "success"

        result = timeout_then_success()
        assert result == "success"
        assert call_count == 2

    @patch("dmaf.utils.retry.time.sleep")
    def test_max_retries_on_network_error(self, mock_sleep):
        """Test that max retries are respected for network errors."""

        @with_retry(RetryConfig(max_retries=2))
        def always_fails_network():
            raise requests.ConnectionError("Always fails")

        with pytest.raises(requests.ConnectionError):
            always_fails_network()

        # Should retry 2 times
        assert mock_sleep.call_count == 2


class TestExponentialBackoff:
    """Test exponential backoff delay calculation."""

    @patch("dmaf.utils.retry.time.sleep")
    def test_exponential_delays(self, mock_sleep):
        """Test that delays follow exponential backoff."""
        mock_response = Mock()
        mock_response.status_code = 500

        call_count = 0

        @with_retry(RetryConfig(max_retries=3, base_delay=2.0, exponential_base=2.0))
        def always_fails():
            nonlocal call_count
            call_count += 1
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            always_fails()

        # Should have 3 sleep calls: 2.0, 4.0, 8.0
        assert mock_sleep.call_count == 3
        mock_sleep.assert_any_call(2.0)  # 2.0 * 2^0
        mock_sleep.assert_any_call(4.0)  # 2.0 * 2^1
        mock_sleep.assert_any_call(8.0)  # 2.0 * 2^2

    @patch("dmaf.utils.retry.time.sleep")
    def test_max_delay_cap(self, mock_sleep):
        """Test that delays are capped at max_delay."""
        mock_response = Mock()
        mock_response.status_code = 500

        @with_retry(
            RetryConfig(
                max_retries=3,
                base_delay=10.0,
                max_delay=15.0,  # Cap at 15 seconds
                exponential_base=2.0,
            )
        )
        def always_fails():
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            always_fails()

        # Delays should be: 10.0, 15.0 (capped), 15.0 (capped)
        # Original would be: 10.0, 20.0, 40.0
        assert mock_sleep.call_count == 3
        calls = [call.args[0] for call in mock_sleep.call_args_list]
        assert calls == [10.0, 15.0, 15.0]


class TestRetryLogging:
    """Test logging of retry attempts."""

    @patch("dmaf.utils.retry.time.sleep")
    @patch("dmaf.utils.retry.logging.warning")
    def test_logging_on_retry(self, mock_warning, mock_sleep):
        """Test that retry attempts are logged."""
        mock_response = Mock()
        mock_response.status_code = 503

        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def fails_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                error = requests.HTTPError()
                error.response = mock_response
                raise error
            return "success"

        fails_once()

        # Should have logged one retry warning
        assert mock_warning.call_count == 1
        warning_msg = mock_warning.call_args[0][0]
        assert "fails_once" in warning_msg
        assert "Retry 1/1" in warning_msg
        assert "HTTP 503" in warning_msg

    @patch("dmaf.utils.retry.time.sleep")
    @patch("dmaf.utils.retry.logging.warning")
    def test_logging_network_error(self, mock_warning, mock_sleep):
        """Test logging for network errors."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def network_error_once():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise requests.ConnectionError("Network is down")
            return "success"

        network_error_once()

        assert mock_warning.call_count == 1
        warning_msg = mock_warning.call_args[0][0]
        assert "network_error_once" in warning_msg
        assert "ConnectionError" in warning_msg


class TestRetryEdgeCases:
    """Test edge cases and special scenarios."""

    def test_no_retries_config(self):
        """Test with max_retries=0 (no retries)."""
        mock_response = Mock()
        mock_response.status_code = 500

        call_count = 0

        @with_retry(RetryConfig(max_retries=0))
        def fails_immediately():
            nonlocal call_count
            call_count += 1
            error = requests.HTTPError()
            error.response = mock_response
            raise error

        with pytest.raises(requests.HTTPError):
            fails_immediately()

        # Should only be called once (no retries)
        assert call_count == 1

    def test_with_function_arguments(self):
        """Test that decorated functions can accept arguments."""

        @with_retry()
        def add_numbers(a, b, multiplier=1):
            return (a + b) * multiplier

        result = add_numbers(10, 20, multiplier=2)
        assert result == 60

    @patch("dmaf.utils.retry.time.sleep")
    def test_preserves_function_metadata(self, mock_sleep):
        """Test that decorator preserves function metadata."""

        @with_retry()
        def my_function():
            """This is my function."""
            pass

        assert my_function.__name__ == "my_function"
        assert my_function.__doc__ == "This is my function."

    def test_http_error_without_response(self):
        """Test HTTPError without response attribute."""
        call_count = 0

        @with_retry(RetryConfig(max_retries=1))
        def error_no_response():
            nonlocal call_count
            call_count += 1
            error = requests.HTTPError()
            error.response = None  # No response
            raise error

        # Should not retry (no response.status_code to check)
        with pytest.raises(requests.HTTPError):
            error_no_response()

        # Should only be called once
        assert call_count == 1

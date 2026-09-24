import logging

import pytest

from attendance_service.config import RetryConfig
from attendance_service.retry import retry_call


def test_retry_is_bounded_and_eventually_succeeds() -> None:
    attempts = 0
    sleeps = []

    def operation():
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise OSError("temporary")
        return "ok"

    result = retry_call(
        operation,
        retry_on=(OSError,),
        config=RetryConfig(3, 1, 2),
        logger=logging.getLogger("test"),
        operation_name="test",
        sleep=sleeps.append,
    )

    assert result == "ok"
    assert attempts == 3
    assert sleeps == [1, 2]


def test_retry_raises_after_final_attempt() -> None:
    attempts = 0

    def operation():
        nonlocal attempts
        attempts += 1
        raise OSError("still unavailable")

    with pytest.raises(OSError):
        retry_call(
            operation,
            retry_on=(OSError,),
            config=RetryConfig(2, 0, 0),
            logger=logging.getLogger("test"),
            operation_name="test",
            sleep=lambda _: None,
        )

    assert attempts == 2


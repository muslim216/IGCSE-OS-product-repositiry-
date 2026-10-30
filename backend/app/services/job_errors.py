"""What a failed background job is allowed to say to a tutor.

A job's failure is written onto a row a tutor reads (`submission.ai_error`,
`extraction_error`, `booklet.error`, a report's `error`). An exception's own
text is not fit for that: it can carry a library's or a provider's wording,
paths or request detail. The detail belongs in the server log, which every
site already writes; the row gets either a sentence we wrote or the generic
one below.
"""

GENERIC_JOB_ERROR = "Something went wrong on our side. Try again in a few minutes."


class DocumentProblem(ValueError):
    """A problem with the tutor's document that we describe in our own words
    ("No questions were found in the document"). A `ValueError` so that every
    existing `except ValueError` keeps working; the marker is what lets the
    sentence reach the tutor."""

    safe_to_show = True


def safe_job_error(exc: BaseException) -> str:
    """The text to store for a failed job.

    Fails closed: the exception's own text is returned only when its class or
    instance carries `safe_to_show = True`, which a class sets once every
    message it is raised with has been written by us. It is an attribute, the
    same idiom as `job_retryable` in `workers/jobs.py:is_permanent`, and not a
    check on the type: plain `ValueError` is also what pydantic's
    `ValidationError` and many libraries raise, and their text can quote the
    input or a provider's reply."""
    if getattr(exc, "safe_to_show", False) is True:
        text = str(exc).strip()
        if text:
            return text
    return GENERIC_JOB_ERROR

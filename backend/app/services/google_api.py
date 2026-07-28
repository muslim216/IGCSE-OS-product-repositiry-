"""Thin async clients for the Classroom and Drive REST APIs."""

import asyncio

import httpx

CLASSROOM = "https://classroom.googleapis.com/v1"
DRIVE = "https://www.googleapis.com/drive/v3"

# Google Docs-native files can't be downloaded with alt=media; they must be
# exported. Students who type their answers produce these.
EXPORTABLE = {
    "application/vnd.google-apps.document": "application/pdf",
    "application/vnd.google-apps.presentation": "application/pdf",
    "application/vnd.google-apps.drawing": "application/pdf",
    "application/vnd.google-apps.spreadsheet": "application/pdf",
}
SHORTCUT = "application/vnd.google-apps.shortcut"


class GoogleApiError(Exception):
    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


async def _request(
    http: httpx.AsyncClient, token: str, method: str, url: str, **kwargs
) -> httpx.Response:
    """One retry on a rate limit or transient server error, then give up."""
    headers = {**kwargs.pop("headers", {}), "Authorization": f"Bearer {token}"}
    for attempt in range(2):
        resp = await http.request(method, url, headers=headers, **kwargs)
        if resp.status_code in (429, 500, 502, 503, 504) and attempt == 0:
            await asyncio.sleep(2)
            continue
        return resp
    return resp


async def _get_json(http: httpx.AsyncClient, token: str, url: str, params: dict | None = None) -> dict:
    resp = await _request(http, token, "GET", url, params=params)
    if resp.status_code != 200:
        raise GoogleApiError(resp.status_code, f"{resp.status_code} from {url}")
    return resp.json()


async def _paginate(
    http: httpx.AsyncClient, token: str, url: str, key: str, params: dict | None = None
) -> list[dict]:
    items: list[dict] = []
    page: str | None = None
    while True:
        data = await _get_json(http, token, url, {**(params or {}), **({"pageToken": page} if page else {})})
        items.extend(data.get(key, []))
        page = data.get("nextPageToken")
        if not page:
            return items


async def list_courses(http: httpx.AsyncClient, token: str) -> list[dict]:
    return await _paginate(
        http, token, f"{CLASSROOM}/courses", "courses",
        {"teacherId": "me", "courseStates": "ACTIVE", "pageSize": 100},
    )


async def list_coursework(http: httpx.AsyncClient, token: str, course_id: str) -> list[dict]:
    return await _paginate(
        http, token, f"{CLASSROOM}/courses/{course_id}/courseWork", "courseWork", {"pageSize": 100}
    )


async def list_students(http: httpx.AsyncClient, token: str, course_id: str) -> list[dict]:
    return await _paginate(
        http, token, f"{CLASSROOM}/courses/{course_id}/students", "students", {"pageSize": 100}
    )


async def list_student_submissions(
    http: httpx.AsyncClient, token: str, course_id: str, coursework_id: str
) -> list[dict]:
    """All states, not just TURNED_IN, so a run can report who hasn't handed in."""
    return await _paginate(
        http,
        token,
        f"{CLASSROOM}/courses/{course_id}/courseWork/{coursework_id}/studentSubmissions",
        "studentSubmissions",
        {"pageSize": 100},
    )


async def drive_metadata(http: httpx.AsyncClient, token: str, file_id: str) -> dict:
    """Fetch type and size before the bytes, so a huge file is rejected cheaply."""
    return await _get_json(
        http,
        token,
        f"{DRIVE}/files/{file_id}",
        {"fields": "id,name,mimeType,size,shortcutDetails", "supportsAllDrives": "true"},
    )


async def drive_download(http: httpx.AsyncClient, token: str, file_id: str, mime: str) -> bytes:
    """Download a Drive file, exporting Google-native documents to PDF."""
    if mime in EXPORTABLE:
        resp = await _request(
            http,
            token,
            "GET",
            f"{DRIVE}/files/{file_id}/export",
            params={"mimeType": EXPORTABLE[mime]},
            timeout=60,
        )
    else:
        resp = await _request(
            http,
            token,
            "GET",
            f"{DRIVE}/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            timeout=60,
        )
    if resp.status_code != 200:
        raise GoogleApiError(resp.status_code, f"Could not download file {file_id}")
    return resp.content

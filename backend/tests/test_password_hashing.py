"""Password hashing neither stalls the server nor crashes on a long password.

bcrypt is slow on purpose (about a quarter of a second) and the API shares one
event loop with the job worker, so hashing on it froze every other request
while a sign-in ran (`SA-02`). And bcrypt reads at most 72 bytes: the installed
version raises past that, which answered a long password with a 500 (`SA-05`).
"""

import threading

import pytest

from app import security

API = "/api/v1"


@pytest.fixture
def hashing_threads(monkeypatch) -> list[str]:
    """The thread each hash or verify ran on: on the event loop's own thread,
    every other request waits for it."""
    seen: list[str] = []
    real_hash, real_verify = security.hash_password, security.verify_password

    def hash_password(password):
        seen.append(threading.current_thread().name)
        return real_hash(password)

    def verify_password(password, password_hash):
        seen.append(threading.current_thread().name)
        return real_verify(password, password_hash)

    monkeypatch.setattr(security, "hash_password", hash_password)
    monkeypatch.setattr(security, "verify_password", verify_password)
    return seen


def _off_the_loop(seen: list[str]) -> bool:
    return bool(seen) and threading.main_thread().name not in seen


async def test_signing_up_hashes_off_the_event_loop(client, hashing_threads):
    resp = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "T", "email": "t@example.com", "password": "password123"},
    )
    assert resp.status_code == 201, resp.text
    assert _off_the_loop(hashing_threads), hashing_threads


@pytest.mark.parametrize("identifier", ["tutor@example.com", "nobody@example.com"])
async def test_signing_in_verifies_off_the_event_loop(client, tutor, hashing_threads, identifier):
    """A known account and an unknown one alike: the unknown one is checked
    against a dummy hash so the two take the same time."""
    hashing_threads.clear()
    resp = await client.post(
        f"{API}/auth/login", json={"identifier": identifier, "password": "wrong-password"}
    )
    assert resp.status_code == 401, resp.text
    assert _off_the_loop(hashing_threads), hashing_threads


async def test_a_tutor_setting_a_students_password_hashes_off_the_event_loop(
    client, tutor, group, hashing_threads
):
    resp = await client.post(
        f"{API}/groups/{group['id']}/students",
        json={"name": "Bob", "username": "bob01", "password": "password123"},
        headers=tutor["headers"],
    )
    assert resp.status_code == 201, resp.text
    reset = await client.post(
        f"{API}/groups/{group['id']}/students/{resp.json()['id']}/reset-password",
        json={"password": "another-pass1"},
        headers=tutor["headers"],
    )
    assert reset.status_code == 204, reset.text
    assert len(hashing_threads) == 2
    assert _off_the_loop(hashing_threads), hashing_threads


# --- Over 72 bytes --------------------------------------------------------


@pytest.mark.parametrize(
    "password",
    [
        "a" * 73,
        # 40 Arabic letters: 40 characters, 80 bytes.
        "ب" * 40,
    ],
)
async def test_a_password_over_72_bytes_is_refused_with_a_reason(client, password):
    resp = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "T", "email": "t@example.com", "password": password},
    )
    assert resp.status_code == 422, resp.text
    [error] = resp.json()["detail"]
    assert error["loc"][-1] == "password"
    assert "shorter password" in error["msg"]


@pytest.mark.parametrize("password", ["a" * 72, "ب" * 36])
async def test_a_password_of_exactly_72_bytes_still_signs_up_and_in(client, password):
    resp = await client.post(
        f"{API}/auth/register/tutor",
        json={"name": "T", "email": "t@example.com", "password": password},
    )
    assert resp.status_code == 201, resp.text
    login = await client.post(
        f"{API}/auth/login", json={"identifier": "t@example.com", "password": password}
    )
    assert login.status_code == 200, login.text


async def test_every_place_a_password_is_set_refuses_one_over_72_bytes(
    client, tutor, group, student
):
    long = "a" * 73
    headers = tutor["headers"]
    create = await client.post(
        f"{API}/groups/{group['id']}/students",
        json={"name": "Bob", "username": "bob01", "password": long},
        headers=headers,
    )
    assert create.status_code == 422, create.text
    reset = await client.post(
        f"{API}/groups/{group['id']}/students/{student['user']['id']}/reset-password",
        json={"password": long},
        headers=headers,
    )
    assert reset.status_code == 422, reset.text
    for path, body in (
        ("register/student", {"invite_code": "x", "name": "S", "email": "s@example.com"}),
        ("register/parent", {"link_code": "x", "name": "P", "email": "p@example.com"}),
    ):
        resp = await client.post(f"{API}/auth/{path}", json=body | {"password": long})
        # Refused on the password before the code is even looked up.
        assert resp.status_code == 422, (path, resp.text)


async def test_signing_in_with_an_over_long_password_is_just_wrong(client, tutor):
    """Not a 500 and not a 422: an over-long password cannot be anyone's."""
    resp = await client.post(
        f"{API}/auth/login", json={"identifier": "tutor@example.com", "password": "a" * 100}
    )
    assert resp.status_code == 401, resp.text

from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, Response, UploadFile, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.api.file_responses import FILE_RESPONSES, signed_or_proxied_file
from app.models import Group, GroupMember, GroupResource, ResourceKind, User, UserRole
from app.schemas.resources import LibraryResourceOut, ResourceOut
from app.services import storage
from app.services.resource_library import tutor_shared_resources

router = APIRouter(tags=["resources"])


async def _can_view_group(db, user: User, group_id: int) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if user.role in (UserRole.tutor, UserRole.admin):
        # The organization binds first, admins included (`SEC-7`).
        if group.organization_id != user.organization_id or (
            group.tutor_id != user.id and user.role != UserRole.admin
        ):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
        return group
    is_member = await db.scalar(
        select(GroupMember.id).where(
            GroupMember.group_id == group_id, GroupMember.student_id == user.id
        )
    )
    if is_member is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group


def _validated_url(url: str) -> str:
    scheme = urlparse(url).scheme.lower()
    if scheme not in ("http", "https"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, "The recording link must be an http(s) URL"
        )
    return url


def _parse_kind(kind: str | None) -> ResourceKind | None:
    if kind is None:
        return None
    try:
        return ResourceKind(kind)
    except ValueError:
        # `from None`: an unrecognised ?kind= is a client mistake, not an
        # internal fault, so the ValueError behind it is noise in the
        # traceback rather than context worth carrying.
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid kind") from None


def _out(r: GroupResource) -> ResourceOut:
    return ResourceOut(
        id=r.id,
        group_id=r.group_id,
        kind=r.kind.value,
        title=r.title,
        url=r.url,
        file_name=r.file_name,
        created_at=r.created_at,
    )


@router.post(
    "/groups/{group_id}/resources", response_model=ResourceOut, status_code=status.HTTP_201_CREATED
)
async def create_resource(
    group_id: int,
    db: DbSession,
    user: TutorUser,
    kind: Annotated[str, Form(pattern="^(file|recording)$")],
    title: Annotated[str, Form(min_length=1, max_length=255)],
    url: Annotated[str | None, Form()] = None,
    file: Annotated[UploadFile | None, File()] = None,
) -> ResourceOut:
    group = await _can_view_group(db, user, group_id)

    resource = GroupResource(
        group_id=group.id, tutor_id=group.tutor_id, kind=ResourceKind(kind), title=title
    )
    if kind == "recording":
        if not url:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A recording needs a url")
        resource.url = _validated_url(url)
    else:
        if file is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "A file resource needs a file"
            )
        # The group's organization, not the caller's: the resource is owned by
        # the group (`tutor_id=group.tutor_id` above), and an admin acting
        # across organizations would otherwise file it under their own tenant
        # prefix. Matches services/assignments.py.
        path, name, mime = await storage.save_upload(file, organization_id=group.organization_id)
        resource.file_path = path
        resource.file_name = name
        resource.file_mime = mime
    db.add(resource)
    await db.commit()
    return _out(resource)


@router.get("/resources", response_model=list[LibraryResourceOut])
async def list_my_resources(
    db: DbSession, user: TutorUser, kind: str | None = None
) -> list[LibraryResourceOut]:
    """Everything the caller has shared, across their own classes (the Library).

    Own classes only, an admin included — as `list_groups` does — so a colleague's
    material never appears here; an admin reaches it through that class.
    """
    rows = await tutor_shared_resources(
        db,
        tutor_id=user.id,
        organization_id=user.organization_id,
        kind=_parse_kind(kind),
    )
    return [LibraryResourceOut(**_out(r).model_dump(), group_name=name) for r, name in rows]


@router.get("/groups/{group_id}/resources", response_model=list[ResourceOut])
async def list_resources(
    group_id: int, db: DbSession, user: CurrentUser, kind: str | None = None
) -> list[ResourceOut]:
    await _can_view_group(db, user, group_id)
    query = select(GroupResource).where(GroupResource.group_id == group_id)
    parsed = _parse_kind(kind)
    if parsed is not None:
        query = query.where(GroupResource.kind == parsed)
    rows = (await db.scalars(query.order_by(GroupResource.created_at.desc()))).all()
    return [_out(r) for r in rows]


@router.get("/resources/{resource_id}/file", response_class=Response, responses=FILE_RESPONSES)
async def download_resource_file(resource_id: int, db: DbSession, user: CurrentUser) -> Response:
    resource = await db.get(GroupResource, resource_id)
    if resource is None or resource.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await _can_view_group(db, user, resource.group_id)
    # Signed rather than proxied: group resources are tutor-authored teaching
    # material. F3's test is whose personal data is in the file, and here it is
    # nobody's — see docs/av-82-architecture-impact-report.md.
    return await signed_or_proxied_file(
        resource.file_path,
        mime=resource.file_mime or "application/octet-stream",
        filename=resource.file_name or "file",
    )


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: int, db: DbSession, user: CurrentUser) -> None:
    resource = await db.get(GroupResource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    # The organization binds first, for the owner as much as for an admin
    # (`SEC-7`) — and it is the group's, since the resource row carries none.
    # Being named in `tutor_id` is not that check. Past it, only an admin may
    # delete a colleague's resource.
    group = await db.get(Group, resource.group_id)
    if (
        group is None
        or group.organization_id != user.organization_id
        or (resource.tutor_id != user.id and user.role != UserRole.admin)
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(resource)
    await db.commit()

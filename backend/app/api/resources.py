from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, File, Form, HTTPException, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession, TutorUser
from app.models import Group, GroupMember, GroupResource, ResourceKind, User, UserRole
from app.schemas.resources import ResourceOut
from app.services import storage

router = APIRouter(tags=["resources"])


async def _can_view_group(db, user: User, group_id: int) -> Group:
    group = await db.get(Group, group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    if user.role in (UserRole.tutor, UserRole.admin):
        if group.tutor_id != user.id and user.role != UserRole.admin:
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
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A file resource needs a file")
        path, name, mime = await storage.save_upload(file)
        resource.file_path = path
        resource.file_name = name
        resource.file_mime = mime
    db.add(resource)
    await db.commit()
    return _out(resource)


@router.get("/groups/{group_id}/resources", response_model=list[ResourceOut])
async def list_resources(
    group_id: int, db: DbSession, user: CurrentUser, kind: str | None = None
) -> list[ResourceOut]:
    await _can_view_group(db, user, group_id)
    query = select(GroupResource).where(GroupResource.group_id == group_id)
    if kind is not None:
        try:
            query = query.where(GroupResource.kind == ResourceKind(kind))
        except ValueError:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Invalid kind")
    rows = (await db.scalars(query.order_by(GroupResource.created_at.desc()))).all()
    return [_out(r) for r in rows]


@router.get("/resources/{resource_id}/file")
async def download_resource_file(resource_id: int, db: DbSession, user: CurrentUser) -> FileResponse:
    resource = await db.get(GroupResource, resource_id)
    if resource is None or resource.file_path is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await _can_view_group(db, user, resource.group_id)
    return FileResponse(
        storage.absolute_path(resource.file_path),
        media_type=resource.file_mime or "application/octet-stream",
        filename=resource.file_name or "file",
    )


@router.delete("/resources/{resource_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_resource(resource_id: int, db: DbSession, user: CurrentUser) -> None:
    resource = await db.get(GroupResource, resource_id)
    if resource is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    if resource.tutor_id != user.id and user.role != UserRole.admin:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Not found")
    await db.delete(resource)
    await db.commit()

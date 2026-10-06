from pydantic import BaseModel


class DismissalsOut(BaseModel):
    keys: list[str]

from typing import Literal, NotRequired, TypedDict
from pydantic import BaseModel, Field


class Task(BaseModel):
    name: str
    prompt: str

class TestingTaskList(BaseModel):
    tasks: list[Task] = Field(description="A list of testing tasks")

class UniqueUrls(BaseModel):
    """Represents a list of unique URLs"""
    urls: list[str] = Field(description="A list of unique URLs")

class CustomTestDoc(TypedDict):
    _id: str
    _creationTime: int
    name: str
    prompt: str
    type: Literal["user-defined", "buffalo-defined"]
    projectId: NotRequired[str]
    category: NotRequired[str]
    description: NotRequired[str]
    isActive: NotRequired[bool]
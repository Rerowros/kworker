from pydantic import BaseModel

class LastMessage(BaseModel):
    unread: bool = None
    fromUsername: str = None
    fromUserId: int = None
    type: str = None
    time: int = None
    message: str = None

class DialogMessage(BaseModel):
    unread_count: int = None
    last_message: str = None
    time: int = None
    user_id: int = None
    username: str = None
    profilepicture: str = None
    link: str = None
    status: str = None
    blocked_by_user: bool = None
    allowedDialog: bool = None
    lastMessage: LastMessage = None
    has_active_order: bool = None
    archived: bool = None
    isStarred: bool = None

class InboxMessage(BaseModel):
    message_id: int = None
    to_id: int = None
    to_username: str = None
    to_live_date: int = None
    from_id: int = None
    from_username: str = None
    from_live_date: int = None
    from_profilepicture: str = None
    message: str = None
    time: int = None
    unread: bool = None
    type: str = None
    status: str = None
    created_order_id: str = None
    forwarded: bool = None
    updated_at: int = None
    message_page: int = None
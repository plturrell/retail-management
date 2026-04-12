import uuid
from datetime import datetime
from typing import Annotated
from sqlalchemy import func
from sqlalchemy.orm import mapped_column
from sqlalchemy.dialects.postgresql import UUID

uuid_pk = Annotated[
    uuid.UUID,
    mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4),
]

created_at_col = Annotated[
    datetime,
    mapped_column(default=func.now(), nullable=False),
]

updated_at_col = Annotated[
    datetime,
    mapped_column(default=func.now(), onupdate=func.now(), nullable=False),
]

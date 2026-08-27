import enum
import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_address_id() -> str:
    return uuid.uuid4().hex


class AddressType(str, enum.Enum):
    """Kind of postal address attached to a contact."""

    HOME = "Home"
    WORK = "Work"
    OTHER = "Other"


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    first_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    last_name: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    email: Mapped[str] = mapped_column(String(320), nullable=False, unique=True, index=True)
    phone: Mapped[str | None] = mapped_column(String(40))

    company: Mapped[str | None] = mapped_column(String(200))
    job_title: Mapped[str | None] = mapped_column(String(200))

    # Base64 data URL (data:image/...); Text because encoded images run large.
    photo: Mapped[str | None] = mapped_column(Text)

    notes: Mapped[str | None] = mapped_column(Text)

    addresses: Mapped[list["Address"]] = relationship(
        back_populates="contact",
        cascade="all, delete-orphan",
        order_by="Address.position",
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        server_default=func.now(),
        nullable=False,
    )

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Contact id={self.id} email={self.email!r}>"


class Address(Base):
    """One postal address in a strict 1:N relation with a contact."""

    __tablename__ = "addresses"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_new_address_id)
    contact_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("contacts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    type: Mapped[AddressType] = mapped_column(
        Enum(AddressType, values_callable=lambda e: [member.value for member in e]),
        nullable=False,
    )

    street: Mapped[str] = mapped_column(String(300), nullable=False)
    city: Mapped[str | None] = mapped_column(String(120))
    state: Mapped[str | None] = mapped_column(String(120))
    postal_code: Mapped[str | None] = mapped_column(String(20))
    country: Mapped[str | None] = mapped_column(String(120))

    # Preserves the order the client sent, so the UI never reshuffles rows.
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    contact: Mapped[Contact] = relationship(back_populates="addresses")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return f"<Address id={self.id} contact_id={self.contact_id} type={self.type.value}>"

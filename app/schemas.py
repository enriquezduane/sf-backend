import base64
import binascii
import re
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict, EmailStr, Field, computed_field, field_validator

from app.models import AddressType

# Generous ceiling for a base64 data URL — roughly a 3.5 MB source image.
MAX_PHOTO_LENGTH = 5_000_000

# Sanity cap on how many addresses one contact can carry.
MAX_ADDRESSES = 10

# Image subtypes browsers can both produce via FileReader and render in <img>.
# svg+xml is deliberately excluded: an SVG payload can carry scripts.
SUPPORTED_PHOTO_TYPES = frozenset({"png", "jpeg", "jpg", "gif", "webp", "avif"})

# `data:image/<subtype>;base64,<payload>` — padding only at the end, alphabet enforced
# here so the strict decode below only has to catch bad padding.
_PHOTO_DATA_URL = re.compile(r"^data:image/(?P<subtype>[a-z0-9.+-]+);base64,(?P<payload>[A-Za-z0-9+/]+={0,2})$")
_PHOTO_FIELD = Field(
    default=None,
    description=(
        "Contact photo as a base64 data URL (`data:image/...;base64,...`). "
        "Null or omitted means the UI falls back to initials."
    ),
)


def _validate_photo(value: str | None) -> str | None:
    """Accept only well-formed base64 image data URLs; treat blank as null."""
    if value is None or not value.strip():
        return None
    if len(value) > MAX_PHOTO_LENGTH:
        raise ValueError(f"photo must be at most {MAX_PHOTO_LENGTH} characters when base64-encoded")
    match = _PHOTO_DATA_URL.match(value)
    if match is None:
        raise ValueError("photo must be a base64 data URL of the form 'data:image/<type>;base64,<data>'")
    if match["subtype"] not in SUPPORTED_PHOTO_TYPES:
        raise ValueError(f"photo image type must be one of: {', '.join(sorted(SUPPORTED_PHOTO_TYPES))}")
    try:
        base64.b64decode(match["payload"], validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("photo payload is not valid base64") from exc
    return value


class AddressBase(BaseModel):
    """Fields of one postal address, shared by requests and responses."""

    type: AddressType = Field(
        description="Kind of address: `Home`, `Work`, or `Other`.",
        examples=["Home"],
    )
    street: str = Field(
        min_length=1,
        max_length=300,
        description="Street address, including unit or suite. Required, must not be blank.",
        examples=["1 Market St, Suite 400"],
    )
    city: str | None = Field(default=None, max_length=120, description="City or locality.", examples=["San Francisco"])
    state: str | None = Field(
        default=None,
        max_length=120,
        description="State, province, or region.",
        examples=["CA"],
    )
    postal_code: str | None = Field(
        default=None,
        max_length=20,
        description="Postal or ZIP code.",
        examples=["94105"],
    )
    country: str | None = Field(default=None, max_length=120, description="Country name.", examples=["USA"])


class AddressCreate(AddressBase):
    """One address inside a contact create/replace payload. Ids are server-assigned."""


class AddressRead(AddressBase):
    """A stored address, always nested under its owning contact."""

    model_config = ConfigDict(from_attributes=True)

    id: str = Field(description="Server-assigned address identifier.", examples=["8f14e45fceea167a5a36dedd4bea2543"])
    contact_id: int = Field(description="Id of the contact this address belongs to.", examples=[1])


_ADDRESSES_FIELD = Field(
    default_factory=list,
    max_length=MAX_ADDRESSES,
    description=(
        f"Postal addresses for the contact, at most {MAX_ADDRESSES}. "
        "On `PUT`/`POST` this list is the full set: the stored addresses are replaced with it."
    ),
)


class ContactBase(BaseModel):
    """Fields shared by every contact request and response."""

    first_name: str = Field(
        min_length=1,
        max_length=100,
        description="Given name. Required, must not be blank.",
        examples=["Ada"],
    )
    last_name: str = Field(
        min_length=1,
        max_length=100,
        description="Family name. Required, must not be blank.",
        examples=["Lovelace"],
    )
    email: EmailStr = Field(
        max_length=320,
        description=(
            "Primary email address. Required and unique across all contacts; "
            "compared case-insensitively and stored lowercased."
        ),
        examples=["ada@example.com"],
    )
    phone: str | None = Field(
        default=None,
        max_length=40,
        description="Phone number. Stored verbatim — any format is accepted.",
        examples=["+1-415-555-0101"],
    )
    company: str | None = Field(
        default=None,
        max_length=200,
        description="Employer or organisation name.",
        examples=["Analytical Engines"],
    )
    job_title: str | None = Field(
        default=None,
        max_length=200,
        description="Role held at the company.",
        examples=["Mathematician"],
    )
    notes: str | None = Field(
        default=None,
        description="Free-form notes about the contact. No length limit.",
        examples=["Met at the SF hackathon."],
    )
    photo: str | None = _PHOTO_FIELD

    @field_validator("photo")
    @classmethod
    def _check_photo(cls, value: str | None) -> str | None:
        return _validate_photo(value)


_FULL_EXAMPLE = {
    "first_name": "Ada",
    "last_name": "Lovelace",
    "email": "ada@example.com",
    "phone": "+1-415-555-0101",
    "company": "Analytical Engines",
    "job_title": "Mathematician",
    "addresses": [
        {
            "type": "Work",
            "street": "1 Market St, Suite 400",
            "city": "San Francisco",
            "state": "CA",
            "postal_code": "94105",
            "country": "USA",
        }
    ],
    "notes": "Met at the SF hackathon.",
}
_MINIMAL_EXAMPLE = {"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}


class ContactCreate(ContactBase):
    """Body of `POST /api/v1/contacts`. Only the two names and email are required."""

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE, _MINIMAL_EXAMPLE]})

    addresses: list[AddressCreate] = _ADDRESSES_FIELD


class ContactReplace(ContactBase):
    """
    Body of `PUT /api/v1/contacts/{contact_id}`.

    This is a full replacement: any optional field you omit is set back to `null`,
    and the `addresses` list replaces the stored set (omit it to clear all addresses).
    Use `PATCH` if you only want to change some fields.
    """

    model_config = ConfigDict(json_schema_extra={"examples": [_FULL_EXAMPLE]})

    addresses: list[AddressCreate] = _ADDRESSES_FIELD


class ContactUpdate(BaseModel):
    """
    Body of `PATCH /api/v1/contacts/{contact_id}`.

    Every field is optional. Only the fields actually present in the request are
    written; omitted fields keep their current value. Sending an explicit `null`
    clears that field.
    """

    model_config = ConfigDict(
        json_schema_extra={"examples": [{"phone": "+1-415-555-0199", "job_title": "Chief Engineer"}]}
    )

    first_name: str | None = Field(default=None, min_length=1, max_length=100, description="New given name.")
    last_name: str | None = Field(default=None, min_length=1, max_length=100, description="New family name.")
    email: EmailStr | None = Field(
        default=None,
        max_length=320,
        description="New email address. Must not belong to another contact.",
    )
    phone: str | None = Field(default=None, max_length=40, description="New phone number.")
    company: str | None = Field(default=None, max_length=200, description="New company.")
    job_title: str | None = Field(default=None, max_length=200, description="New job title.")
    addresses: list[AddressCreate] | None = Field(
        default=None,
        max_length=MAX_ADDRESSES,
        description=(
            "When present, replaces the whole address list (an empty list removes every address). "
            "Omit to keep the stored addresses untouched."
        ),
    )
    notes: str | None = Field(default=None, description="New notes; replaces the existing text.")
    photo: str | None = _PHOTO_FIELD

    @field_validator("photo")
    @classmethod
    def _check_photo(cls, value: str | None) -> str | None:
        return _validate_photo(value)


class ContactRead(ContactBase):
    """A stored contact, as returned by every contact endpoint."""

    model_config = ConfigDict(
        from_attributes=True,
        json_schema_extra={
            "examples": [
                {
                    **_FULL_EXAMPLE,
                    "id": 1,
                    "addresses": [
                        {
                            **_FULL_EXAMPLE["addresses"][0],
                            "id": "8f14e45fceea167a5a36dedd4bea2543",
                            "contact_id": 1,
                        }
                    ],
                    "full_name": "Ada Lovelace",
                    "created_at": "2026-08-19T16:22:58.189507Z",
                    "updated_at": "2026-08-19T16:22:58.189511Z",
                }
            ]
        },
    )

    id: int = Field(description="Server-assigned identifier.", examples=[1])
    addresses: list[AddressRead] = Field(
        description="Every address linked to the contact, in the order they were sent."
    )
    created_at: datetime = Field(
        description="UTC timestamp of when the contact was created.",
        examples=["2026-08-19T16:22:58.189507Z"],
    )
    updated_at: datetime = Field(
        description="UTC timestamp of the last modification.",
        examples=["2026-08-19T16:22:58.189511Z"],
    )

    @field_validator("created_at", "updated_at")
    @classmethod
    def _as_utc(cls, value: datetime) -> datetime:
        # SQLite discards tzinfo on write; the stored values are UTC, so label
        # them as such rather than emitting an ambiguous naive timestamp.
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value

    @computed_field(description="Convenience concatenation of first and last name.", examples=["Ada Lovelace"])
    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()


class ContactPage(BaseModel):
    """One page of contacts plus the totals a client needs to paginate."""

    items: list[ContactRead] = Field(description="Contacts on this page, ordered by the requested sort.")
    total: int = Field(
        description="Total contacts matching the query, ignoring `limit` and `offset`.",
        examples=[42],
    )
    limit: int = Field(description="Page size that was applied.", examples=[50])
    offset: int = Field(description="Number of records skipped.", examples=[0])


class HealthResponse(BaseModel):
    """Result of the liveness probe."""

    status: str = Field(description="Always `ok` when the service can serve traffic.", examples=["ok"])
    database: str = Field(description="Active SQLAlchemy dialect.", examples=["sqlite"])
    contacts: int = Field(description="Number of contacts currently stored.", examples=[3])


class RootResponse(BaseModel):
    """Discovery document listing the API's entry points."""

    name: str = Field(description="Human-readable service name.", examples=["Contacts API"])
    version: str = Field(description="Service version.", examples=["0.1.0"])
    docs: str = Field(description="Path to the Swagger UI.", examples=["/docs"])
    redoc: str = Field(description="Path to the ReDoc UI.", examples=["/redoc"])
    openapi: str = Field(description="Path to the OpenAPI 3.1 document.", examples=["/openapi.json"])
    contacts: str = Field(description="Base path of the contacts collection.", examples=["/api/v1/contacts"])
    health: str = Field(description="Path to the liveness probe.", examples=["/health"])


class ErrorResponse(BaseModel):
    """Shape of every non-validation error returned by the API."""

    detail: str = Field(
        description="Human-readable explanation of the failure.",
        examples=["Contact 42 not found"],
    )

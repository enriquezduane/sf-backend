BASE = "/api/v1/contacts"


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["database"] == "sqlite"


def test_create_contact(client, payload):
    response = client.post(BASE, json=payload)
    assert response.status_code == 201
    body = response.json()
    assert body["id"] > 0
    assert body["email"] == "ada@example.com"
    assert body["full_name"] == "Ada Lovelace"
    assert body["created_at"] and body["updated_at"]


def test_create_requires_valid_email(client, payload):
    response = client.post(BASE, json={**payload, "email": "not-an-email"})
    assert response.status_code == 422


def test_create_requires_names(client, payload):
    response = client.post(BASE, json={**payload, "first_name": ""})
    assert response.status_code == 422


def test_duplicate_email_conflicts(client, payload):
    assert client.post(BASE, json=payload).status_code == 201
    response = client.post(BASE, json={**payload, "email": "ADA@example.com"})
    assert response.status_code == 409


def test_get_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.get(f"{BASE}/{contact_id}")
    assert response.status_code == 200
    assert response.json()["id"] == contact_id


def test_get_missing_contact_returns_404(client):
    assert client.get(f"{BASE}/9999").status_code == 404


def test_list_pagination_and_total(client, payload):
    for index in range(5):
        client.post(BASE, json={**payload, "email": f"user{index}@example.com"})

    response = client.get(BASE, params={"limit": 2, "offset": 2})
    assert response.status_code == 200
    body = response.json()
    assert body["total"] == 5
    assert len(body["items"]) == 2
    assert body["limit"] == 2 and body["offset"] == 2


def test_list_search(client, payload):
    client.post(BASE, json=payload)
    client.post(
        BASE,
        json={**payload, "first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com", "company": "US Navy"},
    )

    hits = client.get(BASE, params={"search": "hopper"}).json()
    assert hits["total"] == 1
    assert hits["items"][0]["last_name"] == "Hopper"

    by_company = client.get(BASE, params={"search": "navy"}).json()
    assert by_company["total"] == 1

    misses = client.get(BASE, params={"search": "nobody"}).json()
    assert misses["total"] == 0


def test_list_sorting(client, payload):
    client.post(BASE, json={**payload, "last_name": "Zhang", "email": "z@example.com"})
    client.post(BASE, json={**payload, "last_name": "Adams", "email": "a@example.com"})

    names = [
        item["last_name"]
        for item in client.get(BASE, params={"sort_by": "last_name", "order": "asc"}).json()["items"]
    ]
    assert names == ["Adams", "Zhang"]


def test_list_rejects_bad_sort_field(client):
    assert client.get(BASE, params={"sort_by": "; DROP TABLE contacts"}).status_code == 422


def test_patch_updates_only_sent_fields(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"phone": "+1-000-000-0000"})
    assert response.status_code == 200
    body = response.json()
    assert body["phone"] == "+1-000-000-0000"
    assert body["first_name"] == "Ada"
    assert body["company"] == "Analytical Engines"


def test_patch_duplicate_email_conflicts(client, payload):
    first = client.post(BASE, json=payload).json()["id"]
    client.post(BASE, json={**payload, "email": "grace@example.com"})
    response = client.patch(f"{BASE}/{first}", json={"email": "grace@example.com"})
    assert response.status_code == 409


def test_patch_same_email_is_allowed(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.patch(f"{BASE}/{contact_id}", json={"email": payload["email"]})
    assert response.status_code == 200


def test_put_replaces_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    response = client.put(
        f"{BASE}/{contact_id}",
        json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["full_name"] == "Grace Hopper"
    assert body["company"] is None  # omitted fields are cleared by PUT


def test_put_missing_contact_returns_404(client):
    response = client.put(
        f"{BASE}/9999",
        json={"first_name": "A", "last_name": "B", "email": "ab@example.com"},
    )
    assert response.status_code == 404


def test_delete_contact(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert client.get(f"{BASE}/{contact_id}").status_code == 404
    assert client.delete(f"{BASE}/{contact_id}").status_code == 404


def _address_count() -> int:
    from sqlalchemy import func, select

    from app.database import SessionLocal
    from app.models import Address

    with SessionLocal() as db:
        return db.execute(select(func.count()).select_from(Address)).scalar_one()


def test_create_with_addresses_round_trip(client, payload):
    created = client.post(BASE, json=payload).json()

    assert len(created["addresses"]) == 1
    address = created["addresses"][0]
    assert isinstance(address["id"], str) and address["id"]
    assert address["contact_id"] == created["id"]
    assert address["type"] == "Work"
    assert address["street"] == "1 Market St, Suite 400"

    fetched = client.get(f"{BASE}/{created['id']}").json()
    assert fetched["addresses"] == created["addresses"]


def test_addresses_default_to_empty_list(client):
    created = client.post(
        BASE, json={"first_name": "Grace", "last_name": "Hopper", "email": "grace@example.com"}
    ).json()
    assert created["addresses"] == []


def test_address_requires_known_type(client, payload):
    bad = {**payload, "addresses": [{"type": "Castle", "street": "1 Main St"}]}
    assert client.post(BASE, json=bad).status_code == 422


def test_address_requires_street(client, payload):
    bad = {**payload, "addresses": [{"type": "Home", "street": ""}]}
    assert client.post(BASE, json=bad).status_code == 422


def test_put_replaces_address_set(client, payload):
    created = client.post(BASE, json=payload).json()
    old_id = created["addresses"][0]["id"]

    replaced = client.put(
        f"{BASE}/{created['id']}",
        json={
            **payload,
            "addresses": [
                {"type": "Home", "street": "221B Baker St", "city": "London", "country": "UK"},
                {"type": "Other", "street": "PO Box 42"},
            ],
        },
    ).json()

    assert [a["type"] for a in replaced["addresses"]] == ["Home", "Other"]
    assert old_id not in {a["id"] for a in replaced["addresses"]}
    assert _address_count() == 2  # the replaced row is gone, not orphaned


def test_put_without_addresses_clears_them(client, payload):
    created = client.post(BASE, json=payload).json()
    replaced = client.put(
        f"{BASE}/{created['id']}",
        json={"first_name": "Ada", "last_name": "Lovelace", "email": "ada@example.com"},
    ).json()
    assert replaced["addresses"] == []
    assert _address_count() == 0


def test_patch_without_addresses_keeps_them(client, payload):
    created = client.post(BASE, json=payload).json()
    patched = client.patch(f"{BASE}/{created['id']}", json={"phone": "+1-000-000-0000"}).json()
    assert patched["addresses"] == created["addresses"]


def test_patch_with_addresses_replaces_them(client, payload):
    created = client.post(BASE, json=payload).json()
    patched = client.patch(
        f"{BASE}/{created['id']}",
        json={"addresses": [{"type": "Home", "street": "221B Baker St"}]},
    ).json()
    assert [a["street"] for a in patched["addresses"]] == ["221B Baker St"]
    assert _address_count() == 1


def test_patch_null_addresses_clears_them(client, payload):
    created = client.post(BASE, json=payload).json()
    patched = client.patch(f"{BASE}/{created['id']}", json={"addresses": None})
    assert patched.status_code == 200
    assert patched.json()["addresses"] == []
    assert _address_count() == 0


def test_delete_contact_cascades_addresses(client, payload):
    contact_id = client.post(BASE, json=payload).json()["id"]
    assert _address_count() == 1
    assert client.delete(f"{BASE}/{contact_id}").status_code == 204
    assert _address_count() == 0


PHOTO = "data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgYGBgAAAABQABh6FO1AAAAABJRU5ErkJggg=="


def test_photo_round_trip(client, payload):
    created = client.post(BASE, json={**payload, "photo": PHOTO}).json()
    assert created["photo"] == PHOTO
    assert client.get(f"{BASE}/{created['id']}").json()["photo"] == PHOTO


def test_photo_defaults_to_null(client, payload):
    assert client.post(BASE, json=payload).json()["photo"] is None


def test_put_resending_photo_keeps_it(client, payload):
    created = client.post(BASE, json={**payload, "photo": PHOTO}).json()
    replaced = client.put(f"{BASE}/{created['id']}", json={**payload, "photo": created["photo"]})
    assert replaced.status_code == 200
    assert replaced.json()["photo"] == PHOTO


def test_photo_rejects_non_data_url(client, payload):
    response = client.post(BASE, json={**payload, "photo": "https://example.com/ada.png"})
    assert response.status_code == 422


def test_photo_rejects_malformed_base64(client, payload):
    for bad in (
        "data:image/png;base64,not-base64",  # invalid base64 alphabet
        "data:image/png,plain-text",  # missing ;base64 marker
        "data:image/png;base64,",  # empty payload
        "data:image/png;base64,AAA",  # bad padding
    ):
        response = client.post(BASE, json={**payload, "photo": bad})
        assert response.status_code == 422, f"accepted malformed photo: {bad!r}"


def test_photo_rejects_unsupported_image_type(client, payload):
    response = client.post(BASE, json={**payload, "photo": "data:image/svg+xml;base64,AAAA"})
    assert response.status_code == 422


def test_photo_blank_is_stored_as_null(client, payload):
    assert client.post(BASE, json={**payload, "photo": ""}).json()["photo"] is None


def test_root_lists_entrypoints(client):
    body = client.get("/").json()
    assert body["contacts"] == BASE

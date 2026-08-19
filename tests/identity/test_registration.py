from sti_equations.identity.api import UserCreate


def test_public_registration_cannot_choose_teacher_role() -> None:
    request = UserCreate.model_validate(
        {"email": "student@example.com", "password": "password123", "role": "teacher"}
    )
    assert "role" not in request.model_dump()

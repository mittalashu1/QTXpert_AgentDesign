from app.schemas.auth import UserLogin


def test_login_email_is_normalized():
    payload = UserLogin(email="  Admin@QTXpert.com  ", password="secret")
    assert str(payload.email) == "admin@qtxpert.com"
